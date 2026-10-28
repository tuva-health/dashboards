"""Layout for the Population Health dashboard.

Mirrors the 6 PBI pages: PMPM, Population Overview, Inpatient,
Preventable Events, Pharmacy, Risk.
"""

from __future__ import annotations

import dash_bootstrap_components as dbc
import pandas as pd
import plotly.express as px
from dash import dash_table, dcc, html

from tuva_dash.components import kpi_card, kpi_row, no_data_message, page_shell
from tuva_dash.conditions import LABEL as CONDITIONS_LABEL
from tuva_dash.conditions import SOURCE_TABLE as CONDITIONS_TABLE
from tuva_dash.lazy import LazyFrame

from . import queries

# Lazy module-level dataset cache. Data is queried once, on first use, instead
# of at app startup.
_MM = LazyFrame(queries.load_member_months)
_MEMBERS = LazyFrame(queries.load_members)
_CONDITIONS = LazyFrame(queries.load_member_conditions)
_ENCOUNTERS = LazyFrame(queries.load_encounters)
_ADMISSIONS = LazyFrame(queries.load_admissions)
_ED_VISITS = LazyFrame(queries.load_ed_visits)
_PHARMACY = LazyFrame(queries.load_pharmacy)
_RISK_SCORES = LazyFrame(queries.load_risk_scores)
_RISK_FACTORS = LazyFrame(queries.load_risk_factors)
_PQI_DENOM = LazyFrame(queries.load_pqi_denom)
_PQI_RATE = LazyFrame(queries.load_pqi_rate)


# -- formatting helpers ------------------------------------------------------

def _money(v) -> str:
    return "—" if pd.isna(v) else f"${v:,.0f}"


def _pmpm(v) -> str:
    return "—" if pd.isna(v) else f"${v:,.2f}"


def _pct(v) -> str:
    return "—" if pd.isna(v) else f"{v * 100:.1f}%"


# -- PMPM tab ----------------------------------------------------------------

def _pmpm_tab() -> html.Div:
    if _MM.empty:
        return html.Div([no_data_message()], className="pt-3")

    total_mm = float(_MM["member_months"].sum()) or 1.0
    members = _MM["person_id"].nunique()
    avg_monthly = total_mm / max(_MM["year_month"].nunique(), 1)
    total_paid = float(_MM["total_paid"].sum())
    pmpm = total_paid / total_mm

    cards = kpi_row([
        kpi_card("Members", f"{members:,}"),
        kpi_card("Avg Monthly Enrollment", f"{avg_monthly:,.1f}"),
        kpi_card("Total Paid", _money(total_paid)),
        kpi_card("PMPM", _pmpm(pmpm)),
    ])

    # PMPM trend by data source
    mm_with_ds = _MM.copy()
    mm_with_ds["year_month"] = pd.to_datetime(mm_with_ds["year_month"], format="%Y%m", errors="coerce")
    by_ds = (
        mm_with_ds.groupby(["year_month", "data_source"])
        .agg(paid=("total_paid", "sum"), mm=("member_months", "sum")).reset_index()
    )
    by_ds["pmpm"] = by_ds["paid"] / by_ds["mm"].where(by_ds["mm"] != 0)
    fig_trend = px.line(by_ds.sort_values("year_month"), x="year_month", y="pmpm",
                        color="data_source", title="PMPM trend by data source", markers=True)
    fig_trend.update_layout(height=340, yaxis_tickprefix="$", yaxis_tickformat=",")

    # PMPM by service category (treemap from encounters)
    if not _ENCOUNTERS.empty:
        treemap_df = (
            _ENCOUNTERS.dropna(subset=["encounter_group"])
            .groupby("encounter_group")["paid_amount"].sum().reset_index()
        )
        treemap_df["pmpm"] = treemap_df["paid_amount"] / total_mm
        fig_tree = px.treemap(treemap_df, path=["encounter_group"], values="paid_amount",
                              title="Spend by encounter group")
        fig_tree.update_layout(height=340)
        treemap = dcc.Graph(figure=fig_tree)
    else:
        treemap = no_data_message()

    # PMPM ribbon (% share by group over months)
    if not _ENCOUNTERS.empty:
        share = _ENCOUNTERS.copy()
        share["year_month"] = pd.to_datetime(share["year_month"], format="%Y%m", errors="coerce")
        share = (
            share.dropna(subset=["encounter_group"])
            .groupby(["year_month", "encounter_group"])["paid_amount"].sum().reset_index()
        )
        fig_ribbon = px.area(
            share.sort_values("year_month"), x="year_month", y="paid_amount",
            color="encounter_group", groupnorm="percent",
            title="Monthly spend mix by encounter group",
        )
        fig_ribbon.update_layout(height=340, yaxis_title="share")
        ribbon = dcc.Graph(figure=fig_ribbon)
    else:
        ribbon = no_data_message()

    return html.Div([
        cards,
        dbc.Row([
            dbc.Col(dcc.Graph(figure=fig_trend), md=6),
            dbc.Col(treemap, md=6),
        ], className="mb-3"),
        dbc.Row([dbc.Col(ribbon, md=12)]),
    ], className="pt-3")


