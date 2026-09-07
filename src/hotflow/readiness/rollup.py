"""Aggregate real soak / gate reports. Never invent pass/fail or LIVE readiness."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from hotflow.execution.live_gate import LIVE_PREP_STILL_BLOCKED
from hotflow.failure.soak import LIVE_PREP_STILL_BLOCKED as FAILURE_BLOCKED
from hotflow.monitoring.redact import redact

STATUS_PASSED = "PASSED"
STATUS_FAILED = "FAILED"
STATUS_SKIPPED = "SKIPPED"


def _check(check_id: str, status: str, *, detail: str = "", source: str | None = None) -> dict[str, Any]:
    return {"id": check_id, "status": status, "detail": detail, "source": source}


def _missing(check_id: str, source: str | None) -> dict[str, Any]:
    return _check(check_id, STATUS_SKIPPED, detail="report not provided; not invented", source=source)


def evaluate_paper(report: dict[str, Any] | None, *, source: str | None = None) -> list[dict[str, Any]]:
    if report is None:
        return [
            _missing("paper.mode", source),
            _missing("paper.accounting", source),
            _missing("paper.ledger_events", source),
        ]
    mode = str(report.get("mode") or "")
    acc = report.get("accounting") if isinstance(report.get("accounting"), dict) else None
    checks = [
        _check(
            "paper.mode",
            STATUS_PASSED if mode == "paper" else STATUS_FAILED,
            detail=mode or "missing",
            source=source,
        )
    ]
    if acc is None:
        checks.append(_check("paper.accounting", STATUS_FAILED, detail="accounting missing", source=source))
        checks.append(_check("paper.ledger_events", STATUS_FAILED, detail="accounting missing", source=source))
        return checks
    has_books = all(key in acc for key in ("starting_cash", "cash", "equity"))
    checks.append(
        _check(
            "paper.accounting",
            STATUS_PASSED if has_books else STATUS_FAILED,
            detail="starting_cash/cash/equity" if has_books else f"keys={sorted(acc)}",
            source=source,
        )
    )
    events = acc.get("event_count")
    checks.append(
        _check(
            "paper.ledger_events",
            STATUS_PASSED if isinstance(events, (int, float)) and events >= 0 else STATUS_FAILED,
            detail=str(events),
            source=source,
        )
    )
    return checks


def evaluate_shadow(report: dict[str, Any] | None, *, source: str | None = None) -> list[dict[str, Any]]:
    if report is None:
        return [
            _missing("shadow.mode", source),
            _missing("shadow.sent_orders", source),
            _missing("shadow.signal_complete", source),
        ]
    mode = str(report.get("mode") or "")
    sent = report.get("sent_orders")
    raw_complete = report.get("completeness")
    complete: dict[str, Any] = raw_complete if isinstance(raw_complete, dict) else {}
    rows = complete.get("rows")
    incomplete = complete.get("incomplete")
    complete_ok = isinstance(rows, int) and rows > 0 and incomplete == 0
    return [
        _check(
            "shadow.mode",
            STATUS_PASSED if mode == "shadow" else STATUS_FAILED,
            detail=mode or "missing",
            source=source,
        ),
        _check(
            "shadow.sent_orders",
            STATUS_PASSED if sent is False else STATUS_FAILED,
            detail=str(sent),
            source=source,
        ),
        _check(
            "shadow.signal_complete",
            STATUS_PASSED if complete_ok else STATUS_FAILED,
            detail=f"rows={rows} incomplete={incomplete}",
            source=source,
        ),
    ]


def evaluate_failure(report: dict[str, Any] | None, *, source: str | None = None) -> list[dict[str, Any]]:
    if report is None:
        return [_missing("failure.fail_safe", source), _missing("failure.sent_orders", source)]
    fail_safe = report.get("fail_safe")
    sent = report.get("sent_orders")
    return [
        _check(
            "failure.fail_safe",
            STATUS_PASSED if fail_safe is True else STATUS_FAILED,
            detail=str(fail_safe),
            source=source,
        ),
        _check(
            "failure.sent_orders",
            STATUS_PASSED if sent is False else STATUS_FAILED,
            detail=str(sent),
            source=source,
        ),
    ]


def evaluate_live_gates(report: dict[str, Any] | None, *, source: str | None = None) -> list[dict[str, Any]]:
    if report is None:
        return [
            _missing("live.freeze", source),
            _missing("live.gates_open", source),
            _missing("live.signing", source),
        ]
    freeze = report.get("freeze_ok")
    opened = report.get("live_gates_open")
    signing = report.get("signing_implemented")
    return [
        _check(
            "live.freeze",
            STATUS_PASSED if freeze is True else STATUS_FAILED,
            detail=str(freeze),
            source=source,
        ),
        _check(
            "live.gates_open",
            STATUS_PASSED if opened is False else STATUS_FAILED,
            detail=str(opened),
            source=source,
        ),
        _check(
            "live.signing",
            STATUS_PASSED if signing is False else STATUS_FAILED,
            detail=str(signing),
            source=source,
        ),
    ]


def _group_ok(checks: list[dict[str, Any]]) -> bool:
    return bool(checks) and all(item["status"] == STATUS_PASSED for item in checks)


def remaining_live_blockers(*reports: dict[str, Any] | None) -> list[str]:
    seen: list[str] = []
    for report in reports:
        if not report:
            continue
        for key in ("still_blocked", "live_prep_still_blocked"):
            rows = report.get(key)
            if isinstance(rows, list):
                for item in rows:
                    text = str(item)
                    if text and text not in seen:
                        seen.append(text)
    for item in (*LIVE_PREP_STILL_BLOCKED, *FAILURE_BLOCKED):
        if item not in seen:
            seen.append(item)
    return seen


def build_readiness(
    *,
    paper: dict[str, Any] | None = None,
    shadow: dict[str, Any] | None = None,
    failure: dict[str, Any] | None = None,
    live_gates: dict[str, Any] | None = None,
    sources: dict[str, str | None] | None = None,
) -> dict[str, Any]:
    src = sources or {}
    checks = [
        *evaluate_paper(paper, source=src.get("paper")),
        *evaluate_shadow(shadow, source=src.get("shadow")),
        *evaluate_failure(failure, source=src.get("failure")),
        *evaluate_live_gates(live_gates, source=src.get("live_gates")),
    ]
    paper_ready = _group_ok(evaluate_paper(paper, source=src.get("paper")))
    shadow_ready = _group_ok(evaluate_shadow(shadow, source=src.get("shadow")))
    failure_ready = _group_ok(evaluate_failure(failure, source=src.get("failure")))
    live_frozen = _group_ok(evaluate_live_gates(live_gates, source=src.get("live_gates")))
    from hotflow.analytics.review import informational_section

    payload = {
        "mode": "paper",
        "live_ready": False,
        "paper_ready": paper_ready,
        "shadow_ready": shadow_ready,
        "failure_ready": failure_ready,
        "live_gates_frozen": live_frozen,
        "ok": paper_ready and shadow_ready and failure_ready and live_frozen,
        "checks": checks,
        "remaining_live_blockers": remaining_live_blockers(live_gates, failure),
        "sources": {key: src.get(key) for key in ("paper", "shadow", "failure", "live_gates")},
        "performance": informational_section(paper, source=src.get("paper")),
        "note": "live_ready is always false; signing/transmit are not implemented.",
    }
    cleaned = redact(payload)
    return cleaned if isinstance(cleaned, dict) else payload


def latest_report(directory: Path, prefixes: tuple[str, ...]) -> Path | None:
    if not directory.is_dir():
        return None
    candidates: list[Path] = []
    for path in directory.glob("*.json"):
        name = path.name
        if name.startswith("readiness-"):
            continue
        if any(name.startswith(prefix) for prefix in prefixes):
            candidates.append(path)
    if not candidates:
        return None
    candidates.sort(key=lambda item: item.stat().st_mtime, reverse=True)
    return candidates[0]


def load_json(path: Path | None) -> dict[str, Any] | None:
    if path is None or not path.is_file():
        return None
    import json

    raw = json.loads(path.read_text(encoding="utf-8"))
    return raw if isinstance(raw, dict) else None


def format_summary(report: dict[str, Any]) -> str:
    lines = [
        f"paper_ready={report.get('paper_ready')} shadow_ready={report.get('shadow_ready')} "
        f"failure_ready={report.get('failure_ready')} live_ready={report.get('live_ready')} "
        f"live_gates_frozen={report.get('live_gates_frozen')} ok={report.get('ok')}"
    ]
    for check in report.get("checks") or []:
        if not isinstance(check, dict):
            continue
        lines.append(f"  {check.get('id')} {check.get('status')} {check.get('detail')}")
    perf = report.get("performance")
    if isinstance(perf, dict):
        lines.append(
            f"  performance {perf.get('status')} informational n={((perf.get('sample') or {}).get('n'))} "
            f"does_not_affect_ok={perf.get('does_not_affect_ok')}"
        )
    lines.append("remaining LIVE blockers:")
    for item in report.get("remaining_live_blockers") or []:
        lines.append(f"  - {item}")
    return "\n".join(lines)
