# Tuva Project Analytics Gallery Repository

Welcome to the Tuva Project Analytics Gallery repository! This repository contains files for visualizations that showcase the core open-source data model of [The Tuva Project](https://thetuvaproject.com/).

## Repository Contents

This repository includes:

- [`power_bi/`](power_bi/) — Power BI `.pbip` and `.pbit` files. Explore the hosted examples on the [Dashboards page in the Tuva docs](https://thetuvaproject.com/dashboards).
- `python_dash/` — Python [Dash](https://dash.plotly.com/) equivalents of the same dashboards, for users who want to run Tuva locally without installing Power BI Desktop. See [`python_dash/README.md`](python_dash/README.md) for setup.

## Getting Started — Power BI

1. Clone this repository or download the .pbip files directly.
2. Ensure you have [Power BI Desktop](https://www.microsoft.com/en-us/microsoft-fabric/features/power-bi/desktop) installed on your computer.
3. Open the .pbip files using Power BI Desktop to explore the dashboards and their underlying structure.
4. Change the parameter **load_data** to true and update the rest of the parameters with your database and account information.

## Getting Started — Python Dash

See [`python_dash/README.md`](python_dash/README.md) for venv setup, warehouse driver selection, and per-dashboard run commands.

## Contributing

We welcome contributions to this repository! If you have created interesting visualizations using The Tuva Project's data model, please feel free to submit a pull request.
