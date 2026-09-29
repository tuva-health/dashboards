"""MSSP ACO dashboard: benchmark facts beside actual spend.

Runs the query and aggregation functions against the synthetic DuckDB in
conftest.py. Expected figures are worked in the conftest docstring.

The layout callbacks default to the population the controls start on:
assigned members only, in the latest performance year with a projection
(PY2026 here). Tests that name neither control run on that default.
"""

from __future__ import annotations

import math

import dash_bootstrap_components as dbc
import pytest
from dash import dash_table, dcc, html

from dashboards.mssp_aco_dashboard import benchmark, layout, queries
from tests.fixture_data import N_ASSIGNED_2026, N_MEMBER_MONTHS

PRACTICE = "payer_attributed_provider_practice"
PROVIDER = "payer_attributed_provider"


def _row(df, group_col, value):
    hit = df[df[group_col] == value]
    assert len(hit) == 1, f"{value!r} not found once in {df[group_col].tolist()}"
    return hit.iloc[0]


def _find(component, cls):
    """Depth-first search of a Dash component tree for instances of cls."""
    found = []
    stack = [component]
    while stack:
        node = stack.pop()
        if isinstance(node, (list, tuple)):  # callbacks may return a list of children
            stack.extend(node)
            continue
        if isinstance(node, cls):
            found.append(node)
        children = getattr(node, "children", None)
        if children is not None and not isinstance(children, (str, int, float)):
            stack.append(children)
    return found


# -- queries -----------------------------------------------------------------

def test_member_months_do_not_depend_on_the_surrogate_key(full_db):
    mm = queries.load_member_months()
    assert len(mm) == N_MEMBER_MONTHS
    assert "member_month_sk" not in mm.columns
    assert {"person_id", "year_month"} <= set(mm.columns)


def test_member_month_benchmark_joins_one_to_one_on_the_natural_key(full_db):
    bench = queries.load_member_month_benchmark()
    assert len(bench) == N_MEMBER_MONTHS
    # The fact carries the surrogate key for reference; the join uses the natural key.
    assert bench["member_month_sk"].is_unique
    assert not bench.duplicated(["person_id", "year_month"]).any()
    joined = benchmark.merge_benchmark(queries.load_member_months(), bench)
    assert len(joined) == N_MEMBER_MONTHS
    assert joined["flat_benchmark_pmpm"].notna().all()
    # Each member-month picked up its own row, not a neighbour's.
    p1_jan = joined[(joined["person_id"] == "P1") & (joined["year_month"] == "202601")]
    assert p1_jan["risk_adjusted_benchmark_pmpm_capped"].item() == pytest.approx(1440.0)
    # P2 has no score and P4 no enrollment type: their risk-adjusted rate is NULL.
    assert joined["risk_adjusted_benchmark_pmpm_capped"].isna().sum() == 4


def test_benchmark_renders_when_member_months_lack_the_surrogate_key(legacy_db):
    mm = queries.load_member_months()
    assert len(mm) == N_MEMBER_MONTHS  # the existing view is intact
    joined = benchmark.merge_benchmark(mm, queries.load_member_month_benchmark())
    assert joined["flat_benchmark_pmpm"].notna().all()
    assert layout.build_layout() is not None
    assert "BENCH-T26" in str(layout._render_aco_panel())
    kpis, practice_section = layout._render_program_benchmark("flat")
    assert len(_find(kpis, dbc.Card)) == 5
    table = _find(practice_section, dash_table.DataTable)[0]
    by_practice = {r["Practice"]: r for r in table.data}
    assert by_practice["Practice A"]["Benchmark PMPM"] == pytest.approx(1000.0)
    assert by_practice["Practice A"]["Variance"] == pytest.approx(50.0)


def test_absent_benchmark_tables_return_empty_frames(no_benchmark_db):
    bench = queries.load_member_month_benchmark()
    aco = queries.load_benchmark_aco_quarter()
    assert bench.empty and aco.empty
    assert "risk_adjusted_benchmark_pmpm_capped" in bench.columns
    assert "is_current_projection" in aco.columns
    # The existing member-month load is untouched by the missing facts.
    assert len(queries.load_member_months()) == N_MEMBER_MONTHS


# -- rollups -----------------------------------------------------------------

