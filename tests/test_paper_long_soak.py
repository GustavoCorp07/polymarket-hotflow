"""Long labeled paper soak: ≥50 explicit closes, MARK between, no invented PnL."""

from __future__ import annotations

import json

from typer.testing import CliRunner

from hotflow.analytics.review import build_review
from hotflow.analytics.trades import extract_trades
from hotflow.cli import app
from hotflow.config import HotflowConfig
from hotflow.portfolio.long_soak import ORIGIN, labeled_round_trips, run_labeled_long_soak
from hotflow.portfolio.session import PaperSession
from hotflow.types import KillSwitchReason


def test_labeled_lots_are_fixture_origin() -> None:
    lots = labeled_round_trips(50)
    assert len(lots) == 50
    assert all(lot.origin == ORIGIN for lot in lots)
    assert lots[0].close_price != lots[1].close_price


def test_long_soak_closes_fifty_with_marks() -> None:
    cfg = HotflowConfig()
    cfg.trading.mode = "paper"
    cfg.risk.cooldown_ms = 0
    session = PaperSession(cfg)
    meta = run_labeled_long_soak(session, target_closes=50)
    snap = session.ledger.snapshot()
    assert meta["origin"] == ORIGIN
    assert meta["fail_safe"] is True
    assert meta["live"] is False
    assert meta["auto_disable"] is False
    assert snap.closed_count >= 50
    kinds = [event.kind.value for event in session.ledger.events]
    assert kinds.count("FILL") == 50
    assert kinds.count("MARK") == 100
    assert kinds.count("FLATTEN") == 50
    report = session.report()
    extract = extract_trades(report)
    assert len(extract.trades) >= 50
    assert all(row.holding_s == 10.0 for row in extract.trades)
    assert all(row.mae is not None and row.mfe is not None for row in extract.trades)
    reviewed = build_review(report)
    assert reviewed["performance"]["sample"]["n"] >= 50
    assert reviewed["performance"]["sample"]["caveat"] is None
    assert reviewed["auto_disable"] is False


def test_long_soak_stops_when_kill_trips() -> None:
    cfg = HotflowConfig()
    session = PaperSession(cfg)
    session.pipe.kills.trip(KillSwitchReason.MANUAL, "preexisting")
    meta = run_labeled_long_soak(session, target_closes=50)
    assert session.ledger.snapshot().closed_count == 0
    assert meta["fail_safe"] is True
    assert meta["stopped_reason"] == KillSwitchReason.MANUAL.value


def test_long_soak_stops_midway_on_kill() -> None:
    cfg = HotflowConfig()
    session = PaperSession(cfg)
    original = session.pipe.risk.enforce_session_limits

    def _enforce():
        if session.ledger.snapshot().closed_count >= 3:
            session.pipe.kills.trip(KillSwitchReason.MANUAL, "mid-soak")
        return original()

    session.pipe.risk.enforce_session_limits = _enforce  # type: ignore[method-assign]
    meta = run_labeled_long_soak(session, target_closes=50)
    assert 3 <= session.ledger.snapshot().closed_count < 50
    assert meta["fail_safe"] is True
    assert session.pipe.kills.tripped


def test_cli_long_soak_and_performance(tmp_path) -> None:
    soak = tmp_path / "paper-soak-long.json"
    result = CliRunner().invoke(app, ["paper-soak", "--long", "--target-closes", "50", "--out", str(soak)])
    assert result.exit_code == 0, result.output
    assert "closed=50" in result.output
    body = json.loads(soak.read_text(encoding="utf-8"))
    assert body["origin"] == ORIGIN
    assert body["accounting"]["closed_count"] >= 50
    assert body["ledger"]["snapshot"]["closed_count"] >= 50
    assert body["auto_disable"] is False
    perf = tmp_path / "performance.json"
    review = CliRunner().invoke(app, ["performance", "--report", str(soak), "--out", str(perf)])
    assert review.exit_code == 0, review.output
    payload = json.loads(perf.read_text(encoding="utf-8"))
    assert payload["performance"]["sample"]["n"] >= 50
    assert payload["performance"]["sample"]["caveat"] != "empty_sample"
    assert payload["auto_disable"] is False


def test_cli_long_soak_refuses_live(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("HOTFLOW_TRADING_MODE", "live")
    result = CliRunner().invoke(
        app, ["paper-soak", "--long", "--out", str(tmp_path / "x.json")]
    )
    assert result.exit_code != 0
