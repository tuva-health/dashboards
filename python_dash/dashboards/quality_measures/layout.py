"""Layout for the Quality Measures dashboard.

Mirrors the 2 PBI pages:
  1. Quality Measure Summary — gauge + measure-level summary table + provider rollup
  2. Measure Detail — members with open gaps for a chosen measure

Combines clinical measures (`quality_measures.summary_long`) with AHRQ
Prevention Quality Indicators (`ahrq_quality_indicators.pqi_rate`) so the dashboard
still has data even when the clinical measures aren't populated (common
in synthetic Tuva data sets that lack meds/labs).
"""

from __future__ import annotations

import dash_bootstrap_components as dbc
import pandas as pd
import plotly.graph_objects as go
from dash import Input, Output, callback, dash_table, dcc, html

from tuva_dash.components import kpi_card, kpi_row, no_data_message, page_shell
from tuva_dash.lazy import LazyFrame

from . import queries

# Default rate target — PBI used a parameterized "Quality target" measure
# defaulting to 80%. Adjust by editing here or via a future parameter.
QUALITY_TARGET = 0.80

_CLINICAL = LazyFrame(queries.load_clinical_long)
_CLINICAL_WIDE = LazyFrame(queries.load_clinical_wide)
_AHRQ_RATE = LazyFrame(queries.load_ahrq_rate)
_AHRQ_DENOM = LazyFrame(queries.load_ahrq_denom_long)
_AHRQ_NUM = LazyFrame(queries.load_ahrq_num_long)
_MEMBERS = LazyFrame(queries.load_dim_member)
_MEMBER_MONTHS = LazyFrame(queries.load_dim_member_months)


# -- helpers ------------------------------------------------------------------

def _provider_attribution() -> pd.DataFrame:
    """One row per person with most-recent provider attribution."""
    if _MEMBER_MONTHS.empty:
        return pd.DataFrame(columns=[
            "person_id", "payer_attributed_provider",
            "payer_attributed_provider_practice",
        ])
    df = _MEMBER_MONTHS.sort_values("year_month").drop_duplicates(
        subset=["person_id"], keep="last"
    )
    return df[[
        "person_id", "payer_attributed_provider",
        "payer_attributed_provider_practice",
    ]]


def _measure_summary() -> pd.DataFrame:
    """Single measure-level table union'd from clinical + AHRQ sources."""
    rows = []

    # Clinical measures: aggregate from summary_long
    if not _CLINICAL.empty:
        clean = _CLINICAL.dropna(subset=["measure_id"])
        if not clean.empty:
            agg = (
                clean.groupby(["measure_id", "measure_name"])
                .agg(
                    denominator=("denominator_flag", "sum"),
                    numerator=("numerator_flag", "sum"),
                    exclusions=("exclusion_flag", "sum"),
                )
                .reset_index()
            )
            agg["source"] = "clinical"
            agg["rate"] = agg["numerator"] / agg["denominator"].where(agg["denominator"] != 0)
            rows.append(agg)

    # AHRQ measures: pqi_rate already has denom_count/num_count
    if not _AHRQ_RATE.empty:
        ahrq = _AHRQ_RATE.copy()
        agg = (
            ahrq.groupby("pqi_number")
            .agg(
                denominator=("denom_count", "sum"),
                numerator=("num_count", "sum"),
            )
            .reset_index()
            .rename(columns={"pqi_number": "measure_id"})
        )
        agg["measure_name"] = "AHRQ PQI " + agg["measure_id"].astype(str)
        agg["exclusions"] = 0
        agg["source"] = "ahrq"
        agg["rate"] = agg["numerator"] / agg["denominator"].where(agg["denominator"] != 0)
        rows.append(agg)

    if not rows:
        return pd.DataFrame(columns=[
            "measure_id", "measure_name", "denominator", "numerator",
            "exclusions", "rate", "source", "meets_target",
        ])

    out = pd.concat(rows, ignore_index=True)
    out["meets_target"] = out["rate"].fillna(0) >= QUALITY_TARGET
    return out[
        ["measure_id", "measure_name", "source",
         "denominator", "numerator", "exclusions", "rate", "meets_target"]
    ].sort_values(["source", "measure_id"])


def _gauge(rate: float):
    fig = go.Figure(
        go.Indicator(
            mode="gauge+number",
            value=(rate or 0) * 100,
            number={"suffix": "%"},
            domain={"x": [0, 1], "y": [0, 1]},
            title={"text": "Quality measures meeting target"},
            gauge={
                "axis": {"range": [0, 100]},
                "bar": {"color": "#1f77b4"},
                "steps": [
                    {"range": [0, 50], "color": "#fbe4e4"},
                    {"range": [50, 80], "color": "#fff3cd"},
                    {"range": [80, 100], "color": "#d4edda"},
                ],
                "threshold": {
                    "line": {"color": "#d62728", "width": 3},
                    "thickness": 0.75,
                    "value": QUALITY_TARGET * 100,
                },
            },
        )
    )
    fig.update_layout(height=300, margin=dict(l=20, r=20, t=40, b=20))
    return dcc.Graph(figure=fig)


