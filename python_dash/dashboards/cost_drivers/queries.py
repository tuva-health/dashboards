"""SQL queries for the Cost Drivers dashboard.

Mirrors the PBI dashboard which lets a user filter to a member cohort by
condition and inspect cost/utilization at the encounter group + service
category grain. On Tuva 1.0 the conditions are the CMS chronic conditions
(see `tuva_dash.conditions`).
"""

from __future__ import annotations

import logging

import pandas as pd

from tuva_dash import conditions, run_query
from tuva_dash.config import get_settings

log = logging.getLogger(__name__)

SCHEMA = "semantic_layer"


def _safe(sql: str, columns: list[str]) -> pd.DataFrame:
    try:
        return run_query(sql, columns=columns)
    except Exception as exc:
        log.warning("cost_drivers query failed (returning empty): %s", exc)
        return pd.DataFrame(columns=columns)


def load_member_months() -> pd.DataFrame:
    s = get_settings()
    sql = f"""
        SELECT person_id, year_month, year_nbr, member_months,
               total_paid, medical_paid, pharmacy_paid
        FROM {s.qualified(SCHEMA, 'fact_member_months')}
    """
    return _safe(sql, ["person_id", "year_month", "year_nbr", "member_months",
                       "total_paid", "medical_paid", "pharmacy_paid"])


def load_encounters() -> pd.DataFrame:
    s = get_settings()
    sql = f"""
        SELECT
            e.encounter_id, e.person_id, e.year_month,
            e.encounter_start_date, e.encounter_end_date,
            e.facility_name, e.paid_amount, e.allowed_amount, e.claim_count,
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
                       "claim_count", "encounter_group", "encounter_type"])


def load_claims() -> pd.DataFrame:
    s = get_settings()
    sql = f"""
        SELECT
            c.claim_id, c.medical_claim_id, c.claim_line_number,
            c.person_id, c.year_month, c.claim_start_date, c.claim_end_date,
            c.claim_type, c.payer, c.specialty,
            c.ccsr_category_description, c.primary_diagnosis_description,
            c.facility_name, c.paid_amount, c.allowed_amount,
            c.admission_date, c.discharge_date,
            eg.encounter_group, et.encounter_type,
            sc.service_category_1, sc.service_category_2
        FROM {s.qualified(SCHEMA, 'fact_claims')} c
        LEFT JOIN {s.qualified(SCHEMA, 'dim_encounter_group')} eg
            ON eg.encounter_group_sk = c.encounter_group_sk
        LEFT JOIN {s.qualified(SCHEMA, 'dim_encounter_type')} et
            ON et.encounter_type_sk = c.encounter_type_sk
        LEFT JOIN {s.qualified(SCHEMA, 'dim_service_category')} sc
            ON sc.service_category_sk = c.service_category_sk
    """
    return _safe(sql, ["claim_id", "medical_claim_id", "claim_line_number",
                       "person_id", "year_month", "claim_start_date",
                       "claim_end_date", "claim_type", "payer", "specialty",
                       "ccsr_category_description", "primary_diagnosis_description",
                       "facility_name", "paid_amount", "allowed_amount",
                       "admission_date", "discharge_date",
                       "encounter_group", "encounter_type",
                       "service_category_1", "service_category_2"])


def load_member_conditions() -> pd.DataFrame:
    """CMS chronic conditions per member; see `tuva_dash.conditions`."""
    return _safe(conditions.member_conditions_sql(get_settings()), conditions.COLUMNS)


def load_admissions() -> pd.DataFrame:
    s = get_settings()
    sql = f"""
        SELECT encounter_id, person_id, length_of_stay
        FROM {s.qualified(SCHEMA, 'fact_admissions')}
    """
    return _safe(sql, ["encounter_id", "person_id", "length_of_stay"])
