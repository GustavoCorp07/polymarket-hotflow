"""Parte 53 — alpha decay vs baseline. Suggestion-only; no auto-disable."""

from __future__ import annotations

import random
from typing import Any

from hotflow.analytics.performance import SMALL_SAMPLE, _mean, sample_caveat

DEFAULT_WINDOWS = (50, 100, 500)
BOOTSTRAP_DRAWS = 200


def _stderr(values: list[float]) -> float | None:
    if len(values) < 2:
        return None
    mu = sum(values) / len(values)
    var = sum((item - mu) ** 2 for item in values) / (len(values) - 1)
    return (var / len(values)) ** 0.5


def _bootstrap_diff(
    recent: list[float],
    baseline: list[float],
    *,
    draws: int = BOOTSTRAP_DRAWS,
    seed: int = 7,
) -> dict[str, Any]:
    rng = random.Random(seed)
    diffs: list[float] = []
    for _ in range(max(1, draws)):
        r = sum(rng.choice(recent) for _ in recent) / len(recent)
        b = sum(rng.choice(baseline) for _ in baseline) / len(baseline)
        diffs.append(r - b)
    diffs.sort()
    lo_i = max(0, int(0.05 * (len(diffs) - 1)))
    hi_i = min(len(diffs) - 1, int(0.95 * (len(diffs) - 1)))
    return {
        "mean_diff": sum(diffs) / len(diffs),
        "ci_low": diffs[lo_i],
        "ci_high": diffs[hi_i],
        "draws": draws,
        "method": "bootstrap_lite_percentile",
    }


def _window(pnls: list[float], size: int) -> dict[str, Any]:
    n = len(pnls)
    take = min(size, n)
    recent = pnls[-take:] if take else []
    baseline = pnls[:-take] if take and n > take else []
    sample = sample_caveat(len(recent))
    row: dict[str, Any] = {
        "window": size,
        "requested": size,
        "clipped": take < size,
        "n_recent": len(recent),
        "n_baseline": len(baseline),
        "recent_mean": _mean(recent),
        "baseline_mean": _mean(baseline),
        "recent_stderr": _stderr(recent),
        "baseline_stderr": _stderr(baseline),
        "sample": sample,
        "degraded": False,
        "flag": "insufficient_sample",
        "auto_disable": False,
        "suggestion_only": True,
    }
    if not recent or not baseline:
        row["detail"] = "need both a recent window and an earlier baseline"
        return row
    boot = _bootstrap_diff(recent, baseline)
    row["bootstrap"] = boot
    mean_diff = (row["recent_mean"] or 0.0) - (row["baseline_mean"] or 0.0)
    row["mean_diff"] = mean_diff
    se_r = row["recent_stderr"]
    se_b = row["baseline_stderr"]
    if se_r is not None and se_b is not None:
        row["diff_stderr"] = (se_r**2 + se_b**2) ** 0.5
    if len(recent) < SMALL_SAMPLE or len(baseline) < SMALL_SAMPLE:
        row["flag"] = "possible_degradation_low_confidence" if mean_diff < 0 else "no_strong_signal"
        row["detail"] = "small sample; no strong decay conclusion"
        return row
    if boot["ci_high"] < 0:
        row["degraded"] = True
        row["flag"] = "degradation_suggested"
        row["detail"] = "recent mean below baseline; 90% bootstrap CI does not include 0"
    elif mean_diff < 0:
        row["flag"] = "weaker_recent_not_significant"
        row["detail"] = "recent mean is lower but CI still crosses 0"
    else:
        row["flag"] = "no_decay_detected"
        row["detail"] = "recent mean is not below baseline on this window"
    return row


def decay_report(pnls: list[float], *, windows: tuple[int, ...] = DEFAULT_WINDOWS) -> dict[str, Any]:
    windows_out = [_window(pnls, size) for size in windows]
    flagged = [row for row in windows_out if row.get("degraded")]
    any_flag = bool(flagged)
    return {
        "windows": windows_out,
        "any_degradation_suggested": any_flag,
        "auto_disable": False,
        "suggestion_only": True,
        "production_change": False,
        "note": "Decay is informational. Do not disable strategies or open LIVE from this report.",
        "sample": sample_caveat(len(pnls)),
    }
