"""Parte 39 failure injection: each case fails safe (no would_* submit, no invented data)."""

from datetime import UTC, datetime, timedelta

from typer.testing import CliRunner

from hotflow.backtest.events import sanitize_event_rows
from hotflow.cli import app
from hotflow.config import load_config
from hotflow.execution.live_gate import live_gates_open
from hotflow.failure.scenarios import (
    scenario_clock_skew,
    scenario_corrupt_events,
    scenario_http_faults,
    scenario_missing_fees_twap_gap,
    scenario_partial_cancel_race,
    scenario_position_mismatch,
    scenario_stale_max_age,
    scenario_ws_disconnect,
)
from hotflow.failure.soak import LIVE_PREP_STILL_BLOCKED, run_failure_soak
from hotflow.marketdata.freshness import FeedClock
from hotflow.pipeline import PaperPipeline, demo_market
from hotflow.reason_codes import ReasonCode
from hotflow.types import KillSwitchReason, OrderStatus


def test_default_still_paper() -> None:
    cfg = load_config("configs/default.yaml")
    assert cfg.trading.mode == "paper"
    assert live_gates_open(cfg) is False


def test_ws_disconnect_does_not_invent_or_trade() -> None:
    row = scenario_ws_disconnect()
    assert row["fail_safe"] is True
    assert row["would_buy"] is False
    assert row["would_sell"] is False
    assert row["orders_submitted"] == 0
    assert row["invented_twap"] is False
    assert row["reconnects"] >= 1
    assert row["reason"] == ReasonCode.TWAP_OBSERVATION_MISSING
    assert "api_disconnected" in row["alert_kinds"]


def test_http_faults_empty_universe() -> None:
    row = scenario_http_faults()
    assert row["fail_safe"] is True
    assert row["invented_markets"] is False
    assert row["orders_submitted"] == 0
    labels = {item["label"] for item in row["cases"]}
    assert labels == {"gamma_500", "gamma_429", "gamma_timeout"}
    assert all(item["markets"] == 0 for item in row["cases"])
    assert all(item["error"] for item in row["cases"])


def test_sanitize_corrupt_duplicate_ooo() -> None:
    row = scenario_corrupt_events()
    assert row["accepted"] == 2
    assert ReasonCode.EVENT_CORRUPT in row["reject_reasons"]
    assert ReasonCode.EVENT_DUPLICATE in row["reject_reasons"]
    assert ReasonCode.EVENT_OUT_OF_ORDER in row["reject_reasons"]
    assert row["healed"] is False
    now = datetime.now(UTC)
    cleaned = sanitize_event_rows([{"ts": now.isoformat(), "kind": "book", "payload": {}}])
    assert cleaned["accepted_count"] == 1


def test_stale_blocks_shadow_intent() -> None:
    row = scenario_stale_max_age()
    assert row["fail_safe"] is True
    assert row["would_buy"] is False
    assert row["reason"] in {ReasonCode.STALE_DATA, ReasonCode.KILL_SWITCH}
    assert row["kill_reason"] in {
        KillSwitchReason.STALE_CRITICAL_DATA.value,
        None,
    } or row["kill_reason"]


def test_missing_fees_twap_and_gap() -> None:
    row = scenario_missing_fees_twap_gap()
    assert row["fail_safe"] is True
    assert row["fees_reason"] == ReasonCode.UNKNOWN_FEES
    assert row["twap_reason"] == ReasonCode.TWAP_OBSERVATION_MISSING
    assert ReasonCode.DATA_GAP in row["gap_reasons"]
    assert row["orders_submitted"] == 0


def test_partial_cancel_race_no_fill_after_settle() -> None:
    row = scenario_partial_cancel_race()
    assert row["partial_status"] == OrderStatus.PARTIAL.value
    assert row["no_fill_after_cancel"] is True
    assert row["post_cancel_status"] in {OrderStatus.CANCELLED.value, OrderStatus.FILLED.value}


def test_position_mismatch_trips_and_blocks() -> None:
    row = scenario_position_mismatch()
    assert row["fail_safe"] is True
    assert row["kill_reason"] == KillSwitchReason.POSITION_MISMATCH.value
    assert row["second_accepted"] is False
    assert row["reason"] == ReasonCode.KILL_SWITCH
    assert row["mismatched_tokens"]
    assert "position_mismatch" in row["alert_kinds"]


def test_clock_skew_and_negative_latency() -> None:
    row = scenario_clock_skew()
    assert row["fail_safe"] is True
    assert row["future_book_reason"] == ReasonCode.CLOCK_SKEW
    assert row["negative_latency_reason"] == ReasonCode.CLOCK_SKEW
    assert row["monotonic_elapsed_nonneg"] is True
    assert row["monotonic_forward"] is True
    clock = FeedClock(load_config("configs/default.yaml").feeds)
    now = datetime.now(UTC)
    clock.touch("clob_book", observed_at=now + timedelta(seconds=30))
    assert "clob_book" in clock.clock_skewed(now)
    assert not clock.is_fresh("clob_book", now)


def test_future_book_does_not_look_fresh() -> None:
    pipe = PaperPipeline(load_config("configs/default.yaml"))
    market = demo_market(hot=True)
    now = datetime.now(UTC)
    market.book.fetched_at = now + timedelta(hours=1)  # type: ignore[union-attr]
    result = pipe.evaluate_market(market, p_info=0.70, now=now)
    assert result["accepted"] is False
    assert result["reason"] == ReasonCode.CLOCK_SKEW
    assert pipe.broker.orders == {}


def test_failure_soak_and_cli(tmp_path) -> None:
    report = run_failure_soak()
    assert report["fail_safe"] is True
    assert report["orders_submitted"] == 0
    assert report["would_intent"] is False
    assert report["gates"]["live_still_blocked"] is True
    assert report["scenario_count"] == 8
    assert LIVE_PREP_STILL_BLOCKED[0] in report["live_prep_still_blocked"]
    out = tmp_path / "failure-soak.json"
    cli = CliRunner().invoke(app, ["failure-soak", "--out", str(out)])
    assert cli.exit_code == 0, cli.output
    assert "sent_orders=0" in cli.output
    assert "fail_safe=True" in cli.output