# -- Population Overview tab -------------------------------------------------

def _overview_tab() -> html.Div:
    if _MEMBERS.empty:
        return html.Div([no_data_message()], className="pt-3")

    members_n = len(_MEMBERS)
    avg_age = float(_MEMBERS["age"].mean()) if "age" in _MEMBERS else float("nan")
    pct_female = (_MEMBERS["sex"].str.lower() == "female").mean()
    cards = kpi_row([
        kpi_card("Members", f"{members_n:,}"),
        kpi_card("Average Age", f"{avg_age:.1f}" if avg_age == avg_age else "—"),
        kpi_card("% Female", _pct(pct_female)),
    ])

    # Members by age group, split by sex
    by_age = (
        _MEMBERS.dropna(subset=["age_group"])
        .groupby(["age_group", "sex"])["person_id"].count().reset_index()
        .rename(columns={"person_id": "members"})
    )
    fig_age = px.bar(by_age, x="age_group", y="members", color="sex", barmode="group",
                     title="Members by age group")
    fig_age.update_layout(height=340, xaxis_title="")

    # Sex pie
    sex_pie = (
        _MEMBERS.groupby("sex")["person_id"].count().reset_index()
        .rename(columns={"person_id": "members"})
    )
    fig_sex = px.pie(sex_pie, names="sex", values="members", title="Members by sex")
    fig_sex.update_layout(height=340)

    # CMS chronic conditions × age group pivot
    if not _CONDITIONS.empty:
        cc = _CONDITIONS.merge(_MEMBERS[["person_id", "age_group"]], on="person_id", how="left")
        pivot = (
            cc.dropna(subset=["condition"])
            .groupby(["condition", "age_group"])["person_id"].nunique()
            .reset_index().rename(columns={"person_id": "members"})
            .pivot(index="condition", columns="age_group", values="members")
            .fillna(0).astype(int).reset_index()
        )
        cc_table = dash_table.DataTable(
            data=pivot.to_dict("records"),
            columns=[{"name": c, "id": c} for c in pivot.columns],
            page_size=20, sort_action="native", filter_action="native",
            style_cell={"fontSize": 12, "padding": "4px"},
            style_header={"fontWeight": "bold"},
        )
    else:
        cc_table = no_data_message()

    # Top members by total paid
    top_members = (
        _MM.groupby("person_id")["total_paid"].sum().reset_index()
        .sort_values("total_paid", ascending=False).head(100)
    )
    top_members["total_paid"] = top_members["total_paid"].round(0)
    top_members = top_members.merge(_MEMBERS[["person_id", "age", "sex"]], on="person_id", how="left")

    return html.Div([
        cards,
        dbc.Row([
            dbc.Col(dcc.Graph(figure=fig_age), md=8),
            dbc.Col(dcc.Graph(figure=fig_sex), md=4),
        ], className="mb-3"),
        html.H5(f"{CONDITIONS_LABEL} by age group"),
        cc_table,
        html.H5("Top members by total paid", className="mt-3"),
        dash_table.DataTable(
            data=top_members.to_dict("records"),
            columns=[{"name": c, "id": c} for c in top_members.columns],
            page_size=15, sort_action="native",
            style_cell={"fontSize": 12, "padding": "4px"},
            style_header={"fontWeight": "bold"},
        ),
    ], className="pt-3")


