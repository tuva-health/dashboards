"""Layout for the Semantic Layer model browser.

The PBI .pbit file for this dashboard is a blank report — its sole purpose
is to publish the unified semantic model that the other dashboards
consume. Rather than mirror an empty page, this Dash version is a useful
*model browser*: a single-screen overview of every table, its row count,
its freshness, its columns, and the inferred relationships across its facts and
dimensions (8 dimensions and 11 facts in semantic layer 1.0).
"""

from __future__ import annotations

import dash_bootstrap_components as dbc
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from dash import Input, Output, callback, dash_table, dcc, html

from tuva_dash.components import kpi_card, kpi_row, no_data_message, page_shell
from tuva_dash.lazy import LazyFrame

from . import queries

# Lazy module-level cache. The model browser only queries information_schema
# when the Semantic Layer page is visited.
_TABLES = LazyFrame(queries.load_tables)
_COLUMNS = LazyFrame(queries.load_columns)


# -- relationship graph ------------------------------------------------------

# Inferred from naming conventions in the semantic_layer dbt package (1.0):
# fact_* tables join to the dim_* tables that share a key column. Member
# months join on Core's `member_month_id` where a fact carries it; the
# encounter-grain facts carry only the deprecated person-and-month
# `member_month_sk`, so their member-month join is the composite natural key,
# with the month derived from the encounter's start date. That join is many to
# many where a person holds two coverage rows (payers or plans) in one month.
# 1.0 retired dim_condition, fact_member_condition_bridge and
# fact_expected_values. Each tuple is (fact_table, dim_table, join_key).
_RELATIONSHIPS = [
    ("fact_member_months", "dim_member", "person_id"),
    ("fact_member_months", "dim_data_source", "data_source"),
    ("fact_member_months", "dim_member_months", "member_month_id"),
    ("fact_encounters", "dim_member", "person_id"),
    ("fact_encounters", "dim_encounter_group", "encounter_group_sk"),
    ("fact_encounters", "dim_encounter_type", "encounter_type_sk"),
    ("fact_encounters", "dim_member_months", "person_id + data_source + yyyymm(encounter_start_date)"),
    ("fact_claims", "dim_member", "person_id"),
    ("fact_claims", "dim_encounter_group", "encounter_group_sk"),
    ("fact_claims", "dim_encounter_type", "encounter_type_sk"),
    ("fact_claims", "dim_service_category", "service_category_sk"),
    ("fact_claims", "dim_member_months", "member_month_id"),
    ("fact_admissions", "dim_member", "person_id"),
    ("fact_admissions", "dim_member_months", "person_id + data_source + yyyymm(admit_date)"),
    ("fact_ed_visits", "dim_member", "person_id"),
    ("fact_ed_visits", "dim_member_months", "person_id + data_source + yyyymm(encounter_start_date)"),
    ("fact_pharmacy_claims", "dim_member", "person_id"),
    ("fact_pharmacy_claims", "dim_member_months", "member_month_id"),
    ("fact_quality_measures", "dim_member", "person_id"),
    ("fact_risk_scores", "dim_member", "person_id"),
    ("fact_risk_factors", "dim_member", "person_id"),
    ("fact_hcc_gaps", "dim_member", "person_id"),
    ("fact_encounter_service_bridge", "dim_service_category", "service_category_sk"),
]


def _relationships_table() -> pd.DataFrame:
    if _TABLES.empty:
        return pd.DataFrame(columns=["fact", "dim", "join_key"])
    valid = set(_TABLES["table_name"])
    rows = [
        {"fact": f, "dim": d, "join_key": k}
        for f, d, k in _RELATIONSHIPS
        if f in valid and d in valid
    ]
    return pd.DataFrame(rows)