DEFAULT_POPULATION = benchmark.Population(assigned_only=True, year=2026)
FULL_2026 = benchmark.Population(assigned_only=False, year=2026)


@pytest.fixture
def all_joined(full_db):
    """Every member-month with its benchmark row: both years, assigned or not."""
    return benchmark.merge_benchmark(
        queries.load_member_months(), queries.load_member_month_benchmark()
    )


@pytest.fixture
def joined(all_joined):
    """The default population the dashboard opens on: assigned members, PY2026.

    The rollup figures below were worked for these member-months before the
    fixture grew non-assigned members and a prior year, so they hold as is.
    """
    return benchmark.filter_population(all_joined, DEFAULT_POPULATION)


def test_practice_rollup_flat_rate(joined):
    out = benchmark.rollup(joined, PRACTICE, "flat")
    a = _row(out, PRACTICE, "Practice A")
    assert a["benchmark_member_months"] == 4
    assert a["excluded_member_months"] == 0
    assert a["actual_pmpm"] == pytest.approx(1050.0)
    assert a["benchmark_pmpm"] == pytest.approx(1000.0)
    assert a["variance_pmpm"] == pytest.approx(50.0)  # above benchmark: positive

    b = _row(out, PRACTICE, "Practice B")
    assert b["actual_pmpm"] == pytest.approx(400.0)
    assert b["variance_pmpm"] == pytest.approx(-600.0)


def test_variance_sign_flips_with_the_selected_rate(joined):
    flat = _row(benchmark.rollup(joined, PRACTICE, "flat"), PRACTICE, "Practice A")
    by_type = _row(
        benchmark.rollup(joined, PRACTICE, "enrollment_type"), PRACTICE, "Practice A"
    )
    assert flat["variance_pmpm"] > 0
    assert by_type["benchmark_pmpm"] == pytest.approx(1200.0)
    assert by_type["variance_pmpm"] == pytest.approx(-150.0)


def test_null_rates_are_excluded_from_both_sides(joined):
    out = benchmark.rollup(joined, PRACTICE, "risk_adjusted_capped")
    a = _row(out, PRACTICE, "Practice A")
    # P2 (no score) drops out of the benchmark side and of the matched actual.
    assert a["member_months"] == 4
    assert a["benchmark_member_months"] == 2
    assert a["excluded_member_months"] == 2
    assert a["actual_pmpm"] == pytest.approx(1600.0)
    assert a["benchmark_pmpm"] == pytest.approx(1440.0)
    assert a["variance_pmpm"] == pytest.approx(160.0)

    b = _row(out, PRACTICE, "Practice B")
    assert b["excluded_member_months"] == 2  # P4: no enrollment type
    assert b["benchmark_pmpm"] == pytest.approx(320.0)
    assert b["variance_pmpm"] == pytest.approx(380.0)


def test_uncapped_rate_is_available(joined):
    out = benchmark.rollup(joined, PRACTICE, "risk_adjusted")
    a = _row(out, PRACTICE, "Practice A")
    assert a["benchmark_pmpm"] == pytest.approx(1800.0)
    assert a["variance_pmpm"] == pytest.approx(-200.0)


def test_provider_rollup(joined):
    out = benchmark.rollup(joined, PROVIDER, "enrollment_type")
    three = _row(out, PROVIDER, "Dr Three")
    assert three["benchmark_member_months"] == 0
    assert three["excluded_member_months"] == 2
    assert math.isnan(three["benchmark_pmpm"])
    assert math.isnan(three["variance_pmpm"])


def test_totals(joined):
    t = benchmark.totals(joined, "enrollment_type")
    assert t["member_months"] == N_ASSIGNED_2026 == 8
    assert t["excluded_member_months"] == 2
    assert t["actual_pmpm"] == pytest.approx(5600 / 6)
    assert t["benchmark_pmpm"] == pytest.approx(6400 / 6)
    assert t["variance_pmpm"] == pytest.approx(-800 / 6)


def test_rollup_of_empty_benchmark_is_empty(full_db):
    mm = queries.load_member_months()
    empty = benchmark.merge_benchmark(mm, queries.load_member_month_benchmark().iloc[0:0])
    assert len(empty) == len(mm)
    out = benchmark.rollup(empty, PRACTICE, "flat")
    assert (out["benchmark_member_months"] == 0).all()
    assert out["benchmark_pmpm"].isna().all()


