"""Benchmark-versus-actual aggregation for the MSSP ACO dashboard.

Pure pandas, no Dash and no warehouse: `layout.py` feeds these the lazily
loaded frames, and the tests feed them a synthetic DuckDB.

`semantic_layer.fact_member_month_benchmark` is one row per member-month,
one to one with `fact_member_months`. It carries the surrogate key
`member_month_sk` (`person_id || '|' || year_month`) and the natural key
`(person_id, year_month)`; the dashboard joins on the natural key so that
nothing outside the benchmark elements depends on the surrogate key being
present in `fact_member_months`. Each row carries four benchmark rates:
flat, by enrollment type, risk-adjusted (uncapped), and risk-adjusted under
the ACO's aggregate cap. A rate is NULL where the fact could not compute it
— every rate when the year has no projection, the risk-adjusted rates when
the member has no CMS score, the type rate when no enrollment type resolved.

A rollup here compares actual spend to the selected rate over the *same*
member-months: rows whose selected rate is NULL are left out of both the
benchmark side and the matched actual, and are counted as excluded, so a
practice's benchmark PMPM and the actual PMPM it is set against cover one
population. Variance is actual minus benchmark; positive means spending
above the benchmark.

Which member-months a comparison runs over is a `Population`: assigned
members only (the ACO's assigned beneficiaries, `is_assigned` on the fact)
or every member-month, and one performance year or all of them. The
benchmark was built for the assigned population, and on it the flat and
enrollment-type rates agree by construction; the non-assigned data-sharing
members can carry a very different enrollment mix, so on the full
population the two rates drift apart for mix reasons rather than
performance. `filter_population` narrows a merged frame before `rollup`.

The risk figures the dashboard shows come from the same fact: `risk_score`
is the CMS prospective HCC score from the assignment list, the score the
risk-adjusted rates use, `by3_enrollment_type_risk_score` the BY3 score for
the member's enrollment type, and `risk_ratio` the first over the second.
Tuva's `normalized_risk_score` on `fact_member_months` is a CMS-HCC MA-model
score no rate uses; the dashboard falls back to it only without the fact.
"""

from __future__ import annotations

from typing import NamedTuple

import pandas as pd

SURROGATE_KEY = "member_month_sk"  # carried on the fact for reference
JOIN_KEYS = ["person_id", "year_month"]  # the natural key the dashboard joins on
UNATTRIBUTED = "(unattributed)"


class Rate(NamedTuple):
    key: str
    label: str
    column: str


class Population(NamedTuple):
    """The member-months a benchmark comparison runs over.

    `assigned_only` keeps the member-months the benchmark fact flags
    `is_assigned`; a member-month the fact does not cover has no flag and is
    outside the assigned population. `year` keeps one calendar year of
    `year_month`, which is the performance year on covered rows; None keeps
    every year.
    """

    assigned_only: bool = True
    year: int | None = None

    def describe(self) -> str:
        """Short label for captions, e.g. 'Assigned members, PY2026'."""
        who = "Assigned members" if self.assigned_only else "All members"
        when = f"PY{self.year}" if self.year is not None else "all performance years"
        return f"{who}, {when}"


RATES: dict[str, Rate] = {
    r.key: r
    for r in (
        Rate("flat", "Flat", "flat_benchmark_pmpm"),
        Rate("enrollment_type", "Enrollment type", "enrollment_type_benchmark_pmpm"),
        Rate("risk_adjusted_capped", "Risk-adjusted (capped)",
             "risk_adjusted_benchmark_pmpm_capped"),
        Rate("risk_adjusted", "Risk-adjusted (uncapped)", "risk_adjusted_benchmark_pmpm"),
    )
}
DEFAULT_RATE = "flat"
RATE_COLUMNS = [r.column for r in RATES.values()]

ROLLUP_COLUMNS = [
    "member_months",
    "benchmark_member_months",
    "excluded_member_months",
    "actual_pmpm",
    "benchmark_pmpm",
    "variance_pmpm",
]


def rate(key: str | None) -> Rate:
    """The selected rate, falling back to the default for an unknown key."""
    return RATES.get(key or DEFAULT_RATE, RATES[DEFAULT_RATE])


def nullable_bool(value) -> bool | None:
    """A warehouse boolean that may have come back as NULL, numpy, or object."""
    if value is None or (not isinstance(value, str) and pd.isna(value)):
        return None
    return bool(value)


def merge_benchmark(member_months: pd.DataFrame, bench: pd.DataFrame) -> pd.DataFrame:
    """Left-join the benchmark fact onto member months on `(person_id, year_month)`.

    Every member-month is kept. A month the fact does not cover — or every
    month, when the fact is absent and `bench` is the empty frame the safe
    query returns — carries NULL rates and counts as excluded in `rollup`.
    The rate columns are always present on the result.
    """
    has_keys = all(k in member_months.columns for k in JOIN_KEYS) and all(
        k in bench.columns for k in JOIN_KEYS
    )
    if has_keys:
        extra = [c for c in bench.columns if c in JOIN_KEYS or c not in member_months.columns]
        merged = member_months.merge(bench[extra], on=JOIN_KEYS, how="left")
    else:
        merged = member_months.copy()
    for column in RATE_COLUMNS:
        if column not in merged.columns:
            merged[column] = float("nan")
    return merged


def calendar_year(year_month: pd.Series) -> pd.Series:
    """The year of a `year_month` key such as '202601' (or 202601); NaN if unparseable."""
    return pd.to_numeric(year_month.astype(str).str[:4], errors="coerce")


