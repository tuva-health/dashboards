"""SQL queries for the Population Health dashboard."""

from __future__ import annotations

import logging

import pandas as pd

from tuva_dash import conditions, run_query
from tuva_dash.config import get_settings

log = logging.getLogger(__name__)

SCHEMA = "semantic_layer"
AHRQ_SCHEMA = "ahrq_quality_indicators"


def _safe(sql: str, columns: list[str]) -> pd.DataFrame:
    try:
        return run_query(sql, columns=columns)
    except Exception as exc:
        log.warning("population_health query failed (returning empty): %s", exc)
        return pd.DataFrame(columns=columns)


def load_member_months() -> pd.DataFrame:
    s = get_settings()
    sql = f"""
        SELECT person_id, year_month, year_nbr, member_months,
               total_paid, medical_paid, pharmacy_paid, data_source
        FROM {s.qualified(SCHEMA, 'fact_member_months')}
    """
    return _safe(sql, ["person_id", "year_month", "year_nbr", "member_months",
                       "total_paid", "medical_paid", "pharmacy_paid", "data_source"])


def load_members() -> pd.DataFrame:
    s = get_settings()
    sql = f"SELECT * FROM {s.qualified(SCHEMA, 'dim_member')}"
    return _safe(sql, ["person_id", "age", "age_group", "sex", "race",
                       "ethnicity", "data_source"])


def load_member_conditions() -> pd.DataFrame:
    """CMS chronic conditions per member; see `tuva_dash.conditions`."""
    return _safe(conditions.member_conditions_sql(get_settings()), conditions.COLUMNS)


def load_encounters() -> pd.DataFrame:
    s = get_settings()
    sql = f"""
        SELECT
            e.encounter_id, e.person_id, e.year_month,
            e.encounter_start_date, e.encounter_end_date, e.facility_name,
            e.paid_amount, e.allowed_amount, e.claim_count,
            e.primary_diagnosis_description,
            eg.encounter_group, et.encounter_type
        FROM {s.qualified(SCHEMA, 'fact_encounters')} e
        LEFT JOIN {s.qualified(SCHEMA, 'dim_encounter_group')} eg
            ON eg.encounter_group_sk = e.encounter_group_sk
        LEFT JOIN {s.qualified(SCHEMA, 'dim_encounter_type')} et
            ON et.encounter_type_sk = e.encounter_type_sk
    """
    return _safe(sql, ["encounter_id", "person_id", "year_month",
                       "encounter_start_date", "encounter_end_date",
                       "facility_name", "paid_amount", "allowed_amount",
                       "claim_count", "primary_diagnosis_description",
                       "encounter_group", "encounter_type"])


def load_admissions() -> pd.DataFrame:
    s = get_settings()
    columns = ["encounter_id", "person_id", "admit_date",
               "discharge_date", "length_of_stay",
               "index_admission_flag", "had_readmission_flag",
               "readmit_30_flag", "drg_description",
               "attending_provider_name"]
    sql = f"SELECT {', '.join(columns)} FROM {s.qualified(SCHEMA, 'fact_admissions')}"
    return _safe(sql, columns)


def load_ed_visits() -> pd.DataFrame:
    s = get_settings()
    columns = ["encounter_id", "person_id", "ed_classification_description",
               "avoidable", "avoidable_description", "paid_amount",
               "claim_count"]
    sql = f"SELECT {', '.join(columns)} FROM {s.qualified(SCHEMA, 'fact_ed_visits')}"
    return _safe(sql, columns)


def load_pharmacy() -> pd.DataFrame:
    s = get_settings()
    sql = f"SELECT * FROM {s.qualified(SCHEMA, 'fact_pharmacy_claims')}"
    return _safe(sql, [
        "claim_id", "person_id", "ndc_description", "paid_amount",
        "prescribing_provider_name", "prescribing_specialty",
        "dispensing_provider_name", "dispensing_date",
        "days_supply", "brand_name", "brand_vs_generic",
        "atc_1_name", "atc_2_name", "atc_3_name", "atc_4_name",
    ])


def load_risk_scores() -> pd.DataFrame:
    s = get_settings()
    sql = f"SELECT * FROM {s.qualified(SCHEMA, 'fact_risk_scores')}"
    return _safe(sql, ["person_id", "blended_risk_score", "normalized_risk_score",
                       "v24_risk_score", "v28_risk_score", "payment_year",
                       "member_months"])


def load_risk_factors() -> pd.DataFrame:
    s = get_settings()
    sql = f"SELECT * FROM {s.qualified(SCHEMA, 'fact_risk_factors')}"
    return _safe(sql, ["person_id", "factor_type", "risk_factor_description",
                       "coefficient", "model_version", "payment_year"])


def load_pqi_denom() -> pd.DataFrame:
    s = get_settings()
    sql = f"SELECT * FROM {s.qualified(AHRQ_SCHEMA, 'pqi_denom_long')}"
    return _safe(sql, ["year_number", "person_id", "data_source", "pqi_number"])


def load_pqi_rate() -> pd.DataFrame:
    s = get_settings()
    sql = f"SELECT * FROM {s.qualified(AHRQ_SCHEMA, 'pqi_rate')}"
    return _safe(sql, ["data_source", "year_number", "pqi_number",
                       "denom_count", "num_count", "rate_per_100_thousand"])
