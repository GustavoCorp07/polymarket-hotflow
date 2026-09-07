"""Backtest report metrics. Absolute PnL is recorded but is not a selection key."""

from __future__ import annotations

from typing import Any

from hotflow.reason_codes import ReasonCode


def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


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


def summarize_trades(
    trades: list[dict[str, Any]],
    *,
    equity: list[float],
    skip_counts: dict[str, int],
    fees_total: float,
    slippage_total: float,
) -> dict[str, Any]:
    pnls = [float(item.get("pnl") or 0.0) for item in trades]
    wins = [item for item in pnls if item > 0]
    losses = [item for item in pnls if item < 0]
    return {
        "expectancy": _mean(pnls),
        "max_drawdown": max_drawdown(equity),
        "fees": fees_total,
        "slippage": slippage_total,
        "trade_count": len(trades),
        "skip_counts": dict(skip_counts),
        "win_rate": (len(wins) / len(pnls)) if pnls else 0.0,
        "avg_win": _mean(wins),
        "avg_loss": _mean(losses),
        "profit_factor": profit_factor(pnls),
        "abs_pnl": sum(pnls),
        "abs_pnl_not_a_selection_metric": True,
        "tail_loss": min(pnls) if pnls else 0.0,
    }


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


def rank_reports(reports: list[dict[str, Any]], *, metric: str = "expectancy") -> dict[str, Any]:
    blocked = refuse_max_abs_pnl_selection(metric)
    if blocked:
        return blocked
    scored: list[tuple[float, float, int, dict[str, Any]]] = []
    for row in reports:
        raw_metrics = row.get("metrics")
        metrics: dict[str, Any] = raw_metrics if isinstance(raw_metrics, dict) else row
        expectancy = float(metrics.get("expectancy") or 0.0)
        drawdown = abs(float(metrics.get("max_drawdown") or 0.0))
        trades = int(metrics.get("trade_count") or 0)
        scored.append((expectancy, -drawdown, trades, row))
    scored.sort(key=lambda item: (item[0], item[1], item[2]), reverse=True)
    winner = scored[0][3] if scored else None
    return {
        "refused": False,
        "metric": "expectancy",
        "selection_rule": "expectancy_then_drawdown_then_trade_count",
        "ranked": [item[3].get("backtest_id") or item[3].get("label") for item in scored],
        "selected": (winner or {}).get("backtest_id") or (winner or {}).get("label"),
    }
