"""Layout + callbacks for the Cost Drivers dashboard.

PBI structure (3 pages):
  - Summary: KPIs, Year + CMS chronic conditions slicers, two pivots
    (Utilization Metrics by Encounter, PMPM by Service Category)
  - Encounter Grain: row-level encounter table
  - Claim Line Grain: row-level claim line table
"""

from __future__ import annotations

import dash_bootstrap_components as dbc
import pandas as pd
from dash import Input, Output, callback, dash_table, dcc, html

from tuva_dash.components import kpi_card, kpi_row, no_data_message, page_shell
from tuva_dash.conditions import LABEL as CONDITIONS_LABEL
from tuva_dash.conditions import SOURCE_TABLE as CONDITIONS_TABLE
from tuva_dash.lazy import LazyFrame

from . import queries

# Lazy dataset cache. The Dash callback rebuilds visuals from these in-memory
# frames as the user changes filters, but Snowflake is not queried until this
# dashboard is visited.
_MM = LazyFrame(queries.load_member_months)
_ENCOUNTERS = LazyFrame(queries.load_encounters)
_CLAIMS = LazyFrame(queries.load_claims)
_MEMBER_CONDITIONS = LazyFrame(queries.load_member_conditions)
_ADMISSIONS = LazyFrame(queries.load_admissions)


def _money(v: float) -> str:
    return "—" if pd.isna(v) else f"${v:,.0f}"


def _pmpm(v: float) -> str:
    return "—" if pd.isna(v) else f"${v:,.2f}"


def _filter_persons(conditions: list[str]) -> set[str] | None:
    """Members who have *all* of the selected conditions. None = no filter."""
    if not conditions or _MEMBER_CONDITIONS.empty:
        return None
    df = _MEMBER_CONDITIONS[_MEMBER_CONDITIONS["condition"].isin(conditions)]
    counts = df.groupby("person_id")["condition"].nunique()
    return set(counts[counts == len(conditions)].index)


