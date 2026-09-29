# Tuva Dash — Python alternatives to the Power BI dashboards

This directory mirrors `../power_bi/` with Python [Dash](https://dash.plotly.com/)
applications, for users who want to explore the [Tuva Project](https://thetuvaproject.com/)
data model without installing Power BI Desktop.

Each PBI dashboard has a corresponding Dash app under `dashboards/`.

## Layout

```
python_dash/
├── tuva_dash/                 # shared library
│   ├── config.py              # loads connection params from .env
│   ├── db.py                  # multi-warehouse connector
│   ├── theme.py               # shared Dash theme + Plotly template
│   └── components.py          # KPI cards, page-shell helpers
└── dashboards/
    ├── dqi_analytics/         # Data Quality Index
    ├── risk_adjust_benchmark/ # Risk-Adjusted Benchmarks
    ├── cost_and_utilization/  # Cost & Utilization (7 PBI pages)
    ├── cost_drivers/          # Cost Drivers (chronic-condition cohort filter)
    ├── mssp_aco_dashboard/    # MSSP ACO Performance (practice/provider/patient drill-down)
    ├── population_health/     # Population Health (6 PBI pages)
    ├── quality_measures/      # Quality Measures (clinical + AHRQ PQI)
    └── semantic_layer/        # Semantic Layer model browser
```

All eight dashboards are implemented end-to-end against the standard
Tuva schemas (`semantic_layer.*`, `data_quality.*`, `quality_measures.*`,
`ahrq_measures.*`). They render against any Tuva install, with graceful
"data not loaded" alerts on tabs whose source tables are empty (e.g.
`fact_risk_*` in synthetic builds, `benchmarks.*` which ships separately).

## Setup

```bash
# from the python_dash/ directory
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env               # then fill in connection details
```

Tested on Python 3.10+.

### Warehouse drivers

`requirements.txt` installs the **DuckDB** and **Snowflake** drivers by
default — DuckDB is the easiest local option (it's what Tuva's `dbt build`
writes to), and Snowflake is the most common hosted target. To use any
other warehouse, uncomment the relevant line in `requirements.txt` and
re-run `pip install`.

The connector dispatches on `DATA_WAREHOUSE_TYPE`. Supported values:
`duckdb`, `snowflake`, `bigquery`, `redshift`, `odbc`, `sqlserver`, `fabric`
(the non-DuckDB values match the PBI `data_warehouse_type` parameter).

### Pointing at a local Tuva DuckDB

If you've run `dbt build` against a local DuckDB Tuva install:

```bash
# .env
LOAD_DATA=true
DATA_WAREHOUSE_TYPE=duckdb
DUCKDB_DATABASE=../../tuva/tuva.duckdb   # relative to python_dash/
SCHEMA_PREPEND_NAME=NULL
```

Caveats specific to local DuckDB Tuva installs:

- **DQI Analytics** has been ported to read the standard Tuva DQ tables
  (`data_quality.medical_claim_claim_flags`, `logical`, `structural`,
  `analytical_data_marts`) instead of the PBI-only
  `data_quality_for_pbi` view, so it works against a fresh `dbt build`.
- **Risk-Adjusted Benchmarks** depends on the `benchmarks` schema, which
  is published separately by Tuva and isn't part of the standard dbt
  build. The dashboard renders gracefully with empty visuals if that
  schema is missing.
- **MSSP ACO Performance** reads two optional benchmark facts described
  below. Without them the benchmark elements show an alert and the rest of
  the dashboard is unchanged.

### Semantic layer benchmark facts (MSSP ACO Performance)

The MSSP benchmark models build two facts in the `semantic_layer` schema
beside the standard Tuva tables. The Dash MSSP ACO dashboard reads them;
the Power BI MSSP ACO template does not yet, and can be extended the same
way.

| Fact | Grain | Join |
| --- | --- | --- |
| `semantic_layer.fact_member_month_benchmark` | one row per member-month | one to one to `fact_member_months`; the fact carries both the surrogate key `member_month_sk` (`person_id \|\| '\|' \|\| year_month`) and the natural key `(person_id, year_month)`. The Dash app joins on the natural key, so only the benchmark elements depend on the new fact |
| `semantic_layer.fact_benchmark_aco_quarter` | one row per ACO, performance year and reported quarter | to the member-month fact on `aco_id` and `performance_year`; the row flagged `is_current_projection` is the one each year's member rates were read from |

Rate columns on `fact_member_month_benchmark`, each a PMPM for the
member-month:

- `flat_benchmark_pmpm` — the ACO's mean projected updated benchmark, the
  same on every member-month of the performance year.
- `enrollment_type_benchmark_pmpm` — the rate for the member's
  `enrollment_type`; NULL where no type resolved.
- `risk_adjusted_benchmark_pmpm` — the type rate scaled by the member's
  `risk_ratio` (CMS prospective HCC score over the BY3 type score),
  uncapped; NULL where the member has no `risk_score`.
- `risk_adjusted_benchmark_pmpm_capped` — the same under the ACO's
  aggregate cap: the uncapped rate times the year's `cap_factor`.

Each rate has a `variance_to_*` column (`total_paid` minus the rate, so
positive means spending above benchmark), and every row carries the
delivery it came from (`benchmark_period`, `benchmark_submission_id`,
`is_agreement_defaulted`). A rate is NULL where the fact could not compute
it, so a report aggregating a rate should count member-months over the
rows where that rate is present — the dashboard's tables show that count
as "Excluded MM" and compute the actual PMPM it compares against over the
same member-months.

`fact_benchmark_aco_quarter` carries the ACO-level view: benchmark and
expenditure PMPM (`mean_projected_updated_benchmark_pmpm`,
`aco_expenditure_per_capita_pmpm`), `projected_savings_percentage`,
`estimated_msr` with `msr_basis_applied`, `savings_status`
(`above_msr` / `below_msr` / `no_savings`), the `aggregate_risk_ratio`
against `cap_upper_bound`, `cap_factor`, `is_cap_binding` (the cap is
one-sided: it binds only when the aggregate ratio exceeds the bound), and
`risk_adjusted_benchmark_pmpm`. The `*_scenario` columns are a labelled
projection of the cap with a national growth term and are not used by the
dashboard. Filter on `is_current_projection` for one row per year.

#### Benchmark controls

Three controls above the dashboard's tabs govern the Program Performance
KPI row, the benchmark KPI row, the practice and provider rollups and
bars, and the ACO projections panel. The headline row (attributed members,
member months, total paid, PMPM, risk) reads the same member-months as the
benchmark comparison, so it and the caption below never disagree on the
count; quality is the programme-wide figure.

- **Benchmark rate** — which of the four rate columns actual PMPM is set
  against. The tables count member-months without the selected rate as
  "Excluded MM" and compute actual PMPM over the covered member-months.
- **Assigned members only** (default on) — compares over the member-months
  the fact flags `is_assigned`, the beneficiaries the benchmark was built
  for; on that population the flat and enrollment-type rates agree by
  construction. Off, every member-month is compared, including
  non-assigned data-sharing members whose enrollment mix can differ from
  the ACO's, so switching rates then moves the variance for mix reasons
  rather than performance.
- **Performance year** — lists every year with a row in
  `fact_benchmark_aco_quarter`, defaulting to the latest. It narrows the
  member-months to that calendar year and the projections panel to that
  year's current-projection card; a year without one shows an alert.

#### Risk scores

The dashboard's risk figures are the CMS prospective HCC scores from the
assignment list, read from `fact_member_month_benchmark`: `risk_score` is
the score the risk-adjusted rates use, `by3_enrollment_type_risk_score` is
the BY3 CMS-HCC score for the member's enrollment type, and `risk_ratio` is
the first over the second. The headline "Avg CMS Risk Score" card is the
member-month-weighted mean score over the scored member-months of the
selected population, with the mean ratio and the scored count as its
subtitle; "Avg Benchmark Risk Score" beside it is the mean BY3 score over
the same member-months, so the pair reads as the performance-year score
against the benchmark-year score. The practice and provider tables show
the CMS score as "Avg CMS Risk".

Tuva's `normalized_risk_score` on `fact_member_months` is a CMS-HCC
MA-model score attached by diagnosis-collection month and normalized with
a payment-year factor; no benchmark rate uses it, and it is NULL for the
latest year until the next payment year's factor is in the Tuva seed. It
stays in the queries and appears as the last table column, "Avg Risk
(Tuva)". Without the benchmark fact the headline card falls back to it,
labelled "Avg Normalized Risk (Tuva)".

The caption under each rollup table states the population and year in
force, e.g. "Assigned members, PY2026, 8 member-months; 2 excluded for
lacking the enrollment type rate.", so a screenshot is self-describing.

To extend the Power BI MSSP ACO model the same way: import both tables,
relate `fact_member_month_benchmark` to `fact_member_months` one to one
(on `member_month_sk` where the semantic layer carries it, otherwise on
`person_id` and `year_month`), write the benchmark
PMPM measures as `SUM(rate) / SUM(member_months)` filtered to rows where
the rate is not blank, and read the ACO card from the
`is_current_projection` rows of `fact_benchmark_aco_quarter`.

## Running the unified shell (recommended)

For demos and exploration, run the Tuva-branded shell that hosts every
dashboard under one URL:

```bash
python -m dashboards
```

Defaults to http://127.0.0.1:8050 — a home page lists every dashboard,
the navbar lets you jump between them, and each route has a deep link:

The Dash apps can display member-level healthcare data. Keep `DASH_HOST` set
to `127.0.0.1` and `DASH_DEBUG=false` unless the app is behind your normal
authentication and network controls.

| Route | Dashboard |
| --- | --- |
| `/` | Home (catalog of dashboards) |
| `/cost-and-utilization` | Cost & Utilization |
| `/cost-drivers` | Cost Drivers |
| `/dqi-analytics` | DQI Analytics |
| `/mssp-aco` | MSSP ACO Performance |
| `/population-health` | Population Health |
| `/quality-measures` | Quality Measures |
| `/risk-adjusted-benchmarks` | Risk-Adjusted Benchmarks |
| `/semantic-layer` | Semantic Layer |

Branding (logo and palette) is sourced from the Power BI theme files,
so the Dash shell visually matches the PBI gallery.

## Running a single dashboard standalone

For development of a single dashboard, run it on its own:

```bash
python -m dashboards.dqi_analytics
python -m dashboards.risk_adjust_benchmark
python -m dashboards.cost_and_utilization
# ...etc
```

Each app starts a local Dash server (defaults to http://127.0.0.1:8050).
Override host/port via `DASH_HOST` / `DASH_PORT` in `.env`.

### Running without warehouse credentials

Set `LOAD_DATA=false` in `.env`. Apps will open with empty frames matching the
expected schema, exactly as the PBI files do when their `load_data` parameter
is false.

### Tests

The tests under `tests/` build a small synthetic DuckDB in a temp directory
and run the dashboard query and aggregation functions against it; no
warehouse or credentials are needed.

```bash
# from the python_dash/ directory, in the venv
pip install pytest
pytest
```

## Adding a new dashboard

1. Create a new package under `dashboards/<name>/`.
2. Add a `queries.py` (SQL strings + a `load_*` function per table).
3. Add a `layout.py` returning a Dash component.
4. Add a `__main__.py` that wires layout + callbacks to a Dash app and calls
   `app.run_server(...)`.
5. The shared lib (`tuva_dash.db.run_query`, `tuva_dash.theme.make_app`,
   `tuva_dash.components.kpi_card`) handles the common plumbing.

## Mapping to Power BI dashboards

| Power BI file | Dash app |
| --- | --- |
| `power_bi/dqi_analytics/` | `dashboards/dqi_analytics/` |
| `power_bi/risk_adjust_benchmark/` | `dashboards/risk_adjust_benchmark/` |
| `power_bi/cost_and_utilization/` | `dashboards/cost_and_utilization/` |
| `power_bi/cost_drivers/` | `dashboards/cost_drivers/` |
| `power_bi/mssp_aco_dashboard/` | `dashboards/mssp_aco_dashboard/` |
| `power_bi/population_health/` | `dashboards/population_health/` |
| `power_bi/quality_measures/` | `dashboards/quality_measures/` |
| `power_bi/semantic_layer/` | `dashboards/semantic_layer/` |