# -- ACO panel ----------------------------------------------------------------

def test_current_projections_pick_one_row_per_year(full_db):
    aco = queries.load_benchmark_aco_quarter()
    assert len(aco) == 3
    current = benchmark.current_projections(aco)
    assert current["performance_year"].tolist() == [2025, 2026]
    assert current["period"].tolist() == ["2025Q4", "2026Q2"]
    py26 = current.iloc[1]
    assert bool(py26["is_cap_binding"]) is True
    assert py26["cap_factor"] == pytest.approx(0.8)
    assert py26["benchmark_submission_id"] == "BENCH-T26"
    py25 = current.iloc[0]
    assert bool(py25["is_cap_binding"]) is False
    assert bool(py25["is_agreement_defaulted"]) is True


# -- layout -------------------------------------------------------------------

def test_layout_builds_with_benchmark_facts(full_db):
    page = layout.build_layout()
    radios = _find(page, dbc.RadioItems)
    assert any(r.id == "mssp-benchmark-rate" for r in radios)
    # The projections panel is rendered by its callback, so the page itself
    # carries no card yet; see test_year_filter_selects_the_projection_card.
    assert any(getattr(d, "id", None) == "mssp-aco-panel" for d in _find(page, html.Div))


def test_program_callback_renders_kpis_and_practice_table(full_db):
    kpis, practice_section = layout._render_program_benchmark("flat")
    cards = _find(kpis, dbc.Card)
    assert len(cards) == 5
    tables = _find(practice_section, dash_table.DataTable)
    assert len(tables) == 1
    cols = [c["name"] for c in tables[0].columns]
    assert "Benchmark PMPM" in cols and "Variance" in cols and "Excluded MM" in cols
    by_practice = {r["Practice"]: r for r in tables[0].data}
    assert by_practice["Practice A"]["Variance"] == pytest.approx(50.0)
    assert by_practice["Practice B"]["Variance"] == pytest.approx(-600.0)


def test_practice_callback_shows_provider_benchmark(full_db):
    out = layout._render_practice("Practice A", "risk_adjusted_capped")
    tables = _find(out, dash_table.DataTable)
    assert len(tables) == 1
    by_provider = {r["Provider"]: r for r in tables[0].data}
    assert by_provider["Dr One"]["Benchmark PMPM"] == pytest.approx(1440.0)
    assert by_provider["Dr One"]["Variance"] == pytest.approx(160.0)
    assert by_provider["Dr One"]["Excluded MM"] == 2


def test_provider_callback_shows_benchmark_cards(full_db):
    out = layout._render_provider("Dr Two", "enrollment_type")
    labels = [c.children[0].children for c in _find(out, dbc.CardBody)]
    assert any("Benchmark PMPM" in str(lbl) for lbl in labels)
    assert any("Variance" in str(lbl) for lbl in labels)


def test_layout_without_benchmark_facts_shows_alert_and_keeps_the_rest(no_benchmark_db):
    page = layout.build_layout()
    assert page is not None
    kpis, practice_section = layout._render_program_benchmark("flat")
    assert _find(kpis, dbc.Alert), "benchmark KPI row should fall back to the alert"
    tables = _find(practice_section, dash_table.DataTable)
    assert len(tables) == 1
    cols = [c["name"] for c in tables[0].columns]
    assert "PMPM" in cols and "Benchmark PMPM" not in cols
    assert "ACO-TEST" not in str(page)

    out = layout._render_practice("Practice A", "flat")
    provider_cols = [c["name"] for c in _find(out, dash_table.DataTable)[0].columns]
    assert "Benchmark PMPM" not in provider_cols


def test_layout_builds_with_load_data_false(no_load_data):
    page = layout.build_layout()
    assert page is not None
    kpis, practice_section = layout._render_program_benchmark("flat")
    assert _find(kpis, dbc.Alert)


# -- population controls -------------------------------------------------------

def _card_values(component) -> dict[str, str]:
    """KPI card label -> headline value, from the card bodies in a tree."""
    out = {}
    for body in _find(component, dbc.CardBody):
        children = body.children
        if isinstance(children, list) and len(children) >= 2:
            out[str(children[0].children)] = str(children[1].children)
    return out