def filter_population(df: pd.DataFrame, population: Population) -> pd.DataFrame:
    """The rows of a merged member-month frame inside `population`.

    Filters on `year_month` rather than the fact's `performance_year` so an
    uncovered member-month (NULL rates, counted as excluded downstream) still
    belongs to its year when the population is not assigned-only.
    """
    keep = pd.Series(True, index=df.index)
    if population.assigned_only:
        assigned = df["is_assigned"] if "is_assigned" in df.columns else []
        keep &= pd.Series([nullable_bool(v) is True for v in assigned], index=df.index)
    if population.year is not None:
        keep &= calendar_year(df["year_month"]) == int(population.year)
    return df[keep]


def _weighted_mean(values: pd.Series, weights: pd.Series) -> float:
    """Mean of `values` weighted by `weights` over the rows where a value is present."""
    values = pd.to_numeric(values, errors="coerce")
    present = values.notna()
    total = weights[present].sum()
    return float((values[present] * weights[present]).sum() / total) if total else float("nan")


def risk_summary(df: pd.DataFrame) -> pd.Series:
    """The CMS risk figures of a member-month frame, weighted by member-months.

    `mean_risk_score` is over the scored member-months, whose count is
    `scored_member_months`; unscored member-months stay out of the mean but
    are still in the frame's member-month count. `mean_risk_ratio` and
    `mean_by3_risk_score` are over the member-months that carry each, which
    can be fewer: a member with a score but no resolved enrollment type has
    no BY3 score and no ratio. Each is NaN where nothing carries it.
    """
    weights = pd.to_numeric(df["member_months"], errors="coerce").fillna(0)
    out = {"scored_member_months": 0.0}
    for column, name in (("risk_score", "mean_risk_score"), ("risk_ratio", "mean_risk_ratio"),
                         ("by3_enrollment_type_risk_score", "mean_by3_risk_score")):
        out[name] = _weighted_mean(df[column], weights) if column in df.columns else float("nan")
    if "risk_score" in df.columns:
        scored = pd.to_numeric(df["risk_score"], errors="coerce").notna()
        out["scored_member_months"] = float(weights[scored].sum())
    return pd.Series(out)


def rollup(df: pd.DataFrame, group_col: str, rate_key: str | None) -> pd.DataFrame:
    """Actual against the selected benchmark rate, by `group_col`.

    Returns one row per group with `member_months` (all), the
    `benchmark_member_months` that carry the rate, the
    `excluded_member_months` that do not, and three PMPMs over the covered
    member-months: `actual_pmpm`, `benchmark_pmpm`, and their difference
    `variance_pmpm` (actual minus benchmark). PMPMs are NaN where no
    member-month carries the rate.
    """
    r = rate(rate_key)
    if df.empty:
        return pd.DataFrame(columns=[group_col, *ROLLUP_COLUMNS])

    member_months = pd.to_numeric(df["member_months"], errors="coerce").fillna(0)
    paid = pd.to_numeric(df["total_paid"], errors="coerce").fillna(0)
    rate_values = pd.to_numeric(df[r.column], errors="coerce")
    covered = rate_values.notna()

    parts = pd.DataFrame({
        group_col: df[group_col].fillna(UNATTRIBUTED),
        "member_months": member_months,
        "benchmark_member_months": member_months.where(covered, 0),
        "_paid": paid.where(covered, 0),
        "_benchmark": (rate_values * member_months).where(covered, 0),
    })
    out = parts.groupby(group_col, sort=True).sum().reset_index()

    denominator = out["benchmark_member_months"].where(out["benchmark_member_months"] > 0)
    out["actual_pmpm"] = out["_paid"] / denominator
    out["benchmark_pmpm"] = out["_benchmark"] / denominator
    out["variance_pmpm"] = out["actual_pmpm"] - out["benchmark_pmpm"]
    out["excluded_member_months"] = out["member_months"] - out["benchmark_member_months"]
    return out[[group_col, *ROLLUP_COLUMNS]]


def totals(df: pd.DataFrame, rate_key: str | None) -> pd.Series:
    """The `rollup` of the whole frame as a single row."""
    if df.empty:
        return pd.Series({
            "member_months": 0, "benchmark_member_months": 0, "excluded_member_months": 0,
            "actual_pmpm": float("nan"), "benchmark_pmpm": float("nan"),
            "variance_pmpm": float("nan"),
        })
    out = rollup(df.assign(_all="all"), "_all", rate_key)
    return out.iloc[0][ROLLUP_COLUMNS]


def projection_years(aco_quarters: pd.DataFrame) -> list[int]:
    """Every performance year with a row in `fact_benchmark_aco_quarter`, ascending."""
    if aco_quarters.empty or "performance_year" not in aco_quarters.columns:
        return []
    years = pd.to_numeric(aco_quarters["performance_year"], errors="coerce").dropna()
    return sorted({int(y) for y in years})


def latest_projection_year(aco_quarters: pd.DataFrame) -> int | None:
    """The default performance year: the latest with a projection, if any."""
    years = projection_years(aco_quarters)
    return years[-1] if years else None


def current_projections(aco_quarters: pd.DataFrame) -> pd.DataFrame:
    """The rows of `fact_benchmark_aco_quarter` the member rates are read from.

    One per ACO and performance year, flagged `is_current_projection` by the
    fact itself; earlier quarters of a year are carried in the fact but not
    returned here. Sorted by year.
    """
    if aco_quarters.empty or "is_current_projection" not in aco_quarters.columns:
        return aco_quarters.iloc[0:0]
    flag = aco_quarters["is_current_projection"].map(nullable_bool).fillna(False).astype(bool)
    sort_cols = [c for c in ("performance_year", "aco_id") if c in aco_quarters.columns]
    return aco_quarters[flag].sort_values(sort_cols).reset_index(drop=True)
