"""Compose performance review + decay. Refuses abs-PnL ranking."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from hotflow.analytics.decay import decay_report
from hotflow.analytics.io import latest_report, load_json
from hotflow.analytics.performance import review_extract
from hotflow.analytics.stats import refuse_max_abs_pnl_selection
from hotflow.analytics.trades import extract_trades
from hotflow.monitoring.redact import redact


def build_review(
    report: dict[str, Any] | None,
    *,
    source: str | None = None,
    rank_metric: str | None = None,
) -> dict[str, Any]:
    blocked = refuse_max_abs_pnl_selection(rank_metric) if rank_metric else None
    extract = extract_trades(report)
    performance = review_extract(extract)
    decay = decay_report(extract.pnls)
    payload: dict[str, Any] = {
        "mode": "paper",
        "live": False,
        "source": source,
        "performance": performance,
        "decay": decay,
        "selection": {
            "abs_pnl_not_a_selection_metric": True,
            "rank_refused": bool(blocked),
            "rank": blocked,
        },
        "auto_disable": False,
        "suggestion_only": True,
    }
    if blocked:
        payload["refused"] = True
        payload["reason"] = blocked.get("reason")
    cleaned = redact(payload)
    return cleaned if isinstance(cleaned, dict) else payload


def informational_section(report: dict[str, Any] | None, *, source: str | None = None) -> dict[str, Any]:
    """Non-blocking readiness attach. Never changes paper_ready / ok."""
    if report is None:
        return {
            "status": "SKIPPED",
            "informational": True,
            "does_not_affect_ok": True,
            "detail": "no report; not invented",
            "source": source,
        }
    review = build_review(report, source=source)
    perf = review.get("performance") or {}
    decay = review.get("decay") or {}
    sample = perf.get("sample") or {}
    return {
        "status": "INFO",
        "informational": True,
        "does_not_affect_ok": True,
        "source": source,
        "sample": sample,
        "net_pnl": perf.get("net_pnl"),
        "win_rate": perf.get("win_rate"),
        "decay_flag": decay.get("any_degradation_suggested"),
        "auto_disable": False,
        "note": "Performance/decay do not gate paper or LIVE readiness.",
    }


def load_review_source(
    path: Path | None = None, directory: Path | None = None
) -> tuple[dict[str, Any] | None, str | None]:
    if path is not None:
        return load_json(path), str(path)
    if directory is None:
        return None, None
    for prefixes in (
        ("paper-soak", "paper-run"),
        ("backtest-",),
        ("shadow-soak", "shadow-"),
    ):
        found = latest_report(directory, prefixes)
        loaded = load_json(found)
        if loaded is not None:
            return loaded, str(found)
    return None, None


def format_review(report: dict[str, Any]) -> str:
    perf = report.get("performance") or {}
    sample = perf.get("sample") or {}
    decay = report.get("decay") or {}
    lines = [
        f"source={report.get('source')} n={sample.get('n')} caveat={sample.get('caveat')} "
        f"net_pnl={perf.get('net_pnl')} win_rate={perf.get('win_rate')} "
        f"decay_suggested={decay.get('any_degradation_suggested')} auto_disable=False"
    ]
    if report.get("refused"):
        lines.append(f"  refused={report.get('reason')}")
    for window in decay.get("windows") or []:
        lines.append(
            f"  recent_{window.get('window')} n={window.get('n_recent')} "
            f"flag={window.get('flag')} clipped={window.get('clipped')}"
        )
    half = perf.get("half_life") or {}
    lines.append(f"  half_life_bucket={half.get('bucket')}")
    return "\n".join(lines)
