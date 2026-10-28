"""Layout for the Risk-Adjusted Benchmarks dashboard."""

from __future__ import annotations

import dash_bootstrap_components as dbc
import pandas as pd
import plotly.express as px
from dash import dash_table, dcc, html

from tuva_dash.components import kpi_card, kpi_row, no_data_message, page_shell
from tuva_dash.config import get_settings

from . import queries


def _empty_message() -> dbc.Alert:
    """Context-aware alert.

    With LOAD_DATA=false the generic message tells the user how to enable
    queries. With LOAD_DATA=true an empty frame here can only mean the
    `benchmarks.*` tables aren't in the warehouse — that schema is
    published separately by Tuva and isn't part of the standard dbt
    build, so we surface that specifically rather than blaming LOAD_DATA.
    """
    if not get_settings().load_data:
        return no_data_message()
    return dbc.Alert(
        [
            html.Strong("Benchmarks schema not loaded. "),
            "This dashboard reads ",
            html.Code("benchmarks.predict_member_month"),
            " and ",
            html.Code("benchmarks.predict_inpatient"),
            ", which Tuva publishes separately from the open-source dbt "
            "package. Load the benchmarks dataset into your warehouse to "
            "populate this view.",
        ],
        color="info",
    )


def _fmt_money(v: float) -> str:
    return "—" if pd.isna(v) else f"${v:,.0f}"


def _fmt_pct(v: float) -> str:
    if pd.isna(v):
        return "—"
    return f"{v * 100:.1f}%" if abs(v) <= 1 else f"{v:.1f}%"


def _pmpm_kpis(mm: pd.DataFrame) -> dbc.Row:
    if mm.empty:
        return kpi_row([
            kpi_card("Actual PMPM", "—"),
            kpi_card("Expected PMPM", "—"),
            kpi_card("Difference", "—"),
            kpi_card("Member Months", "0"),
        ])
    actual = mm["actual_pmpm"].mean()
    expected = mm["expected_pmpm"].mean()
    member_months = mm["member_months"].sum() if "member_months" in mm else len(mm)
    return kpi_row([
        kpi_card("Actual PMPM", _fmt_money(actual)),
        kpi_card("Expected PMPM", _fmt_money(expected)),
        kpi_card(
            "Difference",
            _fmt_money(actual - expected),
            sub="actual − expected",
            color="warning" if actual > expected else "success",
        ),
        kpi_card("Member Months", f"{int(member_months):,}"),
    ])


def _pmpm_trend(mm: pd.DataFrame):
    if mm.empty:
        return _empty_message()
    df = mm.copy()
    df["year_month"] = pd.to_datetime(df["year_month"], errors="coerce")
    by_month = (
        df.groupby("year_month")[["actual_pmpm", "expected_pmpm"]].mean().reset_index()
    )
    fig = px.line(
        by_month.melt(id_vars="year_month", var_name="metric", value_name="pmpm"),
        x="year_month",
        y="pmpm",
        color="metric",
        title="PMPM — actual vs expected",
    )
    fig.update_layout(height=400, legend_title_text="")
    return dcc.Graph(figure=fig)


def _pmpm_by_service(mm: pd.DataFrame):
    if mm.empty or "service_category_1" not in mm.columns:
        return _empty_message()
    by_svc = (
        mm.groupby("service_category_1")[["actual_pmpm", "expected_pmpm"]]
        .mean()
        .reset_index()
        .melt(id_vars="service_category_1", var_name="metric", value_name="pmpm")
    )
    fig = px.bar(
        by_svc,
        x="service_category_1",
        y="pmpm",
        color="metric",
        barmode="group",
        title="PMPM by service category",
    )
    fig.update_layout(height=400, xaxis_title="", legend_title_text="")
    return dcc.Graph(figure=fig)


def _inpatient_kpis(ip: pd.DataFrame) -> dbc.Row:
    if ip.empty:
        return kpi_row([
            kpi_card("Actual LOS", "—"),
            kpi_card("Expected LOS", "—"),
            kpi_card("Actual Readmit", "—"),
            kpi_card("Expected Readmit", "—"),
            kpi_card("Inpatient Paid", "—"),
        ])
    return kpi_row([
        kpi_card("Actual LOS", f"{ip['actual_los'].mean():.1f}"),
        kpi_card("Expected LOS", f"{ip['expected_los'].mean():.1f}"),
        kpi_card("Actual Readmit", _fmt_pct(ip["actual_readmission"].mean())),
        kpi_card("Expected Readmit", _fmt_pct(ip["expected_readmission"].mean())),
        kpi_card("Inpatient Paid", _fmt_money(ip["paid_amount"].sum())),
    ])


def _readmission_trend(ip: pd.DataFrame):
    if ip.empty or "discharge_date" not in ip.columns:
        return _empty_message()
    df = ip.copy()
    df["discharge_date"] = pd.to_datetime(df["discharge_date"], errors="coerce")
    df["year_month"] = df["discharge_date"].dt.to_period("M").dt.to_timestamp()
    by_m = (
        df.groupby("year_month")[["actual_readmission", "expected_readmission"]]
        .mean()
        .reset_index()
    )
    fig = px.line(
        by_m.melt(id_vars="year_month", var_name="metric", value_name="rate"),
        x="year_month",
        y="rate",
        color="metric",
        title="30-day readmission rate over time",
    )
    fig.update_layout(height=400, legend_title_text="", yaxis_tickformat=".0%")
    return dcc.Graph(figure=fig)


def _inpatient_table(ip: pd.DataFrame):
    if ip.empty:
        return _empty_message()
    return dash_table.DataTable(
        data=ip.head(500).to_dict("records"),
        columns=[{"name": c, "id": c} for c in ip.columns],
        page_size=25,
        sort_action="native",
        filter_action="native",
        style_cell={"fontSize": 12},
    )


def build_layout() -> html.Div:
    mm = queries.load_member_month()
    ip = queries.load_inpatient()

    pmpm_tab = html.Div(
        [
            _pmpm_kpis(mm),
            dbc.Row(
                [
                    dbc.Col(_pmpm_trend(mm), md=7),
                    dbc.Col(_pmpm_by_service(mm), md=5),
                ],
                className="mb-3",
            ),
        ],
        className="pt-3",
    )

    inpatient_tab = html.Div(
        [
            _inpatient_kpis(ip),
            _readmission_trend(ip),
            html.H5("Inpatient encounters (sample)", className="mt-3"),
            _inpatient_table(ip),
        ],
        className="pt-3",
    )

    body = dbc.Tabs(
        [
            dbc.Tab(label="PMPM and Encounters", children=pmpm_tab),
            dbc.Tab(label="Inpatient", children=inpatient_tab),
        ]
    )

    return page_shell(
        title="Risk-Adjusted Benchmarks",
        subtitle="Actual vs expected PMPM and inpatient outcomes.",
        body=body,
        tuva_tables=[
            "benchmarks.predict_member_month",
            "benchmarks.predict_inpatient",
        ],
    )
