"""Member chronic conditions on Tuva 1.0.

Semantic layer 1.0 retired `dim_condition` and `fact_member_condition_bridge`
(person x Tuva-defined chronic condition). Tuva 1.0 ships the CMS Chronic
Conditions mart (`tuva-health/cms_chronic_conditions`) as a standalone
package, and its `cms_chronic_conditions_long` holds one row per person,
condition and evidence event. Deduplicated to person x condition it is the
same shape as the retired bridge: every condition with claims evidence, under
the CMS Chronic Conditions Warehouse definitions rather than Tuva's own.

The mart builds in the `chronic_conditions` schema, beside (not inside)
`semantic_layer`, and only where the root project installs the package.
Without it the query fails, the pages' safe loaders return an empty frame,
and the condition views show their "no data" state.
"""

from __future__ import annotations

from tuva_dash.config import Settings

SCHEMA = "chronic_conditions"
TABLE = "cms_chronic_conditions_long"
SOURCE_TABLE = f"{SCHEMA}.{TABLE}"
COLUMNS = ["person_id", "condition"]

# Short label for page headings and filter captions.
LABEL = "CMS chronic conditions"


def member_conditions_sql(s: Settings) -> str:
    """One row per member and CMS chronic condition, as `(person_id, condition)`."""
    return f"""
        SELECT DISTINCT person_id, condition
        FROM {s.qualified(SCHEMA, TABLE)}
        WHERE condition IS NOT NULL
    """
