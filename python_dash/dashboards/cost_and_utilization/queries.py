"""SQL queries for the Cost and Utilization dashboard.

The Power BI version is built on the cloud-hosted Tuva semantic model. We
read the same `semantic_layer.*` fact and dimension tables locally (they
exist in any Tuva install that has run the unified semantic_layer dbt
package — including a fresh local DuckDB build).

PBI measure → SQL/pandas equivalent
  PMPM                = sum(paid_amount) / sum(member_months)
  Contributive PMPM   = sum(paid_amount for slice) / sum(total member_months)
  Cost Per Util       = sum(paid_amount) / sum(encounters)
  PKPY                = sum(encounters) * 12000 / sum(member_months)
  Paid Amount         = sum(paid_amount)
  Average LOS         = mean(length_of_stay) on inpatient admissions
  Readmission Rate    = sum(readmit_30_flag) / count(index admissions)
  Avoidable Percent   = sum(avoidable) / count(ed_visits)
  Members             = count(distinct person_id)
  % Female            = count(sex='female') / count(*) on dim_member
"""

from __future__ import annotations

import logging

import pandas as pd

from tuva_dash import run_query
from tuva_dash.config import get_settings

log = logging.getLogger(__name__)

SCHEMA = "semantic_layer"


def _safe_query(sql: str, columns: list[str]) -> pd.DataFrame:
    try:
        return run_query(sql, columns=columns)
    except Exception as exc:
        log.warning("cost_and_utilization query failed (returning empty): %s", exc)
        return pd.DataFrame(columns=columns)


def load_member_months() -> pd.DataFrame:
    s = get_settings()
    columns = ["person_id", "year_month", "member_months", "total_paid"]
    sql = f"SELECT {', '.join(columns)} FROM {s.qualified(SCHEMA, 'fact_member_months')}"
    return _safe_query(sql, columns)


def load_encounters() -> pd.DataFrame:
    """Encounters joined to encounter group + type names."""
    s = get_settings()
    sql = f"""
        SELECT
            e.encounter_id,
            e.person_id,
            e.year_month,
            e.encounter_start_date,
            e.facility_name,
            e.paid_amount,
            e.allowed_amount,
            e.claim_count,
            e.data_source,
            eg.encounter_group,
            et.encounter_type
        FROM {s.qualified(SCHEMA, 'fact_encounters')} e
        LEFT JOIN {s.qualified(SCHEMA, 'dim_encounter_group')} eg
            ON eg.encounter_group_sk = e.encounter_group_sk
        LEFT JOIN {s.qualified(SCHEMA, 'dim_encounter_type')} et
            ON et.encounter_type_sk = e.encounter_type_sk
    """
    return _safe_query(
        sql,
        [
            "encounter_id", "person_id", "year_month", "encounter_start_date",
            "facility_name", "paid_amount", "allowed_amount", "claim_count",
            "data_source", "encounter_group", "encounter_type",
        ],
    )


def load_claims() -> pd.DataFrame:
    """Claims joined to encounter group + type so we can filter per page."""
    s = get_settings()
    sql = f"""
        SELECT
            c.claim_id,
            c.person_id,
            c.year_month,
            c.claim_start_date,
            c.specialty,
            c.ccsr_category_description,
            c.drg_description,
            c.primary_diagnosis_description,
            c.facility_name,
            c.paid_amount,
            eg.encounter_group,
            et.encounter_type
        FROM {s.qualified(SCHEMA, 'fact_claims')} c
        LEFT JOIN {s.qualified(SCHEMA, 'dim_encounter_group')} eg
            ON eg.encounter_group_sk = c.encounter_group_sk
        LEFT JOIN {s.qualified(SCHEMA, 'dim_encounter_type')} et
            ON et.encounter_type_sk = c.encounter_type_sk
    """
    return _safe_query(
        sql,
        [
            "claim_id", "person_id", "year_month", "claim_start_date", "specialty",
            "ccsr_category_description", "drg_description",
            "primary_diagnosis_description", "facility_name", "paid_amount",
            "encounter_group", "encounter_type",
        ],
    )


def load_admissions() -> pd.DataFrame:
    s = get_settings()
    columns = [
        "encounter_id", "person_id", "admit_date", "discharge_date",
        "length_of_stay", "index_admission_flag", "readmit_30_flag",
        "drg_description", "attending_provider_name",
    ]
    sql = f"SELECT {', '.join(columns)} FROM {s.qualified(SCHEMA, 'fact_admissions')}"
    return _safe_query(sql, columns)


def load_ed_visits() -> pd.DataFrame:
    s = get_settings()
    columns = [
        "encounter_id", "person_id",
        "ed_classification_description", "avoidable", "paid_amount",
    ]
    sql = f"SELECT {', '.join(columns)} FROM {s.qualified(SCHEMA, 'fact_ed_visits')}"
    return _safe_query(sql, columns)


def load_dim_member() -> pd.DataFrame:
    s = get_settings()
    sql = f"SELECT person_id, sex, race FROM {s.qualified(SCHEMA, 'dim_member')}"
    return _safe_query(sql, ["person_id", "sex", "race"])


def load_risk_scores() -> pd.DataFrame:
    """Optional — fact_risk_scores may not exist in every install."""
    s = get_settings()
    sql = f"SELECT * FROM {s.qualified(SCHEMA, 'fact_risk_scores')}"
    return _safe_query(sql, ["person_id", "blended_risk_score", "normalized_risk_score"])