def _summary_kpis(summary: pd.DataFrame) -> dbc.Row:
    if summary.empty:
        return kpi_row([
            kpi_card("Measures Tracked", "0"),
            kpi_card("Meeting Target", "0"),
            kpi_card("Members in Denom.", "0"),
            kpi_card("Avg Rate", "—"),
        ])
    member_total = 0
    if not _CLINICAL.empty:
        clean = _CLINICAL.dropna(subset=["measure_id"])
        if not clean.empty:
            member_total = clean[clean["denominator_flag"] == 1]["person_id"].nunique()
    if not _AHRQ_DENOM.empty:
        member_total += _AHRQ_DENOM["person_id"].nunique()

    avg_rate = summary["rate"].dropna().mean()
    return kpi_row([
        kpi_card("Measures Tracked", f"{len(summary):,}"),
        kpi_card("Meeting Target", f"{int(summary['meets_target'].sum()):,}",
                 sub=f"of {len(summary)}"),
        kpi_card("Members in Denom.", f"{member_total:,}"),
        kpi_card("Avg Rate", f"{avg_rate * 100:.1f}%" if avg_rate == avg_rate else "—"),
    ])


def _summary_table(summary: pd.DataFrame):
    if summary.empty:
        return no_data_message()
    df = summary.copy()
    df["rate"] = (df["rate"].fillna(0) * 100).round(1)
    df["target"] = QUALITY_TARGET * 100
    df = df.rename(columns={
        "measure_id": "Measure ID",
        "measure_name": "Measure Name",
        "source": "Source",
        "denominator": "Denominator",
        "numerator": "Numerator",
        "exclusions": "Exclusions",
        "rate": "Rate %",
        "target": "Target %",
    })
    df = df[["Measure ID", "Measure Name", "Source", "Denominator",
             "Numerator", "Exclusions", "Rate %", "Target %"]]

    return dash_table.DataTable(
        data=df.to_dict("records"),
        columns=[{"name": c, "id": c} for c in df.columns],
        page_size=20,
        sort_action="native",
        filter_action="native",
        style_cell={"fontSize": 13, "padding": "5px"},
        style_header={"fontWeight": "bold"},
        style_data_conditional=[
            {
                "if": {"filter_query": "{Rate %} >= {Target %}", "column_id": "Rate %"},
                "backgroundColor": "#d4edda",
            },
            {
                "if": {"filter_query": "{Rate %} < {Target %}", "column_id": "Rate %"},
                "backgroundColor": "#fbe4e4",
            },
        ],
    )


def _provider_summary():
    """Pivot of provider practice → measures meeting target rates."""
    attribution = _provider_attribution()
    summary = _measure_summary()
    if attribution.empty or summary.empty or _CLINICAL.empty:
        return no_data_message()

    clean = _CLINICAL.dropna(subset=["measure_id"])
    if clean.empty:
        return dbc.Alert(
            "Provider rollup unavailable — clinical measure data isn't populated "
            "in this dataset (synthetic data without meds/labs).",
            color="secondary", className="mt-1",
        )

    df = clean.merge(attribution, on="person_id", how="left")
    df["meets_target"] = (df["numerator_flag"] == 1).astype(int)
    g = (
        df.groupby("payer_attributed_provider_practice")
        .agg(
            denom=("denominator_flag", "sum"),
            num=("numerator_flag", "sum"),
        )
        .reset_index()
    )
    g["rate"] = (g["num"] / g["denom"].where(g["denom"] != 0) * 100).round(1)
    g = g.rename(columns={
        "payer_attributed_provider_practice": "Practice",
        "denom": "Denominator",
        "num": "Numerator",
        "rate": "Rate %",
    })
    return dash_table.DataTable(
        data=g.to_dict("records"),
        columns=[{"name": c, "id": c} for c in g.columns],
        page_size=15,
        sort_action="native",
        style_cell={"fontSize": 13, "padding": "5px"},
        style_header={"fontWeight": "bold"},
    )


# -- Measure Detail tab -------------------------------------------------------

def _measure_detail_options() -> list[dict]:
    out = []
    if not _CLINICAL.empty:
        clean = _CLINICAL.dropna(subset=["measure_id"])
        for mid in sorted(clean["measure_id"].unique()):
            mname = clean[clean["measure_id"] == mid]["measure_name"].iloc[0]
            out.append({"label": f"{mid} — {mname}", "value": f"clinical:{mid}"})
    if not _AHRQ_RATE.empty:
        for mid in sorted(_AHRQ_RATE["pqi_number"].astype(str).unique()):
            out.append({"label": f"AHRQ PQI {mid}", "value": f"ahrq:{mid}"})
    return out