def _caption(section) -> str:
    texts = [p.children for p in _find(section, html.P) if isinstance(p.children, str)]
    hits = [t for t in texts if t.startswith(("Assigned members", "All members"))]
    assert len(hits) == 1, texts
    return hits[0]


def test_filter_population_by_assignment_and_year(all_joined):
    assert len(all_joined) == N_MEMBER_MONTHS
    assert len(benchmark.filter_population(all_joined, DEFAULT_POPULATION)) == 8
    assert len(benchmark.filter_population(all_joined, FULL_2026)) == 14
    assert len(benchmark.filter_population(all_joined, benchmark.Population(True, 2025))) == 2
    assert len(benchmark.filter_population(all_joined, benchmark.Population(False, 2025))) == 3
    assert len(benchmark.filter_population(all_joined, benchmark.Population(True, None))) == 10
    assert len(benchmark.filter_population(all_joined, benchmark.Population(False, None))) == 17
    # Member-months the benchmark fact does not cover have no assignment flag,
    # so they are outside the assigned population and inside the full one.
    uncovered = benchmark.merge_benchmark(
        queries.load_member_months(), queries.load_member_month_benchmark().iloc[0:0]
    )
    assert benchmark.filter_population(uncovered, benchmark.Population(True, None)).empty
    assert len(benchmark.filter_population(uncovered, FULL_2026)) == 14


def test_population_describes_itself():
    assert DEFAULT_POPULATION.describe() == "Assigned members, PY2026"
    assert benchmark.Population(False, None).describe() == "All members, all performance years"


def test_projection_years_come_from_the_aco_fact(full_db):
    aco = queries.load_benchmark_aco_quarter()
    assert benchmark.projection_years(aco) == [2025, 2026]
    assert benchmark.latest_projection_year(aco) == 2026
    assert benchmark.projection_years(aco.iloc[0:0]) == []
    assert benchmark.latest_projection_year(aco.iloc[0:0]) is None


def test_assigned_population_brings_the_flat_and_type_rates_together(all_joined):
    """The acceptance check: on the assigned population the KPI row's actual
    PMPM is the plain mean of total_paid, and the flat and enrollment-type
    benchmarks sit closer together than they do on the full population, whose
    non-assigned members carry a skewed enrollment-type mix."""
    assigned = benchmark.filter_population(all_joined, DEFAULT_POPULATION)
    full = benchmark.filter_population(all_joined, FULL_2026)

    kpis, _ = layout._render_program_benchmark("flat", True, 2026)
    values = _card_values(kpis)
    expected_actual = assigned["total_paid"].mean()
    assert expected_actual == pytest.approx(725.0)
    assert values["Actual PMPM"] == layout._pmpm(expected_actual)
    assert values["Flat Benchmark PMPM"] == "$1,000.00"
    assert values["Enrollment-Type Benchmark PMPM"] == layout._pmpm(6400 / 6)

    gap = {
        "assigned": abs(benchmark.totals(assigned, "flat")["benchmark_pmpm"]
                        - benchmark.totals(assigned, "enrollment_type")["benchmark_pmpm"]),
        "full": abs(benchmark.totals(full, "flat")["benchmark_pmpm"]
                    - benchmark.totals(full, "enrollment_type")["benchmark_pmpm"]),
    }
    assert gap["assigned"] == pytest.approx(200 / 3)
    assert gap["full"] == pytest.approx(500 / 3)
    assert gap["assigned"] < gap["full"]

    # The same gap is visible in the KPI row with the toggle off.
    off = _card_values(layout._render_program_benchmark("flat", False, 2026)[0])
    assert off["Actual PMPM"] == layout._pmpm(full["total_paid"].mean()) == "$650.00"
    assert off["Enrollment-Type Benchmark PMPM"] == layout._pmpm(10000 / 12)


