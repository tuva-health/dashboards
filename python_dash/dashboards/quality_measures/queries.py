"""SQL queries for the Quality Measures dashboard.

Two complementary data sources both live under the Tuva project:

  - Clinical measures (adh_*, cqm_*, nqf_*, supd) come from
    `quality_measures.summary_long` — one row per (person_id, measure_id)
    with denominator / numerator / exclusion flags.
  - AHRQ Prevention Quality Indicators come from `ahrq_quality_indicators.pqi_rate`
    (rolled-up rate) plus the `pqi_denom_long` and `pqi_num_long` row-level
    tables.

Both are union-friendly into a single "measure summary" frame so the
dashboard renders even when one source is empty (the clinical models can
be empty in synthetic data sets that don't include meds/labs).
"""

from __future__ import annotations

import logging

import pandas as pd

from tuva_dash import run_query
from tuva_dash.config import get_settings

log = logging.getLogger(__name__)

CLINICAL_SCHEMA = "quality_measures"
AHRQ_SCHEMA = "ahrq_quality_indicators"
SEMANTIC_SCHEMA = "semantic_layer"


def _safe(sql: str, columns: list[str]) -> pd.DataFrame:
    try:
        return run_query(sql, columns=columns)
    except Exception as exc:
        log.warning("quality_measures query failed (returning empty): %s", exc)
        return pd.DataFrame(columns=columns)


def load_clinical_long() -> pd.DataFrame:
    """One row per (person, measure) for clinical quality measures."""
    s = get_settings()
    sql = f"SELECT * FROM {s.qualified(CLINICAL_SCHEMA, 'summary_long')}"
    return _safe(
        sql,
        [
            "person_id", "denominator_flag", "numerator_flag", "exclusion_flag",
            "performance_flag", "evidence_date", "evidence_value",
            "exclusion_date", "exclusion_reason",
            "performance_period_begin", "performance_period_end",
            "measure_id", "measure_name", "measure_version",
        ],
    )


def load_clinical_wide() -> pd.DataFrame:
    """One row per person, one column per measure — useful as a fallback
    inventory when summary_long is empty."""
    s = get_settings()
    sql = f"SELECT * FROM {s.qualified(CLINICAL_SCHEMA, 'summary_wide')}"
    return _safe(sql, ["person_id"])


def load_ahrq_rate() -> pd.DataFrame:
    s = get_settings()
    sql = f"SELECT * FROM {s.qualified(AHRQ_SCHEMA, 'pqi_rate')}"
    return _safe(
        sql,
        [
            "data_source", "year_number", "pqi_number",
            "denom_count", "num_count", "rate_per_100_thousand",
        ],
    )


def load_ahrq_denom_long() -> pd.DataFrame:
    s = get_settings()
    sql = f"SELECT * FROM {s.qualified(AHRQ_SCHEMA, 'pqi_denom_long')}"
    return _safe(
        sql,
        ["year_number", "person_id", "data_source", "pqi_number"],
    )


def load_ahrq_num_long() -> pd.DataFrame:
    s = get_settings()
    sql = f"SELECT * FROM {s.qualified(AHRQ_SCHEMA, 'pqi_num_long')}"
    return _safe(
        sql,
        ["data_source", "person_id", "year_number", "encounter_id", "pqi_number"],
    )


def load_dim_member() -> pd.DataFrame:
    s = get_settings()
    sql = f"SELECT person_id, age, sex, race FROM {s.qualified(SEMANTIC_SCHEMA, 'dim_member')}"
    return _safe(sql, ["person_id", "age", "sex", "race"])


def load_dim_member_months() -> pd.DataFrame:
    """Provider attribution. We grab one row per person (most-recent month)."""
    s = get_settings()
    sql = f"""
        SELECT
            person_id,
            year_month,
            payer,
            payer_attributed_provider,
            payer_attributed_provider_practice,
            payer_attributed_provider_organization
        FROM {s.qualified(SEMANTIC_SCHEMA, 'dim_member_months')}
    """
    return _safe(
        sql,
        ["person_id", "year_month", "payer",
         "payer_attributed_provider",
         "payer_attributed_provider_practice",
         "payer_attributed_provider_organization"],
    )