# -- Inpatient tab -----------------------------------------------------------

def _inpatient_tab() -> html.Div:
    if _ADMISSIONS.empty:
        return html.Div([no_data_message()], className="pt-3")

    total_mm = float(_MM["member_months"].sum()) or 1.0
    inpatient_paid = (
        float(_ENCOUNTERS[_ENCOUNTERS["encounter_group"] == "inpatient"]["paid_amount"].sum())
        if not _ENCOUNTERS.empty else 0.0
    )
    n_admits = len(_ADMISSIONS)
    avg_los = float(_ADMISSIONS["length_of_stay"].mean())
    readmit_rate = float(_ADMISSIONS["readmit_30_flag"].fillna(0).mean())
    pkpy = n_admits * 12000 / total_mm
    cost_per_admit = inpatient_paid / n_admits if n_admits else float("nan")

    cards = kpi_row([
        kpi_card("Admissions", f"{n_admits:,}"),
        kpi_card("Average LOS", f"{avg_los:.1f}"),
        kpi_card("Readmission Rate", _pct(readmit_rate)),
        kpi_card("Inpatient PKPY", f"{pkpy:,.1f}"),
        kpi_card("Cost per Admit", _money(cost_per_admit)),
    ])

    # Admissions by month (combo: count + paid)
    df = _ADMISSIONS.copy()
    df["admit_date"] = pd.to_datetime(df["admit_date"], errors="coerce")
    df["year_month"] = df["admit_date"].dt.to_period("M").dt.to_timestamp()
    by_m = (
        df.groupby("year_month")
        .agg(admits=("encounter_id", "count")).reset_index()
    )
    fig_m = px.bar(by_m, x="year_month", y="admits", title="Admissions by month")
    fig_m.update_layout(height=320, xaxis_title="")

    # Admissions by age group
    adm_with_age = _ADMISSIONS.merge(_MEMBERS[["person_id", "age_group"]],
                                     on="person_id", how="left")
    by_age = (
        adm_with_age.dropna(subset=["age_group"])
        .groupby("age_group")["encounter_id"].count().reset_index()
        .rename(columns={"encounter_id": "admits"})
    )
    by_age["pkpy"] = by_age["admits"] * 12000 / total_mm
    fig_age = px.bar(by_age, x="age_group", y="pkpy", title="Inpatient PKPY by age group")
    fig_age.update_layout(height=320, xaxis_title="")

    # DRG breakdown
    drg = (
        _ADMISSIONS.dropna(subset=["drg_description"])
        .groupby("drg_description")
        .agg(admits=("encounter_id", "count"),
             avg_los=("length_of_stay", "mean"))
        .reset_index().sort_values("admits", ascending=False)
    )
    drg["avg_los"] = drg["avg_los"].round(2)
    drg = drg.rename(columns={"drg_description": "DRG", "admits": "Admits", "avg_los": "Avg LOS"})

    # Facility breakdown
    facility = pd.DataFrame()
    if not _ENCOUNTERS.empty:
        ip_enc = _ENCOUNTERS[_ENCOUNTERS["encounter_group"] == "inpatient"]
        if not ip_enc.empty:
            facility = (
                ip_enc.dropna(subset=["facility_name"])
                .groupby("facility_name")
                .agg(encounters=("encounter_id", "nunique"),
                     paid=("paid_amount", "sum"))
                .reset_index().sort_values("paid", ascending=False)
            )
            facility["paid"] = facility["paid"].round(0)
            facility = facility.rename(columns={
                "facility_name": "Facility", "encounters": "Encounters", "paid": "Paid",
            })

    return html.Div([
        cards,
        dbc.Row([
            dbc.Col(dcc.Graph(figure=fig_m), md=6),
            dbc.Col(dcc.Graph(figure=fig_age), md=6),
        ], className="mb-3"),
        html.H5("Admissions by DRG"),
        dash_table.DataTable(
            data=drg.to_dict("records"),
            columns=[{"name": c, "id": c} for c in drg.columns],
            page_size=15, sort_action="native",
            style_cell={"fontSize": 12, "padding": "4px"},
            style_header={"fontWeight": "bold"},
        ),
        html.H5("Inpatient facilities", className="mt-3"),
        (dash_table.DataTable(
            data=facility.to_dict("records"),
            columns=[{"name": c, "id": c} for c in facility.columns],
            page_size=10, sort_action="native",
            style_cell={"fontSize": 12, "padding": "4px"},
            style_header={"fontWeight": "bold"},
        ) if not facility.empty else no_data_message()),
    ], className="pt-3")