def test_toggle_off_is_the_full_population(all_joined):
    """Off, the comparison runs over every member-month of the year with or
    without an assignment, which is what the dashboard showed before the toggle."""
    full = benchmark.filter_population(all_joined, FULL_2026)
    kpis, section = layout._render_program_benchmark("flat", False, 2026)
    table = _find(section, dash_table.DataTable)[0]
    by_practice = {r["Practice"]: r for r in table.data}
    assert set(by_practice) == {"Practice A", "Practice B", "Practice C"}
    assert by_practice["Practice C"]["Member Months"] == 6
    assert by_practice["Practice C"]["Variance"] == pytest.approx(-450.0)
    expected = benchmark.rollup(full, PRACTICE, "flat")
    for _, row in expected.iterrows():
        assert by_practice[row[PRACTICE]]["Actual PMPM"] == pytest.approx(row["actual_pmpm"])
    assert "All members, PY2026, 14 member-months; 0 excluded" in _caption(section)

    on_kpis, on_section = layout._render_program_benchmark("flat", True, 2026)
    on_table = _find(on_section, dash_table.DataTable)[0]
    assert {r["Practice"] for r in on_table.data} == {"Practice A", "Practice B"}
    assert "Assigned members, PY2026, 8 member-months; 0 excluded" in _caption(on_section)


@pytest.mark.parametrize("assigned_only, year, members, member_months", [
    (True, 2026, 4, 8), (False, 2026, 7, 14), (True, 2025, 2, 2), (False, 2025, 3, 3),
    (True, None, 4, 8),  # None is the latest projection year
])
def test_program_kpi_row_follows_the_population(full_db, assigned_only, year, members,
                                                member_months):
    """The headline row counts the same member-months as the caption below it."""
    values = _card_values(layout._render_program_kpis(assigned_only, year))
    assert values["Attributed Members"] == str(members)
    assert values["Member Months"] == str(member_months)
    _, section = layout._render_program_benchmark("flat", assigned_only, year)
    assert f"{member_months} member-months" in _caption(section)
    subs = [c.children[2].children for c in _find(layout._render_program_kpis(assigned_only, year),
                                                  dbc.CardBody) if len(c.children) > 2]
    assert benchmark.Population(assigned_only, year or 2026).describe() in subs


def test_program_kpi_row_values(all_joined):
    full = benchmark.filter_population(all_joined, FULL_2026)
    values = _card_values(layout._render_program_kpis(False, 2026))
    assert values["Total Paid"] == layout._money(full["total_paid"].sum()) == "$9,100"
    assert values["PMPM"] == "$650.00"
    assert "Avg Normalized Risk (Tuva)" not in values  # the CMS cards replace it


def test_program_kpi_row_without_benchmark_is_the_whole_frame(no_benchmark_db):
    values = _card_values(layout._render_program_kpis(True, None))
    assert values["Member Months"] == str(N_MEMBER_MONTHS)
    assert values["Attributed Members"] == "7"
    bodies = _find(layout._render_program_kpis(True, None), dbc.CardBody)
    assert all(len(b.children) == 2 for b in bodies), "no population label without the fact"


# -- risk cards ----------------------------------------------------------------

def _card_subs(component) -> dict[str, str]:
    """KPI card label -> subtitle, for the cards that have one."""
    return {
        str(b.children[0].children): str(b.children[2].children)
        for b in _find(component, dbc.CardBody)
        if isinstance(b.children, list) and len(b.children) > 2
    }


def _weighted(df, column):
    hit = df[df[column].notna()]
    return (hit[column] * hit["member_months"]).sum() / hit["member_months"].sum()


def test_risk_summary(all_joined):
    assigned = benchmark.filter_population(all_joined, DEFAULT_POPULATION)
    risk = benchmark.risk_summary(assigned)
    # P1 (1.5), P3 (0.5) and P4 (1.1) are scored, two months each; P2 is not.
    assert risk["scored_member_months"] == 6
    assert risk["mean_risk_score"] == pytest.approx(3.1 / 3)
    # P4 has a score but no enrollment type, so no BY3 score and no ratio.
    assert risk["mean_risk_ratio"] == pytest.approx(1.0)
    assert risk["mean_by3_risk_score"] == pytest.approx(1.0)

    full = benchmark.filter_population(all_joined, FULL_2026)
    risk = benchmark.risk_summary(full)
    assert risk["scored_member_months"] == 12
    assert risk["mean_risk_score"] == pytest.approx(_weighted(full, "risk_score"))
    assert risk["mean_risk_ratio"] == pytest.approx(0.88)
    assert risk["mean_by3_risk_score"] == pytest.approx(1.15)

    empty = benchmark.risk_summary(assigned.iloc[0:0])
    assert empty["scored_member_months"] == 0 and math.isnan(empty["mean_risk_score"])
    # A frame without the fact's columns has no CMS figures.
    plain = benchmark.risk_summary(assigned[["member_months", "total_paid"]])
    assert math.isnan(plain["mean_risk_score"]) and plain["scored_member_months"] == 0


