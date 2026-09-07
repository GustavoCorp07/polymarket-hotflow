from __future__ import annotations

import json
from pathlib import Path

import pytest

from hotflow.analytics.tuner import (
    AutoTunerStub,
    OfflineTuner,
    suggestion_path_allowed,
    write_suggestion,
)
from hotflow.reason_codes import ReasonCode


def _report(*, expectancy: float, drawdown: float, skips: dict[str, int], trades: int = 3) -> dict:
    return {
        "metrics": {
            "expectancy": expectancy,
            "max_drawdown": drawdown,
            "trade_count": trades,
            "skip_counts": skips,
            "abs_pnl": 9999.0,
            "abs_pnl_not_a_selection_metric": True,
        },
        "splits": {"train": {}, "validation": {}, "oos": {}},
        "walk_forward": {"status": "stub", "windows": []},
    }


def test_stub_never_applies() -> None:
    stub = AutoTunerStub()
    proposal = stub.propose("expectancy", [0.1, 0.2])
    assert proposal.applied is False
    assert stub.apply(proposal).applied is False


def test_refuses_abs_pnl_objective() -> None:
    tuner = OfflineTuner()
    report = tuner.propose_from_reports([_report(expectancy=0.1, drawdown=0.01, skips={})], objective="abs_pnl")
    assert report.refused is True
    assert report.applied is False
    assert report.reason == ReasonCode.MAX_ABS_PNL_SELECTION_REFUSED
    assert report.suggested == {}


def test_bounded_suggestions_from_skips_and_drawdown() -> None:
    tuner = OfflineTuner()
    report = tuner.propose_from_reports(
        [
            _report(
                expectancy=-0.02,
                drawdown=0.12,
                skips={"MARKET_NOT_HOT": 4, "EDGE_TOO_SMALL": 3},
            )
        ],
        objective="expectancy",
        hypothesis="raise edge if drawdown is high",
    )
    assert report.refused is False
    assert report.applied is False
    assert report.production_write is False
    assert report.metrics_used["abs_pnl_ignored"] is True
    edge = report.suggested["trading.min_required_edge"]
    assert 0.006 <= edge <= 0.040
    score = report.suggested["hot_market.min_score_to_trade"]
    assert 40.0 <= score <= 80.0


def test_write_suggestion_refuses_production_path(tmp_path: Path) -> None:
    report = OfflineTuner().propose_from_reports(
        [_report(expectancy=0.01, drawdown=0.01, skips={})],
        objective="expectancy",
    )
    forbidden = tmp_path / "configs" / "default.yaml"
    forbidden.parent.mkdir()
    assert suggestion_path_allowed(forbidden) is False
    with pytest.raises(ValueError, match=ReasonCode.TUNER_PRODUCTION_WRITE_REFUSED):
        write_suggestion(forbidden, report)
    allowed = tmp_path / "reports" / "tune-suggestion.yaml"
    write_suggestion(allowed, report)
    text = allowed.read_text(encoding="utf-8")
    assert "applied: false" in text
    assert "production_write: false" in text


def test_cli_tune_refuses_pnl(tmp_path: Path) -> None:
    from typer.testing import CliRunner

    from hotflow.cli import app

    report = tmp_path / "bt.json"
    report.write_text(json.dumps(_report(expectancy=0.2, drawdown=0.01, skips={})), encoding="utf-8")
    out = tmp_path / "tune.json"
    completed = CliRunner().invoke(
        app, ["tune", "--report", str(report), "--objective", "pnl", "--out", str(out)]
    )
    assert completed.exit_code == 0, completed.output
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["refused"] is True
    assert payload["applied"] is False
    assert payload["reason"] == ReasonCode.MAX_ABS_PNL_SELECTION_REFUSED
