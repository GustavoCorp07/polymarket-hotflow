"""Walk-forward / regime split on existing long-soak closes only."""

from __future__ import annotations

import json

from typer.testing import CliRunner

from hotflow.analytics.walkforward import build_walk_forward
from hotflow.cli import app
from hotflow.config import HotflowConfig
from hotflow.portfolio.long_soak import run_labeled_long_soak
from hotflow.portfolio.session import PaperSession
from hotflow.reason_codes import ReasonCode


def _long_report(n: int = 50) -> dict:
    cfg = HotflowConfig()
    cfg.trading.mode = "paper"
    session = PaperSession(cfg)
    run_labeled_long_soak(session, target_closes=n)
    return session.report()


def test_walk_forward_on_fifty_closes() -> None:
    report = _long_report(50)
    body = build_walk_forward(report, expanding=True, train_size=20, test_size=10, step=10)
    assert body["n_closes"] == 50
    assert body["fold_count"] == 3
    assert body["auto_disable"] is False
    assert body["live_ready"] is False
    used = 0
    for fold in body["folds"]:
        train = fold["train"]
        hold = fold["holdout"]
        assert train["trade_count"] >= 20
        assert hold["trade_count"] == 10
        assert "expectancy" in hold
        assert "win_rate" in hold
        assert "max_drawdown" in hold
        assert hold["abs_pnl_not_a_selection_metric"] is True
        assert hold["sample"]["strong_conclusion"] is False
        used += hold["trade_count"]
    assert used == 30
    assert body["n_closes"] == 50


def test_rolling_windows_use_fixed_train_width() -> None:
    body = build_walk_forward(
        _long_report(50), expanding=False, train_size=20, test_size=10, step=10
    )
    assert body["scheme"] == "rolling"
    assert body["fold_count"] == 3
    for fold in body["folds"]:
        assert fold["scheme"] == "rolling"
        assert fold["train"]["trade_count"] == 20
        assert fold["holdout"]["trade_count"] == 10
        assert fold["train"]["sample"]["strong_conclusion"] is False


def test_regime_split_from_labeled_soak() -> None:
    body = build_walk_forward(_long_report(50))
    regimes = body["regime_split"]
    assert regimes["status"] == "labeled_synthetic"
    assert set(regimes["regimes"]) == {"normal", "high_volatility"}
    assert regimes["regimes"]["normal"]["trade_count"] == 25
    assert regimes["regimes"]["high_volatility"]["trade_count"] == 25


def test_regime_na_without_labels() -> None:
    report = {
        "mode": "backtest",
        "trades": [{"pnl": 0.1}, {"pnl": -0.05}, {"pnl": 0.02}],
    }
    body = build_walk_forward(report, train_size=20, test_size=10)
    assert body["regime_split"]["status"] == "N/A"
    assert body["fold_count"] == 0
    assert body["sample"]["strong_conclusion"] is False


def test_tiny_folds_are_caveated() -> None:
    body = build_walk_forward(_long_report(12), train_size=6, test_size=3, step=3)
    assert body["fold_count"] >= 1
    hold = body["folds"][0]["holdout"]
    assert hold["sample"]["strong_conclusion"] is False
    assert hold["sample"]["caveat"] == "too_small_for_inference"


def test_abs_pnl_ranking_refused() -> None:
    body = build_walk_forward(_long_report(50), rank_metric="abs_pnl")
    assert body["refused"] is True
    assert body["reason"] == ReasonCode.MAX_ABS_PNL_SELECTION_REFUSED
    assert body["auto_disable"] is False


def test_cli_walk_forward(tmp_path) -> None:
    soak = tmp_path / "paper-soak-long.json"
    CliRunner().invoke(app, ["paper-soak", "--long", "--target-closes", "50", "--out", str(soak)])
    out = tmp_path / "walk-forward.json"
    result = CliRunner().invoke(app, ["walk-forward", "--report", str(soak), "--out", str(out)])
    assert result.exit_code == 0, result.output
    assert "auto_disable=False" in result.output
    body = json.loads(out.read_text(encoding="utf-8"))
    assert body["n_closes"] == 50
    assert body["fold_count"] >= 1
    assert body["live_ready"] is False
    refused = CliRunner().invoke(
        app, ["walk-forward", "--report", str(soak), "--rank-by", "pnl"]
    )
    assert refused.exit_code == 1