# -- Preventable Events tab --------------------------------------------------

def _preventable_tab() -> html.Div:
    ed_n = len(_ED_VISITS)
    avoidable_pct = (
        float((_ED_VISITS["avoidable"].fillna(0) > 0).mean())
        if not _ED_VISITS.empty else 0.0
    )
    pqi_admits_n = int(_PQI_RATE["denom_count"].sum()) if not _PQI_RATE.empty else 0
    inpatient_paid = (
        float(_ENCOUNTERS[_ENCOUNTERS["encounter_group"] == "inpatient"]["paid_amount"].sum())
        if not _ENCOUNTERS.empty else 0.0
    )

    cards = kpi_row([
        kpi_card("ED Visits", f"{ed_n:,}"),
        kpi_card("Avoidable %", _pct(avoidable_pct)),
        kpi_card("PQI Denom Population", f"{pqi_admits_n:,}",
                 sub="person-years in any AHRQ PQI denominator"),
        kpi_card("Inpatient Paid", _money(inpatient_paid)),
    ])

    # ED visits by avoidable category
    if not _ED_VISITS.empty:
        ed_pie = (
            _ED_VISITS.fillna({"avoidable_description": "unknown"})
            .groupby("avoidable_description")["encounter_id"].count().reset_index()
            .rename(columns={"encounter_id": "visits"})
        )
        fig_ed = px.pie(ed_pie, names="avoidable_description", values="visits",
                        title="ED visits by avoidable category")
        fig_ed.update_layout(height=340)
        ed_chart = dcc.Graph(figure=fig_ed)
    else:
        ed_chart = no_data_message()

    # PQI rate breakdown
    if not _PQI_RATE.empty:
        pqi = (
            _PQI_RATE.groupby("pqi_number")
            .agg(denom=("denom_count", "sum"), num=("num_count", "sum")).reset_index()
            .sort_values("denom", ascending=True)
        )
        pqi["pqi"] = "PQI " + pqi["pqi_number"].astype(str)
        fig_pqi = px.bar(pqi, x="denom", y="pqi", orientation="h",
                         title="AHRQ PQI denominator population")
        fig_pqi.update_layout(height=340, xaxis_title="person-years", yaxis_title="")
        pqi_chart = dcc.Graph(figure=fig_pqi)
    else:
        pqi_chart = no_data_message()

    # Avoidable ED by primary diagnosis
    avoidable_dx = pd.DataFrame()
    if not _ED_VISITS.empty and not _ENCOUNTERS.empty:
        ed_with_dx = _ED_VISITS.merge(
            _ENCOUNTERS[["encounter_id", "primary_diagnosis_description"]],
            on="encounter_id", how="left",
        )
        ed_with_dx = ed_with_dx[ed_with_dx["avoidable"].fillna(0) > 0]
        avoidable_dx = (
            ed_with_dx.dropna(subset=["primary_diagnosis_description"])
            .groupby("primary_diagnosis_description")
            .agg(visits=("encounter_id", "count"),
                 paid=("paid_amount", "sum")).reset_index()
            .sort_values("visits", ascending=False)
        )
        avoidable_dx["paid"] = avoidable_dx["paid"].round(0)

    return html.Div([
        cards,
        dbc.Row([
            dbc.Col(ed_chart, md=6),
            dbc.Col(pqi_chart, md=6),
        ], className="mb-3"),
        html.H5("Avoidable ED visits by primary diagnosis"),
        (dash_table.DataTable(
            data=avoidable_dx.to_dict("records"),
            columns=[{"name": c, "id": c} for c in avoidable_dx.columns],
            page_size=15, sort_action="native",
            style_cell={"fontSize": 12, "padding": "4px"},
            style_header={"fontWeight": "bold"},
        ) if not avoidable_dx.empty else no_data_message()),
    ], className="pt-3")


