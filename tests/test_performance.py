"""Performance review + alpha decay from real-shaped reports only."""

from __future__ import annotations

import ast
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from typer.testing import CliRunner

from hotflow.analytics.cold import analyze_performance_cold
from hotflow.analytics.decay import decay_report
from hotflow.analytics.performance import half_life_bucket, review_extract, sample_caveat
from hotflow.analytics.review import build_review, informational_section
from hotflow.analytics.trades import extract_trades
from hotflow.cli import app
from hotflow.readiness.rollup import build_readiness
from hotflow.reason_codes import ReasonCode
from hotflow.security.hygiene import PLACEHOLDER_ENV_KEYS


def _backtest(trades: list[dict], *, half_life_ms: float | None = None) -> dict:
    payload: dict = {
        "mode": "backtest",
        "strategy_id": "crypto_updown",
        "trades": trades,
        "metrics": {"abs_pnl_not_a_selection_metric": True},
    }
    if half_life_ms is not None:
        payload["signal_half_life_ms"] = half_life_ms
    return payload


def test_empty_sample_is_not_invented() -> None:
    extract = extract_trades({"mode": "paper", "accounting": {"starting_cash": 10000}})
    assert extract.trades == []
    review = review_extract(extract)
    assert review["sample"]["n"] == 0
    assert review["sample"]["strong_conclusion"] is False
    assert review["net_pnl"] is None
    assert review["half_life"]["bucket"] == "N/A"
    assert "empty" in (review["sample"]["caveat"] or "")


def test_small_sample_caveat() -> None:
    caveat = sample_caveat(4)
    assert caveat["strong_conclusion"] is False
    assert caveat["caveat"] == "too_small_for_inference"
    trades = [{"pnl": 0.1, "fee": 0.01, "ts": "2026-09-07T18:00:00Z"} for _ in range(4)]
    body = build_review(_backtest(trades))
    assert body["performance"]["sample"]["strong_conclusion"] is False
    assert body["decay"]["auto_disable"] is False
    assert body["decay"]["any_degradation_suggested"] is False


def test_decay_detects_synthetic_degradation() -> None:
    winners = [{"pnl": 1.0, "fee": 0.0} for _ in range(40)]
    losers = [{"pnl": -1.0, "fee": 0.0} for _ in range(40)]
    body = build_review(_backtest(winners + losers))
    win50 = next(row for row in body["decay"]["windows"] if row["window"] == 50)
    assert win50["n_recent"] == 50
    assert win50["n_baseline"] == 30
    assert win50["degraded"] is True
    assert win50["flag"] == "degradation_suggested"
    assert win50["auto_disable"] is False
    assert body["decay"]["any_degradation_suggested"] is True
    assert body["decay"]["production_change"] is False
    assert body["auto_disable"] is False


def test_abs_pnl_ranking_refused() -> None:
    trades = [{"pnl": 9.0}, {"pnl": -1.0}]
    body = build_review(_backtest(trades), rank_metric="abs_pnl")
    assert body["refused"] is True
    assert body["reason"] == ReasonCode.MAX_ABS_PNL_SELECTION_REFUSED
    assert body["selection"]["rank_refused"] is True
    assert body["performance"]["abs_pnl_not_a_selection_metric"] is True


def test_paper_ledger_events_mae_mfe_holding() -> None:
    start = datetime(2026, 9, 7, 18, 0, tzinfo=UTC)
    report = {
        "mode": "paper",
        "session_id": "s1",
        "strategy_id": "crypto_updown",
        "accounting": {"starting_cash": 10000.0, "fees": 0.01, "drawdown": 0.0},
        "events": [
            {
                "kind": "FILL",
                "ts": start.isoformat(),
                "token_id": "t",
                "side": "BUY",
                "size": 2.0,
                "price": 0.40,
                "fee": 0.0,
                "closed": False,
                "realized_delta": 0.0,
            },
            {
                "kind": "MARK",
                "ts": (start + timedelta(seconds=2)).isoformat(),
                "token_id": "t",
                "price": 0.35,
            },
            {
                "kind": "MARK",
                "ts": (start + timedelta(seconds=4)).isoformat(),
                "token_id": "t",
                "price": 0.50,
            },
            {
                "kind": "FLATTEN",
                "ts": (start + timedelta(seconds=10)).isoformat(),
                "token_id": "t",
                "side": "SELL",
                "size": 2.0,
                "price": 0.45,
                "fee": 0.01,
                "closed": True,
                "realized_delta": 0.09,
            },
        ],
    }
    extract = extract_trades(report)
    assert len(extract.trades) == 1
    row = extract.trades[0]
    assert row.pnl == 0.09
    assert row.holding_s == 10.0
    assert row.mae == (0.35 - 0.40) * 2.0
    assert row.mfe == (0.50 - 0.40) * 2.0
    reviewed = review_extract(extract)
    assert reviewed["fees"] == 0.01
    assert reviewed["gross_pnl"] is not None
    assert abs(reviewed["gross_pnl"] - 0.10) < 1e-12
    assert reviewed["avg_holding_s"] == 10.0
    assert reviewed["mae"] == row.mae
    assert reviewed["mfe"] == row.mfe


