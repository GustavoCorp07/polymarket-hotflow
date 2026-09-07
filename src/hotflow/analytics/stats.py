"""Small stats helpers. Stay out of backtest/pipeline import cycles."""

from __future__ import annotations

from typing import Any

from hotflow.reason_codes import ReasonCode


def mean(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


def max_drawdown(equity: list[float]) -> float:
    peak = equity[0] if equity else 0.0
    worst = 0.0
    for value in equity:
        peak = max(peak, value)
        if peak > 0:
            worst = max(worst, (peak - value) / peak)
    return worst


def profit_factor(pnls: list[float]) -> float:
    wins = sum(item for item in pnls if item > 0)
    losses = abs(sum(item for item in pnls if item < 0))
    if losses == 0:
        return float("inf") if wins > 0 else 0.0
    return wins / losses


def refuse_max_abs_pnl_selection(metric: str) -> dict[str, Any] | None:
    key = metric.strip().lower().replace("-", "_")
    if key in {"abs_pnl", "pnl", "absolute_pnl", "max_pnl", "best_pnl"}:
        return {
            "refused": True,
            "reason": ReasonCode.MAX_ABS_PNL_SELECTION_REFUSED,
            "metric": metric,
            "selection_rule": "refuses_max_abs_pnl",
        }
    return None
