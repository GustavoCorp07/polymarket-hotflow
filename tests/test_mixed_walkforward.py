"""Walk-forward / decay on mixed soak using DETECTED labels, not --long synthetic."""

from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from hotflow.analytics.mixed_review import (
    ANALYSIS_UNIT,
    build_mixed_detected_review,
    extract_proposals,
    is_mixed_soak,
)
from hotflow.analytics.review import build_review
from hotflow.analytics.walkforward import build_walk_forward
from hotflow.cli import app
from hotflow.config import load_config
from hotflow.execution.live_gate import live_gates_open
from hotflow.portfolio.mixed_soak import run_mixed_paper_soak
from hotflow.portfolio.session import PaperSession


def _mixed_report() -> dict:
    cfg = load_config(Path("configs/default.yaml"))
    cfg.trading.mode = "paper"
    cfg.risk.cooldown_ms = 0
    cfg.risk.cooldown_after_losses_ms = 0
    session = PaperSession(cfg, use_twap_fixtures=True)
    meta = run_mixed_paper_soak(session, cycles=5)
    payload = session.report()
    payload.update(meta)
    return payload


def test_is_mixed_soak_vs_long() -> None:
    assert is_mixed_soak({"mixed_soak": True, "origin": "mixed_fixture_book"}) is True
    assert is_mixed_soak({"origin": "synthetic_official_shape", "long_soak": True}) is False


def test_detected_split_not_synthetic() -> None:
    report = _mixed_report()
    proposals = extract_proposals(report)
    assert len(proposals) == 30
    assert any(row.regime == "news_shock" for row in proposals)
    assert any(row.regime == "near_resolution" for row in proposals)
    mixed = build_mixed_detected_review(report)
    split = mixed["detected_regime_split"]
    assert split["status"] == "detected"
    assert split["origin"] == "detected"
    assert "news_shock" in split["regimes"]
    assert "near_resolution" in split["regimes"]
    assert split["strong_conclusion"] is False
    for bucket in split["regimes"].values():
        assert bucket["sample"]["strong_conclusion"] is False
        assert bucket["realized_pnl"] is None
    assert ANALYSIS_UNIT.split()[0] == "Primary"


def test_walk_forward_mixed_uses_detected_not_long_labels() -> None:
    report = _mixed_report()
    body = build_walk_forward(report)
    assert body["mixed_soak"] is True
    assert body["regime_split"]["status"] == "detected"
    assert body["regime_split"]["origin"] == "detected"
    assert body["synthetic_regime_split"]["status"] == "N/A"
    assert body["n_proposals"] == 30
    assert body["fold_count"] == 0
    assert "not invented" in (body.get("fold_note") or "")
    assert body["sample"]["strong_conclusion"] is False
    assert body["auto_disable"] is False
    assert body["live_ready"] is False
    closes = body["close_pnl_by_detected_label"]
    assert closes["status"] == "detected_join"
    assert closes["sample"]["strong_conclusion"] is False
    decay = body["decay_by_detected_label"]
    assert decay["auto_disable"] is False
    for label, payload in decay["labels"].items():
        assert payload["auto_disable"] is False
        assert payload["any_degradation_suggested"] is False
        assert payload["sample"]["strong_conclusion"] is False
        assert label  # detected or N/A


def test_tiny_forced_folds_stay_caveated() -> None:
    report = _mixed_report()
    body = build_walk_forward(report, train_size=3, test_size=2, step=2)
    if body["fold_count"]:
        hold = body["folds"][0]["holdout"]
        assert hold["sample"]["strong_conclusion"] is False
        assert hold["sample"]["caveat"] == "too_small_for_inference"


def test_review_and_cli_mixed_detected(tmp_path) -> None:
    soak = tmp_path / "paper-soak-mixed.json"
    made = CliRunner().invoke(app, ["paper-soak", "--mixed", "--cycles", "5", "--out", str(soak)])
    assert made.exit_code == 0, made.output
    review = build_review(json.loads(soak.read_text(encoding="utf-8")))
    assert review["mixed_soak"] is True
    assert review["detected_regimes"]["detected_regime_split"]["status"] == "detected"
    wf = tmp_path / "walk-forward-mixed.json"
    walked = CliRunner().invoke(app, ["walk-forward", "--report", str(soak), "--out", str(wf)])
    assert walked.exit_code == 0, walked.output
    assert "detected" in walked.output
    assert "news_shock" in walked.output
    body = json.loads(wf.read_text(encoding="utf-8"))
    assert body["regime_split"]["status"] == "detected"
    assert "high_volatility" not in body["regime_split"]["regimes"]
    dec = tmp_path / "decay-mixed.json"
    decayed = CliRunner().invoke(app, ["decay", "--report", str(soak), "--out", str(dec)])
    assert decayed.exit_code == 0, decayed.output
    decay_body = json.loads(dec.read_text(encoding="utf-8"))
    assert decay_body["decay"]["auto_disable"] is False
    assert decay_body["decay_by_detected_label"]["auto_disable"] is False
    assert live_gates_open(load_config(Path("configs/default.yaml"))) is False


def test_cli_walk_forward_refuses_live_mixed(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("HOTFLOW_TRADING_MODE", "live")
    result = CliRunner().invoke(
        app, ["walk-forward", "--report", str(tmp_path / "missing.json")]
    )
    assert result.exit_code != 0
