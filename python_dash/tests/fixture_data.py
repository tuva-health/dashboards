"""Synthetic data for the MSSP ACO benchmark tests, and the DuckDB it is built into.

Every row here is invented. The numbers are chosen so the expected
rollups are exact and the variance sign flips between rates.

Assigned members, performance year 2026 (flat 1000, cap factor 0.8):

Practice A  P1 (aged/dual, scored) pays 1600/month, P2 (aged/dual, no
            score) pays 500/month. Enrollment-type rate 1200. P1's risk
            ratio 1.5 gives an uncapped risk-adjusted rate of 1800, capped
            by the year's factor to 1440. P2 has no risk-adjusted rate.
Practice B  P3 (disabled, scored) pays 700/month against a type rate of
            800, ratio 0.5, so 400 uncapped and 320 capped. P4 has no
            resolved enrollment type and carries the flat rate only.

Non-assigned members (data-sharing only), performance year 2026:

Practice C  P5, P6, P7 pay 550/month. All are aged/non-dual with a type
            rate of 600, well under the flat rate, so the enrollment-type
            benchmark over the full population is pulled away from the flat
            one by the enrollment mix rather than by spending. Score 1.0
            against a BY3 type score of 1.25, ratio 0.8, so 480 uncapped and
            384 capped.

Performance year 2025 (flat 950, cap factor 1.0, type rates 100 lower):
one month (202512) for P1, P3 and P5, paying what they always pay.

Two months (202601, 202602) per member in 2026, one member-month per row.

The BY3 enrollment-type score on each benchmark row is the member's score
over their ratio (1.0 for P1 and P3), and NULL where the ratio is NULL (P2
has no score, P4 no enrollment type).

`conftest.py` turns `build_duckdb` into pytest fixtures; the tests import
the row counts from here.
"""

from __future__ import annotations

from pathlib import Path

import duckdb
import pandas as pd

MONTHS = ["202601", "202602"]
PRIOR_MONTHS = ["202512"]
PRIOR_YEAR_MEMBERS = {"P1", "P3", "P5"}

MEMBERS = [
    # person_id, practice, provider, paid, enrollment_type, risk_score,
    # risk_ratio, enrollment_type_rate, risk_adjusted_rate, is_assigned
    ("P1", "Practice A", "Dr One", 1600.0, "aged_dual", 1.5, 1.5, 1200.0, 1800.0, True),
    ("P2", "Practice A", "Dr One", 500.0, "aged_dual", None, None, 1200.0, None, True),
    ("P3", "Practice B", "Dr Two", 700.0, "disabled", 0.5, 0.5, 800.0, 400.0, True),
    ("P4", "Practice B", "Dr Three", 100.0, None, 1.1, None, None, None, True),
    ("P5", "Practice C", "Dr Four", 550.0, "aged_non_dual", 1.0, 0.8, 600.0, 480.0, False),
    ("P6", "Practice C", "Dr Four", 550.0, "aged_non_dual", 1.0, 0.8, 600.0, 480.0, False),
    ("P7", "Practice C", "Dr Four", 550.0, "aged_non_dual", 1.0, 0.8, 600.0, 480.0, False),
]

# Per performance year: flat rate, cap factor, shift applied to the 2026
# type and risk-adjusted rates, and the delivery the rates came from.
YEARS = {
    2026: {"flat": 1000.0, "cap": 0.8, "rate_shift": 0.0,
           "period": "2026Q2", "submission": "BENCH-T26"},
    2025: {"flat": 950.0, "cap": 1.0, "rate_shift": -100.0,
           "period": "2025Q4", "submission": "BENCH-T25"},
}
FLAT_RATE = YEARS[2026]["flat"]
CAP_FACTOR = YEARS[2026]["cap"]