def _apply(df: pd.DataFrame, persons: set[str] | None, years: list[int] | None) -> pd.DataFrame:
    out = df
    if persons is not None and "person_id" in out.columns:
        out = out[out["person_id"].isin(persons)]
    if years and "year_month" in out.columns:
        ym = pd.to_numeric(out["year_month"], errors="coerce")
        # year_month is YYYYMM; first 4 digits = year
        out = out[(ym // 100).isin([int(y) for y in years])]
    return out


def _kpis(mm: pd.DataFrame, claims: pd.DataFrame) -> dbc.Row:
    members = mm["person_id"].nunique() if not mm.empty else 0
    member_months = float(mm["member_months"].sum()) if not mm.empty else 0.0
    avg_monthly_enrollment = (
        member_months / mm["year_month"].nunique() if not mm.empty and mm["year_month"].nunique() else 0
    )
    paid = float(claims["paid_amount"].sum()) if not claims.empty else 0.0
    pmpm = (paid / member_months) if member_months else float("nan")
    return kpi_row([
        kpi_card("Members", f"{members:,}"),
        kpi_card("Avg Monthly Enrollment", f"{avg_monthly_enrollment:,.1f}"),
        kpi_card("Total Paid", _money(paid)),
        kpi_card("PMPM", _pmpm(pmpm)),
    ])


def _utilization_by_encounter(claims: pd.DataFrame, encounters: pd.DataFrame, mm: pd.DataFrame):
    """Pivot: rows = encounter group + type, cols = Contributive PMPM, PKPY, Avg LOS."""
    if claims.empty or mm.empty:
        return no_data_message()
    total_mm = float(mm["member_months"].sum()) or 1.0

    paid_by = (
        claims.dropna(subset=["encounter_group"])
        .groupby(["encounter_group", "encounter_type"])["paid_amount"].sum()
        .reset_index()
        .rename(columns={"paid_amount": "paid"})
    )
    enc_by = (
        encounters.dropna(subset=["encounter_group"])
        .groupby(["encounter_group", "encounter_type"])["encounter_id"].nunique()
        .reset_index()
        .rename(columns={"encounter_id": "encounters"})
    )
    los_by = pd.DataFrame(columns=["encounter_id", "length_of_stay"])
    if not _ADMISSIONS.empty and not encounters.empty:
        adm = _ADMISSIONS.merge(
            encounters[["encounter_id", "encounter_group", "encounter_type"]],
            on="encounter_id", how="inner",
        )
        los_by = (
            adm.groupby(["encounter_group", "encounter_type"])["length_of_stay"].mean()
            .reset_index().rename(columns={"length_of_stay": "avg_los"})
        )

    out = paid_by.merge(enc_by, on=["encounter_group", "encounter_type"], how="outer").fillna(0)
    if not los_by.empty:
        out = out.merge(los_by, on=["encounter_group", "encounter_type"], how="left")
    else:
        out["avg_los"] = float("nan")

    out["pmpm"] = out["paid"] / total_mm
    out["pkpy"] = out["encounters"] * 12000 / total_mm
    out = out.sort_values(["encounter_group", "encounter_type"]).rename(
        columns={
            "encounter_group": "Encounter Group",
            "encounter_type": "Encounter Type",
            "paid": "Paid",
            "encounters": "Encounters",
            "pmpm": "PMPM",
            "pkpy": "PKPY",
            "avg_los": "Avg LOS",
        }
    )
    out = out[["Encounter Group", "Encounter Type", "PMPM", "PKPY", "Avg LOS",
               "Paid", "Encounters"]]
    out["PMPM"] = out["PMPM"].round(2)
    out["PKPY"] = out["PKPY"].round(1)
    out["Avg LOS"] = out["Avg LOS"].round(2)
    out["Paid"] = out["Paid"].round(0)

    return dash_table.DataTable(
        data=out.to_dict("records"),
        columns=[{"name": c, "id": c} for c in out.columns],
        page_size=20,
        sort_action="native",
        style_cell={"fontSize": 13, "padding": "5px"},
        style_header={"fontWeight": "bold"},
        style_data_conditional=[
            {"if": {"row_index": "odd"}, "backgroundColor": "#f8f9fa"},
        ],
    )


def _pmpm_by_service_category(claims: pd.DataFrame, mm: pd.DataFrame):
    if claims.empty or mm.empty:
        return no_data_message()
    total_mm = float(mm["member_months"].sum()) or 1.0
    g = (
        claims.dropna(subset=["service_category_1"])
        .groupby(["service_category_1", "service_category_2"])["paid_amount"].sum()
        .reset_index()
    )
    g["PMPM"] = (g["paid_amount"] / total_mm).round(2)
    g = g.rename(columns={
        "service_category_1": "Service Category 1",
        "service_category_2": "Service Category 2",
        "paid_amount": "Paid",
    }).sort_values(["Service Category 1", "PMPM"], ascending=[True, False])
    g["Paid"] = g["Paid"].round(0)
    return dash_table.DataTable(
        data=g.to_dict("records"),
        columns=[{"name": c, "id": c} for c in g.columns],
        page_size=25,
        sort_action="native",
        style_cell={"fontSize": 13, "padding": "5px"},
        style_header={"fontWeight": "bold"},
        style_data_conditional=[
            {"if": {"row_index": "odd"}, "backgroundColor": "#f8f9fa"},
        ],
    )


# -- callbacks ---------------------------------------------------------------

@callback(
    Output("cd-summary-content", "children"),
    Input("cd-condition-filter", "value"),
    Input("cd-year-filter", "value"),
)
def _render_summary(conditions, years):
    persons = _filter_persons(conditions or [])
    mm = _apply(_MM, persons, years)
    claims = _apply(_CLAIMS, persons, years)
    encounters = _apply(_ENCOUNTERS, persons, years)

    return [
        _kpis(mm, claims),
        html.H5("Utilization metrics by encounter", className="mt-4"),
        _utilization_by_encounter(claims, encounters, mm),
        html.H5("PMPM by service category", className="mt-4"),
        _pmpm_by_service_category(claims, mm),
    ]


@callback(
    Output("cd-encounters-content", "children"),
    Input("cd-condition-filter", "value"),
    Input("cd-year-filter", "value"),
)
def _render_encounters(conditions, years):
    persons = _filter_persons(conditions or [])
    df = _apply(_ENCOUNTERS, persons, years)
    if df.empty:
        return no_data_message()
    if not _ADMISSIONS.empty:
        df = df.merge(_ADMISSIONS[["encounter_id", "length_of_stay"]],
                      on="encounter_id", how="left")
    cols = [c for c in [
        "encounter_id", "person_id", "encounter_group", "encounter_type",
        "encounter_start_date", "encounter_end_date", "facility_name",
        "length_of_stay", "claim_count", "paid_amount", "allowed_amount",
    ] if c in df.columns]
    return dash_table.DataTable(
        data=df[cols].to_dict("records"),
        columns=[{"name": c, "id": c} for c in cols],
        page_size=25,
        sort_action="native",
        filter_action="native",
        style_cell={"fontSize": 12, "padding": "4px"},
        style_header={"fontWeight": "bold"},
    )


@callback(
    Output("cd-claims-content", "children"),
    Input("cd-condition-filter", "value"),
    Input("cd-year-filter", "value"),
)
def _render_claims(conditions, years):
    persons = _filter_persons(conditions or [])
    df = _apply(_CLAIMS, persons, years)
    if df.empty:
        return no_data_message()
    cols = [c for c in [
        "claim_id", "claim_line_number", "person_id", "claim_type",
        "service_category_1", "service_category_2", "encounter_group",
        "encounter_type", "claim_start_date", "claim_end_date",
        "specialty", "ccsr_category_description", "primary_diagnosis_description",
        "facility_name", "paid_amount", "allowed_amount",
    ] if c in df.columns]
    return dash_table.DataTable(
        data=df[cols].to_dict("records"),
        columns=[{"name": c, "id": c} for c in cols],
        page_size=25,
        sort_action="native",
        filter_action="native",
        style_cell={"fontSize": 11, "padding": "4px"},
        style_header={"fontWeight": "bold"},
    )


# -- entry point -------------------------------------------------------------

def build_layout() -> html.Div:
    condition_options = (
        sorted(_MEMBER_CONDITIONS["condition"].dropna().unique())
        if not _MEMBER_CONDITIONS.empty else []
    )
    year_options = []
    if not _MM.empty and "year_nbr" in _MM.columns:
        year_options = sorted(
            int(y) for y in _MM["year_nbr"].dropna().astype(int).unique()
        )

    filters = dbc.Row(
        [
            dbc.Col(
                [
                    html.Label(f"{CONDITIONS_LABEL} (members must have ALL):",
                               className="small text-muted"),
                    dcc.Dropdown(
                        id="cd-condition-filter",
                        options=[{"label": c, "value": c} for c in condition_options],
                        multi=True,
                        placeholder="No filter — all members",
                    ),
                ],
                md=8,
            ),
            dbc.Col(
                [
                    html.Label("Year:", className="small text-muted"),
                    dcc.Dropdown(
                        id="cd-year-filter",
                        options=[{"label": str(y), "value": y} for y in year_options],
                        multi=True,
                        placeholder="All years",
                    ),
                ],
                md=4,
            ),
        ],
        className="mb-3",
    )

    body = html.Div(
        [
            filters,
            dbc.Tabs(
                [
                    dbc.Tab(
                        html.Div(id="cd-summary-content", className="pt-3"),
                        label="Summary",
                    ),
                    dbc.Tab(
                        html.Div(id="cd-encounters-content", className="pt-3"),
                        label="Encounter Grain",
                    ),
                    dbc.Tab(
                        html.Div(id="cd-claims-content", className="pt-3"),
                        label="Claim Line Grain",
                    ),
                ]
            ),
        ]
    )

    return page_shell(
        title="Cost Drivers",
        subtitle=(
            "Cost and utilization filtered by a CMS chronic-condition cohort. "
            "Pick conditions to see PMPM and PKPY for members who carry all of them."
        ),
        body=body,
        tuva_tables=[
            "semantic_layer.fact_member_months",
            "semantic_layer.fact_claims",
            "semantic_layer.fact_encounters",
            "semantic_layer.fact_admissions",
            CONDITIONS_TABLE,
            "semantic_layer.dim_service_category",
            "semantic_layer.dim_encounter_group",
            "semantic_layer.dim_encounter_type",
        ],
    )
