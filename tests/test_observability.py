from __future__ import annotations

import json
import logging
from http.client import HTTPConnection

from prometheus_client import generate_latest

from hotflow.config import HotflowConfig, load_config
from hotflow.monitoring.alerts import AlertKind, AlertRouter
from hotflow.monitoring.health import HealthState
from hotflow.monitoring.http import make_handler, start_metrics_server, stop_metrics_server
from hotflow.monitoring.json_logs import JsonLogger
from hotflow.monitoring.metrics import REQUIRED_METRIC_NAMES, MetricsRegistry
from hotflow.monitoring.observer import Observability
from hotflow.monitoring.redact import REDACTED, is_secret_key, redact
from hotflow.pipeline import PaperPipeline, demo_market
from hotflow.risk.kill_switch import KillSwitchBoard
from hotflow.types import KillSwitchReason


def test_redact_secrets_and_keep_public_ids() -> None:
    payload = {
        "market_id": "0xabc",
        "token_id": "public-clob-token",
        "api_key": "sk-live-should-hide",
        "POLY_API_SECRET": "topsecret",
        "authorization": "Bearer eyJhbGciOiJIUzI1NiJ9.aaa.bbb",
        "nested": {"private_key": "-----BEGIN PRIVATE KEY-----\nMIIB\n-----END PRIVATE KEY-----"},
        "list": [{"passphrase": "hidden"}, {"side": "BUY"}],
        "note": "plain text",
    }
    cleaned = redact(payload)
    assert cleaned["market_id"] == "0xabc"
    assert cleaned["token_id"] == "public-clob-token"
    assert cleaned["api_key"] == REDACTED
    assert cleaned["POLY_API_SECRET"] == REDACTED
    assert cleaned["authorization"] == REDACTED
    assert cleaned["nested"]["private_key"] == REDACTED
    assert cleaned["list"][0]["passphrase"] == REDACTED
    assert cleaned["list"][1]["side"] == "BUY"
    assert cleaned["note"] == "plain text"
    assert is_secret_key("token_id") is False
    assert is_secret_key("moonshot_api_key") is True
    pem = redact("-----BEGIN EC PRIVATE KEY-----\nxyz\n-----END EC PRIVATE KEY-----")
    assert pem == REDACTED


def test_json_logger_fields_are_redacted(caplog) -> None:
    caplog.set_level(logging.INFO, logger="hotflow")
    log = JsonLogger("hotflow")
    log.signal(
        market_id="m1",
        decision="SKIP",
        reason="EDGE_TOO_SMALL",
        accepted=False,
        mode="paper",
        session_id="s1",
        hms=40.0,
        net_edge=0.01,
        opportunity_score=0.2,
        latency_ms=1.5,
        api_key="should-not-appear",
    )
    log.trade(
        market_id="m1",
        status="FILLED",
        side="BUY",
        size=10,
        price=0.4,
        filled_size=5,
        fill_ratio=0.5,
        fees=0.01,
        slippage=0.0,
        client_order_id="cid",
        mode="paper",
        private_key="0xdead",
    )
    log.risk_decision(
        market_id="m1",
        allowed=False,
        reason="KILL_SWITCH",
        veto=True,
        kill_switch=True,
        exposure=10.0,
        drawdown=0.02,
        mode="paper",
    )
    log.request(request_id="r1", method="GET", path="/health", status=200, latency_ms=0.4)
    bodies = [json.loads(rec.message) for rec in caplog.records if rec.message.startswith("{")]
    events = {item["event"] for item in bodies}
    assert {"signal", "trade", "risk_decision", "request"} <= events
    blob = " ".join(rec.message for rec in caplog.records)
    assert "should-not-appear" not in blob
    assert "0xdead" not in blob
    assert REDACTED in blob


def test_metric_registration_and_hooks() -> None:
    metrics = MetricsRegistry()
    names = metrics.registered_names()
    missing = [name for name in REQUIRED_METRIC_NAMES if name not in names]
    assert missing == []
    metrics.signals.labels(decision="TRADE", reason="OK").inc()
    metrics.note_closed_trade(1.5)
    metrics.note_closed_trade(-0.5)
    metrics.note_fill_attempt(filled=True, fill_ratio=0.55, style="TAKER")
    metrics.signal_latency.observe(0.02)
    metrics.order_latency.observe(0.01)
    text = generate_latest(metrics.registry).decode()
    assert "hotflow_signals_total" in text
    assert "hotflow_signal_latency_seconds_bucket" in text
    assert "hotflow_win_rate" in text
    assert metrics._wins == 1
    assert abs(metrics._pnl_sum - 1.0) < 1e-9