@pytest.mark.parametrize("assigned_only, year", [(True, 2026), (False, 2026), (True, 2025)])
def test_headline_risk_cards_are_the_cms_scores(all_joined, assigned_only, year):
    frame = benchmark.filter_population(all_joined, benchmark.Population(assigned_only, year))
    row = layout._render_program_kpis(assigned_only, year)
    values, subs = _card_values(row), _card_subs(row)
    assert values["Avg CMS Risk Score"] == f"{_weighted(frame, 'risk_score'):.2f}"
    assert values["Avg Benchmark Risk Score"] == \
        f"{_weighted(frame, 'by3_enrollment_type_risk_score'):.2f}"
    scored = int(frame.loc[frame["risk_score"].notna(), "member_months"].sum())
    assert subs["Avg CMS Risk Score"] == \
        f"ratio to BY3 {_weighted(frame, 'risk_ratio'):.2f}; {scored:,} scored member-months"
    assert subs["Avg Benchmark Risk Score"] == "BY3 population, weighted by member-months"
    # Unscored member-months leave the mean but stay in the member-month count.
    unscored = int(frame.loc[frame["risk_score"].isna(), "member_months"].sum())
    assert values["Member Months"] == str(scored + unscored)
    assert "Avg Normalized Risk (Tuva)" not in values


def test_headline_risk_card_worked_figures(full_db):
    values, subs = (f(layout._render_program_kpis(True, 2026)) for f in (_card_values, _card_subs))
    assert values["Avg CMS Risk Score"] == "1.03"  # (1.5 + 0.5 + 1.1) / 3
    assert values["Avg Benchmark Risk Score"] == "1.00"
    assert subs["Avg CMS Risk Score"] == "ratio to BY3 1.00; 6 scored member-months"
    assert values["Member Months"] == "8"


def test_risk_card_falls_back_to_the_tuva_score_without_the_fact(no_benchmark_db):
    mm = queries.load_member_months()
    row = layout._render_program_kpis(True, None)
    values = _card_values(row)
    assert values["Avg Normalized Risk (Tuva)"] == f"{mm['normalized_risk_score'].mean():.2f}"
    assert "Avg CMS Risk Score" not in values and "Avg Benchmark Risk Score" not in values
    practice = _card_values(layout._render_practice("Practice A", "flat"))
    assert "Avg Normalized Risk (Tuva)" in practice and "Avg CMS Risk Score" not in practice


def test_practice_and_provider_risk_cards_follow_the_population(full_db):
    practice = layout._render_practice("Practice A", "flat", True, 2026)
    values, subs = _card_values(practice), _card_subs(practice)
    assert values["Avg CMS Risk Score"] == "1.50"  # P1 only; P2 is unscored
    assert subs["Avg CMS Risk Score"] == "ratio to BY3 1.50; 2 scored member-months"
    assert values["Avg Benchmark Risk Score"] == "1.00"
    provider = _card_values(layout._render_provider("Dr Four", "flat", False, 2026))
    assert provider["Avg CMS Risk Score"] == "1.00"
    assert provider["Avg Benchmark Risk Score"] == "1.25"


def test_rollup_tables_carry_the_cms_score_first_and_the_tuva_score_last(full_db):
    _, section = layout._render_program_benchmark("flat", True, 2026)
    table = _find(section, dash_table.DataTable)[0]
    cols = [c["name"] for c in table.columns]
    assert cols.index("Avg CMS Risk") < cols.index("Avg Risk (Tuva)") == len(cols) - 1
    assert "Avg Risk" not in cols
    by_practice = {r["Practice"]: r for r in table.data}
    assert by_practice["Practice A"]["Avg CMS Risk"] == pytest.approx(1.5)
    assert by_practice["Practice A"]["Avg Risk (Tuva)"] == pytest.approx(1.25)
    assert by_practice["Practice B"]["Avg CMS Risk"] == pytest.approx(0.8)

    out = layout._render_practice("Practice B", "flat", True, 2026)
    provider_cols = [c["name"] for c in _find(out, dash_table.DataTable)[0].columns]
    assert "Avg CMS Risk" in provider_cols and "Avg Risk (Tuva)" in provider_cols


