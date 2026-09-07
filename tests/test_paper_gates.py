"""Parte 59 paper-gate checks that still fit this pass."""

from datetime import UTC, datetime, timedelta

from hotflow.config import load_config
from hotflow.execution.live_gate import live_gates_open
from hotflow.pipeline import PaperPipeline, demo_market
from hotflow.portfolio.session import PaperSession, mock_markets
from hotflow.reason_codes import ReasonCode
from hotflow.types import KillSwitchReason, OrderStatus


def test_default_still_paper_and_live_closed() -> None:
    cfg = load_config("configs/default.yaml")
    assert cfg.trading.mode == "paper"
    assert live_gates_open(cfg) is False
    assert cfg.trading.paper_flatten_at_session_end is False


def test_accounting_on_accepted_paper_fill() -> None:
    cfg = load_config("configs/default.yaml")
    pipe = PaperPipeline(cfg)
    start = pipe.ledger.cash
    result = pipe.evaluate_market(demo_market(hot=True), p_info=0.70)
    assert result["accepted"] is True
    snap = pipe.ledger.snapshot()
    assert snap.cash < start
    assert snap.event_count >= 1
    assert snap.equity <= start + 1e-9
    assert "order" in result


def test_risk_and_staleness_still_block() -> None:
    cfg = load_config("configs/default.yaml")
    pipe = PaperPipeline(cfg)
    first = pipe.evaluate_market(demo_market(hot=True), p_info=0.70)
    assert first["accepted"] is True
    pipe.clock.touch("clob_book", observed_at=datetime.now(UTC) - timedelta(seconds=90))
    aged = demo_market(hot=True)
    aged.book.fetched_at = datetime.now(UTC) - timedelta(seconds=90)  # type: ignore[union-attr]
    stale = pipe.evaluate_market(aged, p_info=0.70)
    assert stale["reason"] == ReasonCode.STALE_DATA
    assert pipe.kills.tripped
    assert pipe.kills.reason is KillSwitchReason.STALE_CRITICAL_DATA
    for order in pipe.broker.orders.values():
        assert order.status in {OrderStatus.CANCELLED, OrderStatus.FILLED, OrderStatus.PARTIAL}


def test_multi_cycle_mock_smoke_and_metrics() -> None:
    cfg = load_config("configs/default.yaml")
    cfg.risk.cooldown_ms = 0
    cfg.risk.cooldown_after_losses_ms = 0
    session = PaperSession(cfg, use_twap_fixtures=True)
    for _ in range(2):
        session.run_markets(mock_markets())
    session.flatten()
    report = session.report()
    assert report["mode"] == "paper"
    assert report["cycle_count"] == 2
    accounting = report["accounting"]
    assert accounting["starting_cash"] == cfg.trading.paper_starting_cash
    assert accounting["event_count"] >= 1
    if accounting["closed_count"]:
        assert 0.0 <= accounting["win_rate"] <= 1.0
    session.obs.publish_ledger(session.ledger.snapshot())
    from prometheus_client import generate_latest

    text = generate_latest(session.obs.metrics.registry).decode()
    assert "hotflow_equity" in text
    assert "hotflow_realized_pnl" in text
    assert "hotflow_win_rate" in text