# -- Pharmacy tab ------------------------------------------------------------

def _pharmacy_tab() -> html.Div:
    if _PHARMACY.empty:
        return html.Div([no_data_message()], className="pt-3")

    total_paid = float(_PHARMACY["paid_amount"].sum())
    # Semantic layer 1.0 retired the generic-opportunity fields on
    # fact_pharmacy_claims with no replacement; a 1.0 source for this card is
    # backlog TUVA-136.
    generic_card = kpi_card("Generic Switching Opportunity", "—",
                            sub="Not in semantic layer 1.0")
    cards = kpi_row([
        kpi_card("Total Pharmacy Paid", _money(total_paid)),
        generic_card,
        kpi_card("Pharmacy Claims", f"{len(_PHARMACY):,}"),
    ])

    # ATC 3 grouping
    atc = (
        _PHARMACY.dropna(subset=["atc_3_name"])
        .groupby("atc_3_name")["paid_amount"].sum().reset_index()
        .sort_values("paid_amount", ascending=True).tail(15)
    )
    fig_atc = px.bar(atc, x="paid_amount", y="atc_3_name", orientation="h",
                     title="Spend by ATC-3 grouping (top 15)")
    fig_atc.update_layout(height=400, xaxis_tickprefix="$", xaxis_tickformat=",",
                          yaxis_title="", xaxis_title="")

    # Brand vs Generic
    bvg = (
        _PHARMACY.fillna({"brand_vs_generic": "unknown"})
        .groupby("brand_vs_generic")["paid_amount"].sum().reset_index()
    )
    fig_bvg = px.pie(bvg, names="brand_vs_generic", values="paid_amount",
                     title="Brand vs Generic spend")
    fig_bvg.update_layout(height=400)

    # Top brand drugs
    brand = (
        _PHARMACY.dropna(subset=["brand_name"])
        .groupby("brand_name")["paid_amount"].sum().reset_index()
        .sort_values("paid_amount", ascending=True).tail(10)
    )
    fig_brand = px.bar(brand, x="paid_amount", y="brand_name", orientation="h",
                       title="Top brand drugs by spend (top 10)")
    fig_brand.update_layout(height=400, xaxis_tickprefix="$", xaxis_tickformat=",",
                            yaxis_title="", xaxis_title="")

    # Prescribing specialty
    specialty = (
        _PHARMACY.dropna(subset=["prescribing_specialty"])
        .groupby("prescribing_specialty")["paid_amount"].sum().reset_index()
        .sort_values("paid_amount", ascending=False)
    )
    specialty["paid_amount"] = specialty["paid_amount"].round(0)
    specialty = specialty.rename(columns={
        "prescribing_specialty": "Specialty", "paid_amount": "Paid",
    })

    return html.Div([
        cards,
        dbc.Row([
            dbc.Col(dcc.Graph(figure=fig_atc), md=6),
            dbc.Col(dcc.Graph(figure=fig_bvg), md=6),
        ], className="mb-3"),
        dbc.Row([dbc.Col(dcc.Graph(figure=fig_brand), md=12)], className="mb-3"),
        html.H5("Spend by prescribing specialty"),
        dash_table.DataTable(
            data=specialty.to_dict("records"),
            columns=[{"name": c, "id": c} for c in specialty.columns],
            page_size=10, sort_action="native",
            style_cell={"fontSize": 12, "padding": "4px"},
            style_header={"fontWeight": "bold"},
        ),
    ], className="pt-3")