def _relationships_graph(rel: pd.DataFrame) -> go.Figure:
    """Force-directed-ish bipartite graph: facts on the left, dims on the right."""
    if rel.empty:
        return go.Figure()

    facts = sorted(rel["fact"].unique())
    dims = sorted(rel["dim"].unique())

    # Lay out facts on x=0, dims on x=1, evenly spaced in y.
    pos = {}
    for i, f in enumerate(facts):
        pos[f] = (0.0, 1.0 - (i + 0.5) / len(facts))
    for i, d in enumerate(dims):
        pos[d] = (1.0, 1.0 - (i + 0.5) / len(dims))

    edge_x, edge_y = [], []
    for _, r in rel.iterrows():
        x0, y0 = pos[r["fact"]]
        x1, y1 = pos[r["dim"]]
        edge_x += [x0, x1, None]
        edge_y += [y0, y1, None]

    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=edge_x, y=edge_y, mode="lines",
        line=dict(color="#bbb", width=1),
        hoverinfo="none", showlegend=False,
    ))
    # Facts (orange)
    fig.add_trace(go.Scatter(
        x=[pos[f][0] for f in facts],
        y=[pos[f][1] for f in facts],
        text=facts, mode="markers+text", textposition="middle right",
        marker=dict(size=14, color="#ff7f0e"),
        name="facts",
    ))
    # Dims (blue)
    fig.add_trace(go.Scatter(
        x=[pos[d][0] for d in dims],
        y=[pos[d][1] for d in dims],
        text=dims, mode="markers+text", textposition="middle left",
        marker=dict(size=14, color="#1f77b4"),
        name="dimensions",
    ))
    fig.update_layout(
        height=720,
        showlegend=True,
        xaxis=dict(visible=False, range=[-0.4, 1.4]),
        yaxis=dict(visible=False),
        margin=dict(l=10, r=10, t=30, b=10),
        title="Inferred relationships between facts and dimensions",
    )
    return fig


# -- callbacks ---------------------------------------------------------------

@callback(
    Output("sl-table-detail", "children"),
    Input("sl-table-select", "value"),
)
def _render_table_detail(table_name):
    if not table_name:
        return dbc.Alert("Pick a table to inspect its columns and a sample.",
                         color="info", className="mt-3")

    cols = _COLUMNS[_COLUMNS["table_name"] == table_name].copy()
    cols = cols[["ordinal_position", "column_name", "data_type"]].rename(columns={
        "ordinal_position": "#",
        "column_name": "Column",
        "data_type": "Type",
    })

    sample = queries.load_sample(table_name, limit=50)

    schema_card = dbc.Card(
        [
            dbc.CardHeader(html.H6(f"{table_name} — columns ({len(cols)})", className="mb-0")),
            dbc.CardBody(
                dash_table.DataTable(
                    data=cols.to_dict("records"),
                    columns=[{"name": c, "id": c} for c in cols.columns],
                    page_size=20,
                    style_cell={"fontSize": 12, "padding": "4px"},
                    style_header={"fontWeight": "bold"},
                ),
            ),
        ],
        className="mb-3",
    )

    sample_card = dbc.Card(
        [
            dbc.CardHeader(html.H6(
                f"Sample — first {min(50, len(sample))} rows", className="mb-0")),
            dbc.CardBody(
                dash_table.DataTable(
                    data=sample.to_dict("records"),
                    columns=[{"name": c, "id": c} for c in sample.columns],
                    page_size=10,
                    sort_action="native",
                    filter_action="native",
                    style_cell={"fontSize": 11, "padding": "3px",
                                "minWidth": 80, "maxWidth": 220,
                                "textOverflow": "ellipsis", "overflow": "hidden"},
                    style_header={"fontWeight": "bold"},
                    style_table={"overflowX": "auto"},
                ) if not sample.empty else no_data_message(),
            ),
        ],
        className="mb-3",
    )

    return [schema_card, sample_card]


# -- entry point --------------------------------------------------------------

