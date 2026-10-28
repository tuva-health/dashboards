"""Tuva 1.0 compatibility for every dashboard's queries.

Tuva 1.0 retired, or moved, these names the dashboards used to read:

- semantic layer: `dim_condition`, `fact_member_condition_bridge`,
  `fact_expected_values`, and the `fact_pharmacy_claims` generic-opportunity
  fields; `member_month_sk` is deprecated (person and month, not unique on 1.0
  member months; join on `member_month_id`);
- AHRQ Quality Indicators: the `ahrq_measures` schema is now
  `ahrq_quality_indicators`.

No warehouse needed:

- `test_no_query_reads_a_retired_name` runs every loader of every dashboard
  with `run_query` stubbed and fails if any SQL names a retired relation,
  column or schema, or selects `*` from a 1.0 relation that still carries a
  deprecated column (the `*` would pull it in unseen).
- `test_page_lists_no_retired_name` builds each page with LOAD_DATA=false and
  scans it, including the "Backed by Tuva tables" list.
- `test_model_browser_maps_no_retired_relation` scans the relationship map.

A stubbed query returns no rows, so a loader that issues a second query only
from the first one's rows (the model browser's per-table counts and samples)
is checked on its first query only. Those table names come from
`information_schema`, not from code.

Opt-in, against a real 1.0 build: `test_page_queries_run_against_a_v1_build`
runs each ported page's loaders against the DuckDB `TUVA_V1_DUCKDB` points at
(for example the cms_mssp_connector `scripts/dbt-local build` output), fails
on any query error or on a retired column in what comes back, and builds the
page.
"""

from __future__ import annotations

import importlib
import inspect
import logging
import os
import re
from pathlib import Path

import pandas as pd
import pytest

from tuva_dash import conditions
from tuva_dash.config import get_settings
from tuva_dash.lazy import LazyFrame

ALL_PAGES = [
    "cost_and_utilization", "cost_drivers", "dqi_analytics", "mssp_aco_dashboard",
    "population_health", "quality_measures", "risk_adjust_benchmark", "semantic_layer",
]
# The pages TUVA-128 ported: each read a retired relation, column or schema.
PORTED_PAGES = [
    "cost_and_utilization", "cost_drivers", "mssp_aco_dashboard",
    "population_health", "quality_measures", "semantic_layer",
]
RETIRED = re.compile(
    r"\b("
    r"dim_condition|fact_member_condition_bridge|fact_expected_values|member_month_sk"
    r"|ahrq_measures"
    r"|generic_available\w*|generic_cost_at_units|brand_paid_amount"
    r")\b",
    re.IGNORECASE,
)
# Semantic layer 1.0 relations that still carry the deprecated member_month_sk.
CARRY_DEPRECATED = (
    "fact_member_months", "dim_member_months", "fact_claims",
    "fact_encounters", "fact_admissions", "fact_ed_visits",
)
SELECT_STAR_FROM_DEPRECATED = re.compile(
    r"SELECT\s+\*\s+FROM\s+\S*\b(" + "|".join(CARRY_DEPRECATED) + r")\b",
    re.IGNORECASE,
)


def _loaders(page: str):
    module = importlib.import_module(f"dashboards.{page}.queries")
    for name, fn in inspect.getmembers(module, inspect.isfunction):
        if name.startswith("load_") and fn.__module__ == module.__name__:
            yield module, name, fn


def _call(fn):
    # The model browser's sampler is the only loader that takes arguments.
    if "table_name" in inspect.signature(fn).parameters:
        return fn("fact_member_months")
    return fn()


def _clear_lazy_frames(layout) -> None:
    for value in vars(layout).values():
        if isinstance(value, LazyFrame):
            value._load.cache_clear()


@pytest.mark.parametrize("page", ALL_PAGES)
def test_no_query_reads_a_retired_name(page, monkeypatch, no_load_data):
    issued: list[str] = []

    def capture(sql, *args, columns=None, **kwargs):
        issued.append(sql)
        return pd.DataFrame(columns=columns or [])

    loaders = list(_loaders(page))
    assert loaders
    for module, _name, fn in loaders:
        monkeypatch.setattr(module, "run_query", capture)
        _call(fn)
    assert issued
    assert not [sql for sql in issued if RETIRED.search(sql)]
    assert not [sql for sql in issued if SELECT_STAR_FROM_DEPRECATED.search(sql)]


@pytest.mark.parametrize("page", ALL_PAGES)
def test_page_lists_no_retired_name(page, no_load_data):
    layout = importlib.import_module(f"dashboards.{page}.layout")
    _clear_lazy_frames(layout)
    try:
        rendered = str(layout.build_layout())
    finally:
        _clear_lazy_frames(layout)
    assert not RETIRED.findall(rendered)


def test_model_browser_maps_no_retired_relation():
    from dashboards.semantic_layer import layout

    named = [part for rel in layout._RELATIONSHIPS for part in rel]
    assert not [n for n in named if RETIRED.search(n)]


def test_conditions_are_cms_chronic_conditions_one_row_per_member_and_condition(full_db):
    from dashboards.cost_drivers import queries
    from tests.fixture_data import CONDITIONS

    got = queries.load_member_conditions()
    assert list(got.columns) == conditions.COLUMNS
    expected = {(p, c) for p, cs in CONDITIONS.items() for c in cs}
    # P1's diabetes has two evidence events in the long table; it comes back once.
    assert len(got) == len(expected)
    assert set(map(tuple, got[["person_id", "condition"]].values)) == expected


V1_DUCKDB = os.environ.get("TUVA_V1_DUCKDB")


@pytest.fixture
def v1_db(monkeypatch):
    if not V1_DUCKDB or not Path(V1_DUCKDB).exists():
        pytest.skip("set TUVA_V1_DUCKDB to a semantic layer 1.0 DuckDB build")
    monkeypatch.setenv("LOAD_DATA", "true")
    monkeypatch.setenv("DATA_WAREHOUSE_TYPE", "duckdb")
    monkeypatch.setenv("DUCKDB_DATABASE", V1_DUCKDB)
    monkeypatch.setenv("SCHEMA_PREPEND_NAME", os.environ.get("TUVA_V1_SCHEMA_PREPEND", "NULL"))
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.mark.parametrize("page", PORTED_PAGES)
def test_page_queries_run_against_a_v1_build(page, v1_db, caplog):
    caplog.set_level(logging.WARNING)
    for _module, name, fn in _loaders(page):
        frame = _call(fn)
        # The model browser shows whatever a table holds, deprecated columns
        # included; every other loader must not bring one back.
        if page != "semantic_layer":
            assert not [c for c in frame.columns if RETIRED.fullmatch(str(c))], name
    failures = [r.getMessage() for r in caplog.records if "query failed" in r.getMessage()]
    assert not failures, failures
    layout = importlib.import_module(f"dashboards.{page}.layout")
    _clear_lazy_frames(layout)
    try:
        assert layout.build_layout() is not None
    finally:
        _clear_lazy_frames(layout)