# Row counts the tests check the loaders against.
N_MEMBER_MONTHS = len(MEMBERS) * len(MONTHS) + len(PRIOR_YEAR_MEMBERS) * len(PRIOR_MONTHS)
N_ASSIGNED_2026 = sum(m[-1] for m in MEMBERS) * len(MONTHS)


def _member_months_of(pid: str) -> list[tuple[int, str]]:
    months = [(2026, ym) for ym in MONTHS]
    if pid in PRIOR_YEAR_MEMBERS:
        months += [(2025, ym) for ym in PRIOR_MONTHS]
    return months


def _member_month_frames() -> dict[str, pd.DataFrame]:
    fact_rows, dim_rows, bench_rows = [], [], []
    for pid, practice, provider, paid, etype, score, ratio, et_rate, ra_rate, assigned in MEMBERS:
        for year, ym in _member_months_of(pid):
            y = YEARS[year]
            sk = f"{pid}|{ym}"
            fact_rows.append({
                "person_id": pid, "data_source": "synthetic", "year_month": ym,
                "year_nbr": str(year), "member_month_sk": sk,
                "patient_source_key": f"{pid}|synthetic", "member_months": 1,
                "total_paid": paid, "medical_paid": paid, "pharmacy_paid": 0.0,
                "normalized_risk_score": score if score is not None else 1.0,
            })
            dim_rows.append({
                "person_id": pid, "year_month": ym, "payer": "synthetic",
                "payer_attributed_provider": provider,
                "payer_attributed_provider_practice": practice,
                "custom_attributed_provider": None,
            })
            type_rate = et_rate + y["rate_shift"] if et_rate is not None else None
            # The risk-adjusted rate is the type rate times the ratio.
            ra = type_rate * ratio if type_rate is not None and ratio is not None else None
            assert (ra is None) == (ra_rate is None)
            capped = ra * y["cap"] if ra is not None else None
            by3 = score / ratio if score is not None and ratio is not None else None
            bench_rows.append({
                "member_month_sk": sk, "person_id": pid, "data_source": "synthetic",
                "patient_source_key": f"{pid}|synthetic", "year_month": ym,
                "performance_year": year, "aco_id": "ACO-TEST", "is_assigned": assigned,
                "enrollment_type": etype, "risk_score": score, "risk_ratio": ratio,
                "by3_enrollment_type_risk_score": by3,
                "flat_benchmark_pmpm": y["flat"],
                "enrollment_type_benchmark_pmpm": type_rate,
                "risk_adjusted_benchmark_pmpm": ra,
                "cap_factor": y["cap"],
                "risk_adjusted_benchmark_pmpm_capped": capped,
                "total_paid": paid,
                "variance_to_flat": paid - y["flat"],
                "variance_to_enrollment_type": paid - type_rate if type_rate is not None else None,
                "variance_to_risk_adjusted": paid - ra if ra is not None else None,
                "variance_to_risk_adjusted_capped": paid - capped if capped is not None else None,
                "has_benchmark": True, "benchmark_period": y["period"],
                "benchmark_submission_id": y["submission"],
                "is_agreement_defaulted": False,
            })
    members = pd.DataFrame([
        {"person_id": pid, "first_name": f"First{pid}", "last_name": f"Last{pid}",
         "age": 70, "sex": "female", "birth_date": "1956-01-01", "address": "1 Test St",
         "city": "Testville", "state": "ZZ", "zip_code": "00000", "race": None,
         "data_source": "synthetic"}
        for pid, *_ in MEMBERS
    ])
    # Columns that are NULL on every synthetic row must still register in
    # DuckDB as VARCHAR, as they are in a real semantic layer; an untyped
    # all-None column would come back as an integer NA instead of None.
    dim_mm = pd.DataFrame(dim_rows).astype({"custom_attributed_provider": "string"})
    members = members.astype({"race": "string"})
    return {
        "fact_member_months": pd.DataFrame(fact_rows),
        "dim_member_months": dim_mm,
        "dim_member": members,
        "fact_member_month_benchmark": pd.DataFrame(bench_rows),
    }


