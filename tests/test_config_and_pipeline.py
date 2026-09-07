from pathlib import Path

from hotflow.config import load_config
from hotflow.execution.live_gate import LiveGateError, assert_live_allowed, live_gates_open
from hotflow.official import RTDS_TWAP_WINDOWS
from hotflow.pipeline import PaperPipeline, demo_market
from hotflow.reason_codes import ReasonCode
from hotflow.strategies.crypto import CryptoStrategy


def test_default_mode_is_paper() -> None:
    cfg = load_config(Path("configs/default.yaml"))
    assert cfg.trading.mode == "paper"
    assert cfg.is_paper
    assert live_gates_open(cfg) is False


def test_live_gates_require_env_and_yaml(monkeypatch) -> None:
    cfg = load_config(Path("configs/default.yaml"))
    cfg.trading.mode = "live"
    cfg.live.accept_live_trading = True
    cfg.live.accept_capital_at_risk = True
    cfg.live.i_understand_orders_are_real = True
    monkeypatch.delenv("HOTFLOW_ACCEPT_LIVE", raising=False)
    assert live_gates_open(cfg) is False
    monkeypatch.setenv("HOTFLOW_ACCEPT_LIVE", "1")
    assert live_gates_open(cfg) is True
    monkeypatch.setenv("HOTFLOW_ACCEPT_LIVE", "0")
    try:
        assert_live_allowed(cfg)
        raise AssertionError("gate should block")
    except LiveGateError:
        pass


def test_pipeline_accepts_fixture_edge() -> None:
    pipe = PaperPipeline(load_config(Path("configs/default.yaml")))
    result = pipe.evaluate_market(demo_market(hot=True), p_info=0.70)
    assert result["accepted"] is True
    assert result["reason"] == ReasonCode.OK
    assert any(a.accepted for a in pipe.audits)


def test_pipeline_rejects_cold() -> None:
    pipe = PaperPipeline(load_config(Path("configs/default.yaml")))
    result = pipe.evaluate_market(demo_market(hot=False), p_info=0.90)
    assert result["accepted"] is False
    assert result["reason"] in {ReasonCode.MARKET_NOT_HOT, ReasonCode.EDGE_TOO_SMALL, ReasonCode.NO_BOOK}


def test_crypto_twap_window_official_only() -> None:
    CryptoStrategy(60)
    try:
        CryptoStrategy(45)
        raise AssertionError("45s TWAP is not official")
    except ValueError:
        pass
    assert RTDS_TWAP_WINDOWS == frozenset({30, 60})


def test_ws_heartbeat_intervals() -> None:
    from hotflow.marketdata.websocket import MARKET_HEARTBEAT, RTDS_HEARTBEAT

    assert MARKET_HEARTBEAT.ping_interval_s == 10
    assert RTDS_HEARTBEAT.ping_interval_s == 5


def test_ws_reconnect_backoff() -> None:
    import asyncio

    from hotflow.marketdata.websocket import MARKET_HEARTBEAT, ReconnectingWebSocket

    ws = ReconnectingWebSocket(MARKET_HEARTBEAT)
    assert ws.backoff_s(0) == 0.5
    assert ws.backoff_s(10) == 30.0

    async def _run() -> None:
        await ws.connect()
        await ws.handle_disconnect()
        assert ws.reconnect_attempts == 1
        assert ws.connected

    asyncio.run(_run())