def _members_with_gaps(measure_value: str | None) -> pd.DataFrame:
    if not measure_value:
        return pd.DataFrame()
    source, measure_id = measure_value.split(":", 1)
    if source == "clinical" and not _CLINICAL.empty:
        df = _CLINICAL[
            (_CLINICAL["measure_id"] == measure_id)
            & (_CLINICAL["denominator_flag"] == 1)
            & (_CLINICAL["numerator_flag"].fillna(0) == 0)
            & (_CLINICAL["exclusion_flag"].fillna(0) == 0)
        ]
        return df[["person_id", "measure_id", "measure_name", "evidence_date",
                   "performance_period_begin", "performance_period_end"]]
    if source == "ahrq":
        # AHRQ PQI: a "gap" is a denom row that doesn't appear in num rows
        denom = _AHRQ_DENOM[_AHRQ_DENOM["pqi_number"].astype(str) == measure_id]
        num = _AHRQ_NUM[_AHRQ_NUM["pqi_number"].astype(str) == measure_id]
        gaps = denom[~denom["person_id"].isin(num["person_id"])]
        gaps = gaps.copy()
        gaps["measure_id"] = measure_id
        gaps["measure_name"] = "AHRQ PQI " + measure_id
        return gaps[["person_id", "measure_id", "measure_name",
                     "year_number", "data_source"]]
    return pd.DataFrame()


@callback(
    Output("qm-detail-content", "children"),
    Input("qm-measure-select", "value"),
)
def _render_detail(measure_value):
    if not measure_value:
        return dbc.Alert(
            "Pick a measure from the dropdown to see members with open gaps.",
            color="info", className="mt-3",
        )
    gaps = _members_with_gaps(measure_value)
    if gaps.empty:
        return dbc.Alert(
            "No open gaps for this measure (or denominator is empty in the "
            "current dataset).", color="secondary", className="mt-3",
        )
    enriched = gaps.merge(_MEMBERS, on="person_id", how="left")
    attribution = _provider_attribution()
    enriched = enriched.merge(attribution, on="person_id", how="left")

    cols = [c for c in [
        "person_id", "measure_id", "measure_name", "age", "sex",
        "payer_attributed_provider", "payer_attributed_provider_practice",
        "year_number", "evidence_date",
        "performance_period_begin", "performance_period_end",
    ] if c in enriched.columns]

    return html.Div([
        html.P(f"{len(enriched):,} members with open gaps", className="text-muted small"),
        dash_table.DataTable(
            data=enriched[cols].to_dict("records"),
            columns=[{"name": c, "id": c} for c in cols],
            page_size=20,
            sort_action="native",
            filter_action="native",
            style_cell={"fontSize": 12, "padding": "4px"},
            style_header={"fontWeight": "bold"},
        ),
    ])


# -- entry point --------------------------------------------------------------

def build_layout() -> html.Div:
    summary = _measure_summary()
    rate_meeting_target = (
        summary["meets_target"].mean() if not summary.empty else 0.0
    )

    summary_tab = html.Div(
        [
            _summary_kpis(summary),
            dbc.Row(
                [
                    dbc.Col(_gauge(rate_meeting_target), md=4),
                    dbc.Col(
                        [
                            html.H5("Quality measures summary"),
                            _summary_table(summary),
                        ],
                        md=8,
                    ),
                ],
                className="mb-3",
            ),
            html.H5("Provider quality measures summary", className="mt-3"),
            _provider_summary(),
        ],
        className="pt-3",
    )

    detail_tab = html.Div(
        [
            html.Div(
                [
                    html.Label("Measure:", className="small text-muted"),
                    dcc.Dropdown(
                        id="qm-measure-select",
                        options=_measure_detail_options(),
                        placeholder="Select a measure to view members with gaps",
                    ),
                ],
                className="mb-3",
                style={"maxWidth": "600px"},
            ),
            html.Div(id="qm-detail-content"),
        ],
        className="pt-3",
    )

    body = dbc.Tabs([
        dbc.Tab(summary_tab, label="Quality Measure Summary"),
        dbc.Tab(detail_tab, label="Measure Detail"),
    ])

    return page_shell(
        title="Quality Measures",
        subtitle=(
            "Clinical and AHRQ prevention quality measure performance, "
            "with member-level gap detail."
        ),
        body=body,
        tuva_tables=[
            "quality_measures.summary_long",
            "quality_measures.summary_wide",
            "ahrq_quality_indicators.pqi_rate",
            "ahrq_quality_indicators.pqi_denom_long",
            "ahrq_quality_indicators.pqi_num_long",
            "semantic_layer.dim_member",
            "semantic_layer.dim_member_months",
        ],
    )
