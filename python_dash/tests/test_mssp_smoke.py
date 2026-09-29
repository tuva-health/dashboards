"""Headless smoke test: the MSSP dashboard served through Dash's Flask app.

Builds one Dash app for the session (Dash hands the module-level callbacks
to the first app that starts), then for each data mode asks the Flask test
client for the layout and posts each callback the way the browser would.
"""

from __future__ import annotations

import pytest

from dashboards.mssp_aco_dashboard import layout
from tuva_dash.theme import make_app

# Sample values for every input the MSSP callbacks read.
INPUT_VALUES = {
    ("mssp-benchmark-rate", "value"): "enrollment_type",
    ("mssp-benchmark-assigned-only", "value"): True,
    ("mssp-benchmark-year", "value"): 2026,
    ("mssp-practice-select", "value"): "Practice A",
    ("mssp-provider-select", "value"): "Dr One",
    ("mssp-patient-select", "value"): "P1",
}


@pytest.fixture(scope="session")
def dash_app():
    return make_app("MSSP smoke")


def _mssp_callbacks(app):
    cbs = [cb for cb in app._callback_list if "mssp-" in cb["output"]]
    outputs = {cb["output"] for cb in cbs}
    assert {"mssp-program-kpis.children", "mssp-aco-panel.children",
            "mssp-practice-content.children"} <= outputs, outputs
    assert len(cbs) == 6, outputs
    return cbs


def _payload(cb: dict, overrides: dict | None = None) -> dict:
    values = {**INPUT_VALUES, **(overrides or {})}
    inputs = [
        {**i, "value": values[(i["id"], i["property"])]} for i in cb["inputs"]
    ]
    outputs = [
        {"id": part.split(".")[0], "property": part.split(".")[1]}
        for part in cb["output"].strip(".").split("...")
    ]
    return {
        "output": cb["output"],
        "outputs": outputs if len(outputs) > 1 else outputs[0],
        "inputs": inputs,
        "changedPropIds": [f"{inputs[0]['id']}.{inputs[0]['property']}"],
        "state": [],
    }


def _smoke(dash_app, overrides=None) -> None:
    dash_app.layout = layout.build_layout()
    client = dash_app.server.test_client()
    assert client.get("/").status_code == 200
    assert client.get("/_dash-layout").status_code == 200
    for cb in _mssp_callbacks(dash_app):
        resp = client.post("/_dash-update-component", json=_payload(cb, overrides))
        assert resp.status_code == 200, (cb["output"], resp.get_data(as_text=True)[:500])
        assert "response" in resp.get_json()


def test_smoke_with_benchmark_facts(dash_app, full_db):
    _smoke(dash_app)
    _smoke(dash_app, {("mssp-benchmark-assigned-only", "value"): False,
                      ("mssp-benchmark-year", "value"): 2025,
                      ("mssp-benchmark-rate", "value"): "risk_adjusted_capped"})
    _smoke(dash_app, {("mssp-benchmark-year", "value"): 2024})


def test_smoke_without_benchmark_facts(dash_app, no_benchmark_db):
    _smoke(dash_app, {("mssp-benchmark-year", "value"): None})


def test_smoke_with_legacy_member_months(dash_app, legacy_db):
    _smoke(dash_app)


def test_smoke_with_load_data_false(dash_app, no_load_data):
    _smoke(dash_app, {("mssp-benchmark-year", "value"): None})