def test_rollup_tables_keep_only_the_tuva_score_without_the_fact(no_benchmark_db):
    _, section = layout._render_program_benchmark("flat")
    cols = [c["name"] for c in _find(section, dash_table.DataTable)[0].columns]
    assert "Avg Risk (Tuva)" in cols and "Avg CMS Risk" not in cols


def test_year_filter_selects_the_member_months(full_db):
    kpis, section = layout._render_program_benchmark("flat", True, 2025)
    values = _card_values(kpis)
    assert values["Actual PMPM"] == "$1,150.00"  # P1 1600 and P3 700 in 202512
    assert values["Flat Benchmark PMPM"] == "$950.00"
    table = _find(section, dash_table.DataTable)[0]
    by_practice = {r["Practice"]: r for r in table.data}
    assert set(by_practice) == {"Practice A", "Practice B"}
    assert by_practice["Practice A"]["Member Months"] == 1
    assert by_practice["Practice A"]["Variance"] == pytest.approx(650.0)
    assert by_practice["Practice B"]["Variance"] == pytest.approx(-250.0)
    assert "Assigned members, PY2025, 2 member-months" in _caption(section)


def test_year_filter_selects_the_projection_card(full_db):
    latest = str(layout._render_aco_panel(None))
    assert "2026Q2" in latest and "BENCH-T26" in latest
    assert "2025Q4" not in latest and "2026Q1" not in latest
    assert str(layout._render_aco_panel(2026)) == latest

    prior = str(layout._render_aco_panel(2025))
    assert "2025Q4" in prior and "BENCH-T25" in prior and "2026Q2" not in prior

    missing = layout._render_aco_panel(2024)
    assert _find(missing, dbc.Alert), "a year without a projection should show the alert"
    assert "2024" in str(missing)


def test_year_without_projection_leaves_the_comparison_empty(full_db):
    kpis, section = layout._render_program_benchmark("flat", True, 2024)
    values = _card_values(kpis)
    assert values["Actual PMPM"] == "—" and values["Flat Benchmark PMPM"] == "—"
    assert _find(section, dbc.Alert) and not _find(section, dash_table.DataTable)


def test_controls_default_to_assigned_and_the_latest_projection_year(full_db):
    page = layout.build_layout()
    switches = [s for s in _find(page, dbc.Switch) if s.id == "mssp-benchmark-assigned-only"]
    assert len(switches) == 1 and switches[0].value is True
    years = [d for d in _find(page, dcc.Dropdown) if d.id == "mssp-benchmark-year"]
    assert len(years) == 1
    assert [o["value"] for o in years[0].options] == [2025, 2026]
    assert years[0].value == 2026
    assert years[0].clearable is False


def test_year_dropdown_is_empty_without_the_aco_fact(no_benchmark_db):
    page = layout.build_layout()
    years = [d for d in _find(page, dcc.Dropdown) if d.id == "mssp-benchmark-year"]
    assert len(years) == 1
    assert years[0].options == [] and years[0].value is None
    # The callbacks still answer with the alerts rather than raising.
    assert _find(layout._render_aco_panel(None), dbc.Alert)
    kpis, section = layout._render_program_benchmark("flat", True, None)
    assert _find(kpis, dbc.Alert) and _find(section, dash_table.DataTable)


