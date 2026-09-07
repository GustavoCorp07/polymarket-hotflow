"""Readiness rollup: real report fields only; live_ready stays false."""

import json

from typer.testing import CliRunner

from hotflow.cli import app
from hotflow.monitoring.redact import REDACTED
from hotflow.readiness.rollup import (
    STATUS_FAILED,
    STATUS_PASSED,
    STATUS_SKIPPED,
    build_readiness,
    evaluate_failure,
    evaluate_live_gates,
    format_summary,
)
from hotflow.security.hygiene import PLACEHOLDER_ENV_KEYS


def _paper_ok() -> dict:
    return {
        "mode": "paper",
        "accounting": {"starting_cash": 10000.0, "cash": 9900.0, "equity": 9950.0, "event_count": 4},
    }


def _shadow_ok() -> dict:
    return {
        "mode": "shadow",
        "sent_orders": False,
        "completeness": {"rows": 3, "incomplete": 0},
    }


def _failure_ok() -> dict:
    return {"fail_safe": True, "sent_orders": False, "live_prep_still_blocked": ["wallet / signing"]}


def _live_ok() -> dict:
    return {
        "freeze_ok": True,
        "live_gates_open": False,
        "signing_implemented": False,
        "still_blocked": ["LIVE transmit"],
    }


def test_rollup_parses_real_fields() -> None:
    report = build_readiness(
        paper=_paper_ok(),
        shadow=_shadow_ok(),
        failure=_failure_ok(),
        live_gates=_live_ok(),
        sources={"paper": "mem"},
    )
    assert report["paper_ready"] is True
    assert report["shadow_ready"] is True
    assert report["failure_ready"] is True
    assert report["live_gates_frozen"] is True
    assert report["live_ready"] is False
    assert report["ok"] is True
    assert report["mode"] == "paper"
    statuses = {item["id"]: item["status"] for item in report["checks"]}
    assert statuses["paper.accounting"] == STATUS_PASSED
    assert statuses["shadow.sent_orders"] == STATUS_PASSED
    assert statuses["failure.fail_safe"] == STATUS_PASSED
    assert statuses["live.signing"] == STATUS_PASSED
    assert "LIVE transmit" in report["remaining_live_blockers"]
    assert "wallet / signing" in report["remaining_live_blockers"]


def test_missing_reports_are_skipped_not_invented() -> None:
    report = build_readiness()
    assert report["paper_ready"] is False
    assert report["ok"] is False
    assert report["live_ready"] is False
    assert all(item["status"] == STATUS_SKIPPED for item in report["checks"])


def test_fail_when_live_gate_open() -> None:
    checks = evaluate_live_gates(
        {"freeze_ok": False, "live_gates_open": True, "signing_implemented": False}
    )
    assert {item["id"]: item["status"] for item in checks}["live.gates_open"] == STATUS_FAILED
    report = build_readiness(
        paper=_paper_ok(),
        shadow=_shadow_ok(),
        failure=_failure_ok(),
        live_gates={"freeze_ok": False, "live_gates_open": True, "signing_implemented": False},
    )
    assert report["live_gates_frozen"] is False
    assert report["live_ready"] is False
    assert report["ok"] is False


def test_fail_when_failure_soak_not_fail_safe() -> None:
    checks = evaluate_failure({"fail_safe": False, "sent_orders": False})
    assert checks[0]["status"] == STATUS_FAILED
    report = build_readiness(
        paper=_paper_ok(),
        shadow=_shadow_ok(),
        failure={"fail_safe": False, "sent_orders": False},
        live_gates=_live_ok(),
    )
    assert report["failure_ready"] is False
    assert report["ok"] is False


def test_secrets_never_appear_in_report() -> None:
    dirty_paper = {
        **_paper_ok(),
        "api_key": "sk-secret-value",
        "private_key": "-----BEGIN PRIVATE KEY-----\nMIIB\n-----END PRIVATE KEY-----",
        "POLY_API_SECRET": "super-secret",
    }
    report = build_readiness(
        paper=dirty_paper,
        shadow=_shadow_ok(),
        failure=_failure_ok(),
        live_gates=_live_ok(),
    )
    blob = json.dumps(report)
    assert "sk-secret-value" not in blob
    assert "super-secret" not in blob
    assert "BEGIN PRIVATE KEY" not in blob
    assert "MIIB" not in blob
    for key in PLACEHOLDER_ENV_KEYS:
        assert f"{key}=" not in blob
    # If a secret key were copied, redact would replace the value.
    assert REDACTED not in blob or "sk-secret-value" not in blob


def test_cli_readiness_from_reports(tmp_path) -> None:
    (tmp_path / "paper-soak.json").write_text(json.dumps(_paper_ok()), encoding="utf-8")
    (tmp_path / "shadow-soak.json").write_text(json.dumps(_shadow_ok()), encoding="utf-8")
    (tmp_path / "failure-soak.json").write_text(json.dumps(_failure_ok()), encoding="utf-8")
    (tmp_path / "live-gates.json").write_text(json.dumps(_live_ok()), encoding="utf-8")
    out = tmp_path / "readiness.json"
    result = CliRunner().invoke(app, ["readiness", "--from-reports", str(tmp_path), "--out", str(out)])
    assert result.exit_code == 0, result.output
    assert "paper_ready=True" in result.output
    assert "live_ready=False" in result.output
    body = json.loads(out.read_text(encoding="utf-8"))
    assert body["ok"] is True
    assert body["live_ready"] is False


def test_cli_readiness_fails_open_live_gate(tmp_path) -> None:
    (tmp_path / "paper-soak.json").write_text(json.dumps(_paper_ok()), encoding="utf-8")
    (tmp_path / "shadow-soak.json").write_text(json.dumps(_shadow_ok()), encoding="utf-8")
    (tmp_path / "failure-soak.json").write_text(json.dumps(_failure_ok()), encoding="utf-8")
    (tmp_path / "live-gates.json").write_text(
        json.dumps({"freeze_ok": False, "live_gates_open": True, "signing_implemented": False}),
        encoding="utf-8",
    )
    result = CliRunner().invoke(app, ["readiness", "--from-reports", str(tmp_path)])
    assert result.exit_code == 1, result.output
    assert "live_gates_frozen=False" in result.output


def test_format_summary_lists_blockers() -> None:
    report = build_readiness(
        paper=_paper_ok(),
        shadow=_shadow_ok(),
        failure=_failure_ok(),
        live_gates=_live_ok(),
    )
    text = format_summary(report)
    assert "paper_ready=True" in text
    assert "live_ready=False" in text
    assert "remaining LIVE blockers" in text