def test_shadow_does_not_invent_pnl() -> None:
    extract = extract_trades({"mode": "shadow", "sent_orders": False, "results": [{"would_buy": True}]})
    assert extract.trades == []
    assert "not invented" in extract.notes[0]


def test_half_life_from_metadata_only() -> None:
    assert half_life_bucket(None) == "N/A"
    assert half_life_bucket(2000) == "1-5s"
    body = build_review(_backtest([{"pnl": 0.1}], half_life_ms=2000.0))
    assert body["performance"]["half_life"]["bucket"] == "1-5s"
    assert body["performance"]["half_life"]["estimated_from_trades"] is None


def test_readiness_performance_is_non_blocking() -> None:
    paper = {
        "mode": "paper",
        "accounting": {"starting_cash": 10000.0, "cash": 9900.0, "equity": 9950.0, "event_count": 4},
    }
    info = informational_section(paper, source="mem")
    assert info["does_not_affect_ok"] is True
    report = build_readiness(
        paper=paper,
        shadow={"mode": "shadow", "sent_orders": False, "completeness": {"rows": 3, "incomplete": 0}},
        failure={"fail_safe": True, "sent_orders": False},
        live_gates={"freeze_ok": True, "live_gates_open": False, "signing_implemented": False},
    )
    assert report["ok"] is True
    assert report["performance"]["informational"] is True
    assert report["performance"]["does_not_affect_ok"] is True


def test_hot_path_modules_do_not_import_kimi() -> None:
    for path in (
        Path("src/hotflow/analytics/performance.py"),
        Path("src/hotflow/analytics/decay.py"),
        Path("src/hotflow/analytics/review.py"),
        Path("src/hotflow/analytics/trades.py"),
    ):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        modules = [node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) and node.module]
        assert not any(mod and "ai_research" in mod for mod in modules)


def test_cold_path_analyst_mockable() -> None:
    from hotflow.ai_research.kimi_client import KimiClient

    def transport(payload: dict) -> dict:
        return {"mock": True, "content": "descriptive only"}

    out = analyze_performance_cold({"n": 3}, KimiClient(transport=transport, api_key=None))
    assert out["content"] == "descriptive only"


def test_cli_performance_and_refuse(tmp_path) -> None:
    src = tmp_path / "backtest-demo.json"
    src.write_text(json.dumps(_backtest([{"pnl": 0.2, "fee": 0.01, "style": "TAKER"}])), encoding="utf-8")
    out = tmp_path / "perf.json"
    ok = CliRunner().invoke(app, ["performance", "--report", str(src), "--out", str(out)])
    assert ok.exit_code == 0, ok.output
    body = json.loads(out.read_text(encoding="utf-8"))
    assert body["performance"]["taker_count"] == 1
    assert body["auto_disable"] is False
    blob = out.read_text(encoding="utf-8")
    for key in PLACEHOLDER_ENV_KEYS:
        assert f"{key}=" not in blob
    assert "BEGIN PRIVATE KEY" not in blob
    refused = CliRunner().invoke(app, ["performance", "--report", str(src), "--rank-by", "abs_pnl"])
    assert refused.exit_code == 1
    assert "MAX_ABS_PNL_SELECTION_REFUSED" in refused.output or "refused" in refused.output


def test_decay_empty_windows() -> None:
    payload = decay_report([])
    assert payload["any_degradation_suggested"] is False
    assert payload["sample"]["n"] == 0
    assert all(row["flag"] == "insufficient_sample" for row in payload["windows"])
