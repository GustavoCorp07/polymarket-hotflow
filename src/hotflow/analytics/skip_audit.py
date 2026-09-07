"""Parte 47 — cold-path why-no-trade rollup. Never mutates production."""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Mapping
from typing import Any

from hotflow.analytics.experiments import git_commit
from hotflow.analytics.signal_quality import impact_exhausted, spread_regime_label
from hotflow.monitoring.redact import redact


def _as_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str) and value:
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def _signal_of(row: Mapping[str, Any]) -> dict[str, Any]:
    extra = _as_dict(row.get("extra"))
    signal = extra.get("signal")
    if isinstance(signal, dict):
        return signal
    return {}


def _regime_of(row: Mapping[str, Any], signal: dict[str, Any]) -> str:
    extra = _as_dict(row.get("extra"))
    extras = extra if extra.get("microstructure") else signal
    label = spread_regime_label(extras) or signal.get("spread_regime")
    if label:
        return str(label)
    micro = extras.get("microstructure") if isinstance(extras.get("microstructure"), dict) else {}
    if not micro:
        micro = signal.get("microstructure") if isinstance(signal.get("microstructure"), dict) else {}
    regime = micro.get("spread_regime") if isinstance(micro, dict) else None
    if isinstance(regime, dict) and regime.get("label") and regime.get("label") != "N/A":
        return str(regime["label"])
    return "N/A"


def _exhausted_of(row: Mapping[str, Any], signal: dict[str, Any]) -> bool:
    if signal.get("impact_exhausted") is True:
        return True
    extra = _as_dict(row.get("extra"))
    extras = extra if extra.get("microstructure") else signal
    flag = impact_exhausted(extras)
    if flag is True:
        return True
    micro = signal.get("microstructure")
    if isinstance(micro, dict) and (micro.get("exhausted_buy") or micro.get("exhausted_sell")):
        return True
    return False


def rollup_skip_audit(
    signals: list[dict[str, Any]],
    *,
    source: str | None = None,
) -> dict[str, Any]:
    """Bucket refused rows by primary reason × spread_regime. Suggestion-only."""
    by_reason: Counter[str] = Counter()
    by_regime: Counter[str] = Counter()
    by_reason_regime: Counter[str] = Counter()
    by_reason_codes: Counter[str] = Counter()
    exhausted = 0
    accepted = 0
    skipped = 0
    missing_signal = 0
    for row in signals:
        signal = _signal_of(row)
        if not signal:
            missing_signal += 1
        if row.get("accepted"):
            accepted += 1
            continue
        skipped += 1
        reason = str(row.get("reason") or "NO_TRADE")
        regime = _regime_of(row, signal)
        by_reason[reason] += 1
        by_regime[regime] += 1
        by_reason_regime[f"{reason}|{regime}"] += 1
        raw_codes = signal.get("reason_codes")
        codes = raw_codes if isinstance(raw_codes, list) else [reason]
        for code in codes:
            by_reason_codes[str(code)] += 1
        if _exhausted_of(row, signal):
            exhausted += 1
    payload: dict[str, Any] = {
        "mode": "paper",
        "live": False,
        "production_changed": False,
        "suggestion_only": True,
        "git_commit": git_commit(),
        "source": source,
        "signals": len(signals),
        "accepted": accepted,
        "skipped": skipped,
        "missing_signal": missing_signal,
        "by_reason": dict(by_reason),
        "by_spread_regime": dict(by_regime),
        "by_reason_spread_regime": dict(by_reason_regime),
        "by_reason_codes": dict(by_reason_codes),
        "impact_exhausted_skips": exhausted,
        "risk_consume": {
            "max_impact_enabled": False,
            "min_top_depth_enabled": False,
            "note": "Parte 45 depth/impact vetoes stay default-off; this rollup is audit only.",
        },
    }
    cleaned = redact(payload)
    return cleaned if isinstance(cleaned, dict) else payload


def format_skip_audit(report: dict[str, Any]) -> str:
    lines = [
        f"skip-audit skipped={report.get('skipped')} accepted={report.get('accepted')} "
        f"missing_signal={report.get('missing_signal')} exhausted={report.get('impact_exhausted_skips')} "
        f"production_changed={report.get('production_changed')}"
    ]
    reasons = report.get("by_reason") or {}
    for reason, count in sorted(reasons.items(), key=lambda item: (-int(item[1]), str(item[0]))):
        lines.append(f"  reason {reason}={count}")
    regimes = report.get("by_reason_spread_regime") or {}
    for key, count in sorted(regimes.items(), key=lambda item: (-int(item[1]), str(item[0]))):
        lines.append(f"  slice {key}={count}")
    return "\n".join(lines)