def _aco_quarter_frame() -> pd.DataFrame:
    common = {"aco_id": "ACO-TEST", "risk_score_cap": 0.03, "cap_upper_bound": 1.03,
              "estimated_msr": 0.02}
    return pd.DataFrame([
        # Earlier quarter of 2026: carried, but not the current projection.
        {**common, "performance_year": 2026, "period": "2026Q1", "quarter_num": 1,
         "is_current_projection": False, "benchmark_submission_id": "BENCH-T26",
         "quarterly_submission_id": "QTR-T26-1",
         "mean_projected_updated_benchmark_pmpm": 900.0,
         "aco_expenditure_per_capita_pmpm": 950.0,
         "projected_savings_percentage": -0.0556, "msr_basis_applied": "variable",
         "savings_status": "no_savings", "aggregate_risk_ratio": 1.4,
         "cap_factor": 1.03 / 1.4, "is_cap_binding": True,
         "risk_adjusted_benchmark_pmpm": 1050.0, "national_growth_projected": 1.05,
         "cap_upper_bound_scenario": 1.08, "is_cap_binding_scenario": True,
         "is_agreement_defaulted": False},
        {**common, "performance_year": 2026, "period": "2026Q2", "quarter_num": 2,
         "is_current_projection": True, "benchmark_submission_id": "BENCH-T26",
         "quarterly_submission_id": "QTR-T26-2",
         "mean_projected_updated_benchmark_pmpm": 1000.0,
         "aco_expenditure_per_capita_pmpm": 950.0,
         "projected_savings_percentage": 0.05, "msr_basis_applied": "fixed",
         "savings_status": "above_msr", "aggregate_risk_ratio": 1.2875,
         "cap_factor": CAP_FACTOR, "is_cap_binding": True,
         "risk_adjusted_benchmark_pmpm": 1100.0, "national_growth_projected": 1.05,
         "cap_upper_bound_scenario": 1.08, "is_cap_binding_scenario": True,
         "is_agreement_defaulted": False},
        # Prior year: cap not binding, agreement row defaulted, no scenario.
        {**common, "performance_year": 2025, "period": "2025Q4", "quarter_num": 4,
         "is_current_projection": True, "benchmark_submission_id": "BENCH-T25",
         "quarterly_submission_id": "QTR-T25-4",
         "mean_projected_updated_benchmark_pmpm": 950.0,
         "aco_expenditure_per_capita_pmpm": 1000.0,
         "projected_savings_percentage": -0.0526, "msr_basis_applied": "variable",
         "savings_status": "no_savings", "aggregate_risk_ratio": 0.9,
         "cap_factor": 1.0, "is_cap_binding": False,
         "risk_adjusted_benchmark_pmpm": 900.0, "national_growth_projected": None,
         "cap_upper_bound_scenario": None, "is_cap_binding_scenario": None,
         "is_agreement_defaulted": True},
    ])


def build_duckdb(path: Path, *, with_benchmark: bool, with_surrogate_key: bool = True) -> Path:
    """`with_surrogate_key=False` mimics a `fact_member_months` that predates
    `member_month_sk`; the benchmark fact still carries it."""
    frames = _member_month_frames()
    if with_benchmark:
        frames["fact_benchmark_aco_quarter"] = _aco_quarter_frame()
    else:
        frames.pop("fact_member_month_benchmark")
    if not with_surrogate_key:
        frames["fact_member_months"] = frames["fact_member_months"].drop(
            columns=["member_month_sk"]
        )
    con = duckdb.connect(str(path))
    try:
        con.execute("CREATE SCHEMA semantic_layer")
        for name, frame in frames.items():
            con.register("src", frame)
            con.execute(f"CREATE TABLE semantic_layer.{name} AS SELECT * FROM src")
            con.unregister("src")
    finally:
        con.close()
    return path