# -- Risk tab ----------------------------------------------------------------

def _risk_tab() -> html.Div:
    if _RISK_SCORES.empty and _RISK_FACTORS.empty:
        return html.Div([
            dbc.Alert(
                [
                    html.Strong("Risk model data not loaded. "),
                    "fact_risk_scores and fact_risk_factors are both empty in this "
                    "DuckDB. Run the Tuva CMS-HCC dbt models against a populated "
                    "claims dataset to enable this view.",
                ],
                color="info",
                className="mt-3",
            )
        ], className="pt-3")

    # If we did have data, render the standard heatmap + factor breakdown.
    cards = kpi_row([
        kpi_card("Members Scored", f"{_RISK_SCORES['person_id'].nunique():,}"),
        kpi_card("Avg Normalized Risk", f"{_RISK_SCORES['normalized_risk_score'].mean():.2f}"),
        kpi_card("Avg Blended Risk", f"{_RISK_SCORES['blended_risk_score'].mean():.2f}"),
    ])

    risk_with_dem = _RISK_SCORES.merge(
        _MEMBERS[["person_id", "age_group", "sex"]], on="person_id", how="left"
    )
    heatmap = (
        risk_with_dem.groupby(["age_group", "sex"])["normalized_risk_score"]
        .mean().reset_index()
        .pivot(index="age_group", columns="sex", values="normalized_risk_score")
        .fillna(0).reset_index()
    )

    factors_top = (
        _RISK_FACTORS.dropna(subset=["risk_factor_description"])
        .groupby(["factor_type", "risk_factor_description"])["coefficient"]
        .sum().reset_index().sort_values("coefficient", ascending=False)
    )

    return html.Div([
        cards,
        html.H5("Average normalized risk score by age group × sex"),
        dash_table.DataTable(
            data=heatmap.to_dict("records"),
            columns=[{"name": c, "id": c} for c in heatmap.columns],
            page_size=10, sort_action="native",
            style_cell={"fontSize": 12, "padding": "4px"},
            style_header={"fontWeight": "bold"},
        ),
        html.H5("Risk factor contributions", className="mt-3"),
        dash_table.DataTable(
            data=factors_top.to_dict("records"),
            columns=[{"name": c, "id": c} for c in factors_top.columns],
            page_size=15, sort_action="native",
            style_cell={"fontSize": 12, "padding": "4px"},
            style_header={"fontWeight": "bold"},
        ),
    ], className="pt-3")


# -- entry point --------------------------------------------------------------

def build_layout() -> html.Div:
    body = dbc.Tabs([
        dbc.Tab(_pmpm_tab(), label="PMPM"),
        dbc.Tab(_overview_tab(), label="Population Overview"),
        dbc.Tab(_inpatient_tab(), label="Inpatient"),
        dbc.Tab(_preventable_tab(), label="Preventable Events"),
        dbc.Tab(_pharmacy_tab(), label="Pharmacy"),
        dbc.Tab(_risk_tab(), label="Risk"),
    ])

    return page_shell(
        title="Population Health",
        subtitle=(
            "Demographics, chronic conditions, inpatient utilization, "
            "preventable events, pharmacy spend, and risk scores."
        ),
        body=body,
        tuva_tables=[
            "semantic_layer.fact_member_months",
            "semantic_layer.dim_member",
            CONDITIONS_TABLE,
            "semantic_layer.fact_encounters",
            "semantic_layer.fact_admissions",
            "semantic_layer.fact_ed_visits",
            "semantic_layer.fact_pharmacy_claims",
            "semantic_layer.fact_risk_scores",
            "ahrq_quality_indicators.pqi_rate",
        ],
    )
