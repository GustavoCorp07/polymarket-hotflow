from __future__ import annotations

import json
from http.client import HTTPConnection
from pathlib import Path

from typer.testing import CliRunner

from hotflow.cli import app
from hotflow.config import HotflowConfig, load_config
from hotflow.monitoring.dashboard import DashboardHub, decision_row, idle_snapshot, load_dashboard_html
from hotflow.monitoring.health import HealthState
from hotflow.monitoring.http import make_handler, start_metrics_server, stop_metrics_server
from hotflow.monitoring.metrics import MetricsRegistry
from hotflow.monitoring.observer import Observability
from hotflow.pipeline import PaperPipeline, demo_market
from hotflow.portfolio.session import PaperSession, mock_markets


def test_dashboard_html_loads_without_secrets() -> None:
    html = load_dashboard_html()
    assert "<!DOCTYPE html>" in html
    assert "HOTFLOW" in html
    assert "PAPER" in html
    assert "/api/state" in html
    assert "/events" in html
    assert "api_key" not in html
    assert "PRIVATE KEY" not in html
    assert "HOTFLOW_ACCEPT_LIVE" not in html


def test_dashboard_http_handlers_and_html_smoke() -> None:
    metrics = MetricsRegistry()
    health = HealthState(mode="paper")
    hub = DashboardHub(health)
    hub.note_decision(
        {
            "accepted": False,
            "reason": "EDGE_TOO_SMALL",
            "market_id": "demo-skip",
            "signal": {
                "reason_codes": ["EDGE_TOO_SMALL", "SPREAD_TOO_LARGE"],
                "spread_regime": "wide",
            },
        }
    )
    handler = make_handler(metrics.registry, health, hub=hub)
    server = start_metrics_server(
        bind="127.0.0.1",
        port=0,
        registry=metrics.registry,
        health=health,
        hub=hub,
    )
    try:
        host, port = server.server_address[:2]
        conn = HTTPConnection(host, port, timeout=3)
        conn.request("GET", "/")
        page = conn.getresponse()
        html = page.read().decode()
        assert page.status == 200
        assert "text/html" in page.getheader("Content-Type", "")
        assert "HOTFLOW" in html
        assert "PAPER" in html
        assert "sk-live" not in html

        conn.request("GET", "/api/state")
        state_resp = conn.getresponse()
        state = json.loads(state_resp.read().decode())
        assert state_resp.status == 200
        assert state["mode"] == "paper"
        assert state["paper_only"] is True
        assert state["live_transmit"] is False
        assert state["live_gates"]["closed"] is True
        assert state["ledger"]["origin"] == "paper_ledger"
        assert state["recent"][0]["reason"] == "EDGE_TOO_SMALL"
        assert "SPREAD_TOO_LARGE" in state["recent"][0]["reason_codes"]
        assert state["recent"][0]["spread_regime"] == "wide"
        assert "api_key" not in json.dumps(state)

        conn.request("GET", "/health")
        health_resp = conn.getresponse()
        assert health_resp.status == 200
        health_resp.read()

        conn.request("GET", "/metrics")
        metrics_resp = conn.getresponse()
        body = metrics_resp.read().decode()
        assert metrics_resp.status == 200
        assert "hotflow_kill_switch" in body

        conn.request("GET", "/events")
        events = conn.getresponse()
        assert events.status == 200
        assert "text/event-stream" in events.getheader("Content-Type", "")
        if conn.sock is not None:
            conn.sock.settimeout(2.0)
        chunk = events.fp.read(256)
        assert b"data:" in chunk
        conn.close()
        assert handler is not None
    finally:
        stop_metrics_server(server)


def test_dashboard_state_follows_paper_ledger() -> None:
    cfg = load_config("configs/default.yaml")
    assert cfg.trading.mode == "paper"
    obs = Observability.from_config(cfg)
    session = PaperSession(cfg, obs=obs, use_twap_fixtures=True)
    session.run_markets(mock_markets())
    snap = obs.dashboard.snapshot()
    assert snap["mode"] == "paper"
    assert snap["ledger"]["equity"] is not None
    assert snap["ledger"]["origin"] == "paper_ledger"
    assert snap["open_positions"] >= 0
    assert snap["cycle_count"] >= 1
    assert snap["recent"]
    decisions = {row["decision"] for row in snap["recent"]}
    assert decisions <= {"TRADE", "SKIP", "SHADOW"}
    assert any(row.get("reason") for row in snap["recent"])
    assert snap["live_gates"]["closed"] is True
    assert snap["kill_switch"]["tripped"] in {True, False}


def test_idle_snapshot_does_not_invent_venue_pnl() -> None:
    health = HealthState(mode="paper")
    body = idle_snapshot(health)
    assert body["ledger"]["equity"] is None
    assert body["ledger"]["realized_pnl"] is None
    assert "venue" in body["ledger"]["note"]
    row = decision_row({"accepted": True, "reason": "OK", "market_id": "m1"})
    assert row["decision"] == "TRADE"
    assert row["reason_codes"] == ["OK"]


def test_dashboard_cli_mock_no_hold(tmp_path: Path) -> None:
    out = tmp_path / "dash.json"
    result = CliRunner().invoke(
        app,
        ["dashboard", "--mock", "--no-hold", "--cycles", "1", "--port", "0", "--out", str(out)],
    )
    assert result.exit_code == 0, result.output
    assert "dashboard http://" in result.output
    assert out.is_file()
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload.get("mode") == "paper"


def test_dashboard_refuses_live_mode(tmp_path: Path) -> None:
    cfg_path = tmp_path / "live.yaml"
    cfg_path.write_text("trading:\n  mode: live\n", encoding="utf-8")
    result = CliRunner().invoke(app, ["dashboard", "--mock", "--no-hold", "--config", str(cfg_path)])
    assert result.exit_code != 0
    assert "LIVE" in (result.output or result.stderr or "")


def test_ci_local_script_mirrors_workflow() -> None:
    script = Path("scripts/ci_local.sh").read_text(encoding="utf-8")
    for needle in (
        "ruff check src tests scripts",
        "mypy src/hotflow",
        "pytest -q",
        "paper-run --mock",
        "NullBacktester",
        "PRIVATE KEY",
    ):
        assert needle in script
    workflow = Path(".github/workflows/ci.yml").read_text(encoding="utf-8")
    assert "billing lock" in workflow.lower() or "billing-locked" in workflow
    assert "workflow_dispatch" in workflow
    assert "if: false" in workflow
    assert "self-hosted" in workflow
    assert Path(".gitlab-ci.yml").is_file()
    assert "make ci" in Path(".gitlab-ci.yml").read_text(encoding="utf-8")
    assert Path("Makefile").read_text(encoding="utf-8").startswith("# Default source of truth")


def test_pipeline_still_paper_default_with_dashboard_hub() -> None:
    cfg = HotflowConfig()
    pipe = PaperPipeline(cfg, obs=Observability.from_config(cfg))
    result = pipe.evaluate_market(demo_market(hot=True), p_info=0.70)
    assert result["accepted"] is True
    snap = pipe.obs.dashboard.snapshot()
    assert snap["recent"][0]["decision"] == "TRADE"
    assert snap["mode"] == "paper"
