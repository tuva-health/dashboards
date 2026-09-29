"""Pytest fixtures: the synthetic DuckDBs from `fixture_data`, and the
environment that points the dashboard at each of them."""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.fixture_data import build_duckdb
from tuva_dash.config import get_settings
from tuva_dash.lazy import LazyFrame


@pytest.fixture(scope="session")
def full_db_path(tmp_path_factory) -> Path:
    return build_duckdb(tmp_path_factory.mktemp("duck") / "full.duckdb", with_benchmark=True)


@pytest.fixture(scope="session")
def no_benchmark_db_path(tmp_path_factory) -> Path:
    return build_duckdb(
        tmp_path_factory.mktemp("duck") / "no_benchmark.duckdb", with_benchmark=False
    )


@pytest.fixture(scope="session")
def legacy_db_path(tmp_path_factory) -> Path:
    return build_duckdb(
        tmp_path_factory.mktemp("duck") / "legacy.duckdb",
        with_benchmark=True, with_surrogate_key=False,
    )


def _reset_caches() -> None:
    """Settings and the layout's lazy frames are process-level caches."""
    get_settings.cache_clear()
    from dashboards.mssp_aco_dashboard import layout

    for value in vars(layout).values():
        if isinstance(value, LazyFrame):
            value._load.cache_clear()


def _point_at(monkeypatch, db_path: Path | None) -> None:
    if db_path is None:
        # As .env.example ships: queries skipped, DuckDB the nominal target.
        monkeypatch.setenv("LOAD_DATA", "false")
        monkeypatch.setenv("DATA_WAREHOUSE_TYPE", "duckdb")
    else:
        monkeypatch.setenv("LOAD_DATA", "true")
        monkeypatch.setenv("DATA_WAREHOUSE_TYPE", "duckdb")
        monkeypatch.setenv("DUCKDB_DATABASE", str(db_path))
        monkeypatch.setenv("SCHEMA_PREPEND_NAME", "NULL")
    _reset_caches()


@pytest.fixture
def full_db(monkeypatch, full_db_path):
    _point_at(monkeypatch, full_db_path)
    yield full_db_path
    _reset_caches()


@pytest.fixture
def no_benchmark_db(monkeypatch, no_benchmark_db_path):
    _point_at(monkeypatch, no_benchmark_db_path)
    yield no_benchmark_db_path
    _reset_caches()


@pytest.fixture
def legacy_db(monkeypatch, legacy_db_path):
    _point_at(monkeypatch, legacy_db_path)
    yield legacy_db_path
    _reset_caches()


@pytest.fixture
def no_load_data(monkeypatch):
    _point_at(monkeypatch, None)
    yield
    _reset_caches()