def test_health_and_ready_handlers() -> None:
    metrics = MetricsRegistry()
    health = HealthState(mode="paper")
    handler = make_handler(metrics.registry, health)
    server = start_metrics_server(bind="127.0.0.1", port=0, registry=metrics.registry, health=health)
    try:
        host, port = server.server_address[:2]
        conn = HTTPConnection(host, port, timeout=2)
        conn.request("GET", "/health")
        health_resp = conn.getresponse()
        health_body = json.loads(health_resp.read().decode())
        assert health_resp.status == 200
        assert health_body["mode"] == "paper"
        assert health_body["ready"] is True
        assert "api_key" not in health_body
        conn.request("GET", "/ready")
        ready_resp = conn.getresponse()
        assert ready_resp.status == 200
        ready_resp.read()
        conn.request("GET", "/metrics")
        metrics_resp = conn.getresponse()
        body = metrics_resp.read().decode()
        assert metrics_resp.status == 200
        assert "hotflow_kill_switch" in body
        health.kill_switch = True
        health.kill_reason = "MANUAL"
        conn.request("GET", "/ready")
        dead = conn.getresponse()
        assert dead.status == 503
        dead.read()
        conn.close()
        # handler class is constructible
        assert handler is not None
    finally:
        stop_metrics_server(server)


def test_alerts_redact_and_callback() -> None:
    seen: list[str] = []
    router = AlertRouter(callbacks=[lambda alert: seen.append(alert.kind.value)])
    alert = router.emit(
        AlertKind.AUTH_FAILURE,
        "l2 auth failed",
        api_key="super-secret",
        private_key="-----BEGIN PRIVATE KEY-----\nX\n-----END PRIVATE KEY-----",
        market_id="m-public",
    )
    assert alert.fields["api_key"] == REDACTED
    assert alert.fields["private_key"] == REDACTED
    assert alert.fields["market_id"] == "m-public"
    assert "super-secret" not in json.dumps(alert.as_dict())
    assert seen == [AlertKind.AUTH_FAILURE.value]


def test_kill_switch_and_restart_alerts() -> None:
    cfg = HotflowConfig()
    obs = Observability.from_config(cfg, announce_restart=True)
    assert any(item.kind is AlertKind.PROCESS_RESTART for item in obs.alerts.emitted)
    board = KillSwitchBoard(on_trip=obs.on_kill_event)
    board.trip(KillSwitchReason.AUTH_FAIL, "fixture")
    kinds = {item.kind for item in obs.alerts.emitted}
    assert AlertKind.KILL_SWITCH in kinds
    assert AlertKind.AUTH_FAILURE in kinds
    assert obs.health.kill_switch is True
    assert obs.health.ready is False


def test_pipeline_records_metrics_without_changing_paper_default() -> None:
    cfg = load_config("configs/default.yaml")
    assert cfg.trading.mode == "paper"
    assert cfg.monitoring.http_enabled is False
    obs = Observability.from_config(cfg)
    pipe = PaperPipeline(cfg, obs=obs)
    result = pipe.evaluate_market(demo_market(hot=True), p_info=0.70)
    assert result["accepted"] is True
    obs.snapshot_pipeline(pipe)
    text = generate_latest(obs.metrics.registry).decode()
    assert "hotflow_signals_total" in text
    assert 'decision="TRADE"' in text
    assert "hotflow_orders_total" in text
    assert "hotflow_signal_latency_seconds" in text
    assert cfg.trading.mode == "paper"


def test_drawdown_and_position_mismatch_hooks() -> None:
    obs = Observability(HotflowConfig())
    obs.set_equity_pnl(drawdown=0.09)
    obs.alert(AlertKind.POSITION_MISMATCH, "book vs local", market_id="m1")
    kinds = {item.kind for item in obs.alerts.emitted}
    assert AlertKind.DRAWDOWN in kinds
    assert AlertKind.POSITION_MISMATCH in kinds
