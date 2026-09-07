"""Parte 59 shadow-gate checks: completeness, no submits, stale skip, soak."""

from datetime import UTC, datetime, timedelta

from prometheus_client import generate_latest
from typer.testing import CliRunner

from hotflow.backtest.shadow import (
    SHADOW_REQUIRED_FIELDS,
    ShadowSession,
    compare_shadow_vs_paper,
    run_shadow,
    run_stale_probe,
    shadow_completeness,
)
from hotflow.cli import app
from hotflow.config import load_config
from hotflow.execution.live_gate import live_gates_open
from hotflow.pipeline import PaperPipeline, demo_market
from hotflow.portfolio.session import mock_markets
from hotflow.reason_codes import ReasonCode


def _cfg():
    cfg = load_config("configs/default.yaml")
    cfg.risk.cooldown_ms = 0
    cfg.risk.cooldown_after_losses_ms = 0
    return cfg


def test_default_still_paper_not_live() -> None:
    cfg = load_config("configs/default.yaml")
    assert cfg.trading.mode == "paper"
    assert live_gates_open(cfg) is False


def test_shadow_intent_and_reject_rows_are_complete() -> None:
    cfg = _cfg()
    pipe = PaperPipeline(cfg)
    hot = run_shadow(cfg, [demo_market(hot=True)], p_info=0.70, pipeline=pipe)
    cold = demo_market(hot=False)
    cold.market_id = "demo-cold"
    skipped = run_shadow(cfg, [cold], pipeline=pipe)
    assert hot[0]["reason"] == ReasonCode.SHADOW_MODE
    assert hot[0]["would_buy"] is True
    assert hot[0]["simulated_fill"]["sent"] is False
    assert skipped[0]["would_buy"] is False
    assert skipped[0]["would_sell"] is False
    assert skipped[0]["reason"]
    for row in (*hot, *skipped):
        ok, missing = shadow_completeness(row)
        assert ok, missing
        for key in SHADOW_REQUIRED_FIELDS:
            assert key in row


def test_stale_feed_blocks_would_intent() -> None:
    cfg = _cfg()
    session = ShadowSession(cfg, use_twap_fixtures=True)
    first = session.run_cycle([demo_market(hot=True)], p_info=0.70)
    assert first[0]["would_buy"] is True
    aged = demo_market(hot=True)
    aged.market_id = "shadow-aged"
    aged.book.fetched_at = datetime.now(UTC) - timedelta(seconds=90)  # type: ignore[union-attr]
    session.pipe.clock.touch("clob_book", observed_at=datetime.now(UTC) - timedelta(seconds=90))
    stale = session.run_cycle([aged], p_info=0.70)[0]
    assert stale["accepted"] is False
    assert stale["reason"] in {ReasonCode.STALE_DATA, ReasonCode.KILL_SWITCH}
    assert stale["would_buy"] is False
    assert stale["would_sell"] is False
    assert stale["simulated_fill"]["sent"] is False
    assert session.pipe.broker.orders == {}


def test_stale_probe_and_metrics() -> None:
    cfg = _cfg()
    session = ShadowSession(cfg, use_twap_fixtures=True)
    session.run_cycle(mock_markets()[:2])
    probe = run_stale_probe(session)
    assert probe["blocked"] is True
    assert probe["would_buy"] is False
    assert probe["would_sell"] is False
    assert probe["simulated_fill_sent"] is False
    text = generate_latest(session.obs.metrics.registry).decode()
    assert "hotflow_shadow_decisions_total" in text
    assert session.pipe.broker.orders == {}


def test_multi_cycle_soak_completeness_and_backfill() -> None:
    cfg = _cfg()
    session = ShadowSession(cfg, use_twap_fixtures=True)
    markets = mock_markets()
    for _ in range(2):
        session.run_cycle(markets)
    report = session.report()
    assert report["mode"] == "shadow"
    assert report["sent_orders"] is False
    assert report["cycle_count"] == 2
    assert report["broker_order_count"] == 0
    assert report["completeness"]["incomplete"] == 0
    assert report["gates"]["signal_logging_complete"] is True
    assert report["gates"]["no_orders_sent"] is True
    first = report["cycles"][0]["results"]
    later_mids = session.cycle_marks[1]
    for row in first:
        mid = later_mids.get(str(row["market_id"]))
        if mid is not None:
            assert row["actual_price_after_signal"] == mid


def test_compare_shadow_vs_paper_same_fixtures() -> None:
    cfg = _cfg()
    comparison = compare_shadow_vs_paper(cfg, [demo_market(hot=True)], p_info=0.70)
    assert comparison["live_edge_claimed"] is False
    assert comparison["shadow_orders"] == 0
    assert comparison["paper_orders"] >= 1
    pair = comparison["pairs"][0]
    assert pair["agree"] is True
    assert pair["kind"] == "paper_fill_vs_shadow_intent"
    assert pair["would_buy"] is True
    assert pair["shadow_sent"] is False


def test_cli_shadow_soak(tmp_path) -> None:
    out = tmp_path / "shadow-soak.json"
    result = CliRunner().invoke(
        app,
        ["shadow-soak", "--cycles", "2", "--out", str(out)],
    )
    assert result.exit_code == 0, result.output
    assert "sent_orders=0" in result.output
    import json

    body = json.loads(out.read_text(encoding="utf-8"))
    assert body["mode"] == "shadow"
    assert body["sent_orders"] is False
    assert body["cycle_count"] == 2
    assert body["completeness"]["incomplete"] == 0
    assert body["stale_probe"]["blocked"] is True
    assert body["stale_probe"]["would_buy"] is False
    assert body["comparison"]["live_edge_claimed"] is False
    assert body["comparison"]["shadow_orders"] == 0
    assert body["gates"]["simulated_fills_unsent"] is True