def build_layout() -> html.Div:
    if _TABLES.empty:
        return page_shell(
            title="Enterprise Analytics Semantic Layer",
            subtitle="Model browser for the unified Tuva semantic_layer schema.",
            body=no_data_message(),
        )

    facts = _TABLES[_TABLES["kind"] == "fact"]
    dims = _TABLES[_TABLES["kind"] == "dim"]
    last_run = None
    if "last_run" in _TABLES.columns:
        candidates = []
        for v in _TABLES["last_run"].dropna():
            try:
                ts = pd.Timestamp(v)
                if ts.tz is not None:
                    ts = ts.tz_convert("UTC").tz_localize(None)
                candidates.append(ts)
            except Exception:
                continue
        if candidates:
            last_run = max(candidates)

    cards = kpi_row([
        kpi_card("Tables", f"{len(_TABLES):,}"),
        kpi_card("Fact tables", f"{len(facts):,}"),
        kpi_card("Dim tables", f"{len(dims):,}"),
        kpi_card("Total rows",
                 f"{int(_TABLES['row_count'].sum()):,}"),
        kpi_card("Last run", str(pd.to_datetime(last_run).date()) if last_run else "—"),
    ])

    # Tables overview chart (rows by table)
    chart_df = _TABLES.sort_values("row_count")
    fig = px.bar(
        chart_df, x="row_count", y="table_name", color="kind",
        orientation="h", title="Row counts by table",
        color_discrete_map={"fact": "#ff7f0e", "dim": "#1f77b4"},
    )
    fig.update_layout(height=600, yaxis_title="", xaxis_title="rows")

    # Inventory table
    inventory = _TABLES.copy()
    inventory["last_run"] = inventory["last_run"].astype(str).where(
        inventory["last_run"].notna(), "—"
    )
    inventory = inventory.rename(columns={
        "table_name": "Table",
        "kind": "Kind",
        "row_count": "Rows",
        "last_run": "Last run",
    })

    # Relationships
    rel = _relationships_table()
    rel_table = dash_table.DataTable(
        data=rel.to_dict("records"),
        columns=[{"name": c, "id": c} for c in rel.columns],
        page_size=15, sort_action="native",
        style_cell={"fontSize": 12, "padding": "4px"},
        style_header={"fontWeight": "bold"},
    ) if not rel.empty else no_data_message()

    overview_tab = html.Div([
        cards,
        dbc.Row([
            dbc.Col(dcc.Graph(figure=fig), md=7),
            dbc.Col([
                html.H5("Tables", className="mt-1"),
                dash_table.DataTable(
                    data=inventory.to_dict("records"),
                    columns=[{"name": c, "id": c} for c in inventory.columns],
                    page_size=22, sort_action="native",
                    style_cell={"fontSize": 12, "padding": "4px"},
                    style_header={"fontWeight": "bold"},
                ),
            ], md=5),
        ]),
    ], className="pt-3")

    table_options = [{"label": t, "value": t} for t in _TABLES["table_name"]]
    browse_tab = html.Div([
        html.Div([
            html.Label("Table:", className="small text-muted"),
            dcc.Dropdown(
                id="sl-table-select",
                options=table_options,
                placeholder="Select a table to inspect",
            ),
        ], className="mb-3", style={"maxWidth": "500px"}),
        html.Div(id="sl-table-detail"),
    ], className="pt-3")

    relationships_tab = html.Div([
        dbc.Row([
            dbc.Col(dcc.Graph(figure=_relationships_graph(rel)), md=8),
            dbc.Col([
                html.H6("Join keys"),
                rel_table,
            ], md=4),
        ]),
    ], className="pt-3")

    body = dbc.Tabs([
        dbc.Tab(overview_tab, label="Model Overview"),
        dbc.Tab(browse_tab, label="Browse Tables"),
        dbc.Tab(relationships_tab, label="Relationships"),
    ])

    return page_shell(
        title="Enterprise Analytics Semantic Layer",
        subtitle=(
            "Model browser for the unified Tuva semantic_layer schema — "
            f"{len(_TABLES)} tables, {int(_TABLES['row_count'].sum()):,} total rows."
        ),
        body=body,
        tuva_tables=["semantic_layer.*"],
    )