def test_practice_tab_responds_to_both_controls(full_db):
    # Practice C is entirely non-assigned: empty under the default toggle...
    on = layout._render_practice("Practice C", "enrollment_type", True, 2026)
    assert not _find(on, dash_table.DataTable)
    assert _find(on, dbc.Alert)
    assert _card_values(on)["Members"] == "0"
    # ...and fully covered with it off.
    off = layout._render_practice("Practice C", "enrollment_type", False, 2026)
    table = _find(off, dash_table.DataTable)[0]
    by_provider = {r["Provider"]: r for r in table.data}
    assert by_provider["Dr Four"]["Benchmark PMPM"] == pytest.approx(600.0)
    assert by_provider["Dr Four"]["Variance"] == pytest.approx(-50.0)
    assert by_provider["Dr Four"]["Excluded MM"] == 0
    assert "All members, PY2026, 6 member-months; 0 excluded" in _caption(off)
    values = _card_values(off)
    assert values["Members"] == "3" and values["PMPM"] == "$550.00"

    # The year narrows the practice to its prior-year months.
    prior = layout._render_practice("Practice B", "enrollment_type", True, 2025)
    table = _find(prior, dash_table.DataTable)[0]
    by_provider = {r["Provider"]: r for r in table.data}
    assert set(by_provider) == {"Dr Two"}
    assert by_provider["Dr Two"]["Benchmark PMPM"] == pytest.approx(700.0)
    assert by_provider["Dr Two"]["Variance"] == pytest.approx(0.0)
    # Dr Three's unresolved enrollment type is excluded in 2026 only.
    current = layout._render_practice("Practice B", "enrollment_type", True, 2026)
    by_provider = {r["Provider"]: r for r in _find(current, dash_table.DataTable)[0].data}
    assert by_provider["Dr Three"]["Excluded MM"] == 2
    assert "2 excluded for lacking the enrollment type rate" in _caption(current)


def test_provider_tab_responds_to_both_controls(full_db):
    on = _card_values(layout._render_provider("Dr Four", "flat", True, 2026))
    assert on["Panel size"] == "0" and on["Benchmark PMPM (Flat)"] == "—"
    off = _card_values(layout._render_provider("Dr Four", "flat", False, 2026))
    assert off["Panel size"] == "3"
    assert off["Benchmark PMPM (Flat)"] == "$1,000.00" and off["Variance"] == "-$450.00"
    prior = _card_values(layout._render_provider("Dr One", "risk_adjusted", True, 2025))
    assert prior["Benchmark PMPM (Risk-adjusted (uncapped))"] == "$1,650.00"
    assert prior["Variance"] == "-$50.00"


@pytest.mark.parametrize("rate_key", list(benchmark.RATES))
@pytest.mark.parametrize("assigned_only", [True, False])
@pytest.mark.parametrize("year", [2025, 2026])
def test_every_rate_agrees_with_the_filtered_frame(all_joined, rate_key, assigned_only, year):
    """Whatever the controls, the KPI row, the caption, the practice table and
    the provider table are the rollup of the same filtered member-months."""
    population = benchmark.Population(assigned_only, year)
    frame = benchmark.filter_population(all_joined, population)
    expected = benchmark.totals(frame, rate_key)
    kpis, section = layout._render_program_benchmark(rate_key, assigned_only, year)
    assert len(_find(kpis, dbc.Card)) == 5
    values = _card_values(kpis)
    assert values["Actual PMPM"] == layout._pmpm(expected["actual_pmpm"])
    assert (
        f"{population.describe()}, {int(expected['member_months']):,} member-months; "
        f"{int(expected['excluded_member_months']):,} excluded"
    ) in _caption(section)

    table = _find(section, dash_table.DataTable)[0]
    by_practice = benchmark.rollup(frame, PRACTICE, rate_key).set_index(PRACTICE)
    assert {r["Practice"] for r in table.data} == set(by_practice.index)
    for row in table.data:
        want = by_practice.loc[row["Practice"]]
        assert row["Excluded MM"] == want["excluded_member_months"]
        if math.isnan(want["variance_pmpm"]):
            assert row["Variance"] is None or math.isnan(row["Variance"])
        else:
            assert row["Variance"] == pytest.approx(want["variance_pmpm"], abs=0.01)

    practice = by_practice.index[0]
    out = layout._render_practice(practice, rate_key, assigned_only, year)
    providers = {r["Provider"]: r for r in _find(out, dash_table.DataTable)[0].data}
    want = benchmark.rollup(frame[frame[PRACTICE] == practice], PROVIDER, rate_key)
    assert set(providers) == set(want[PROVIDER])
    for _, w in want.iterrows():
        assert providers[w[PROVIDER]]["Excluded MM"] == w["excluded_member_months"]
