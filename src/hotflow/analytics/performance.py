"""Parte 52 — performance review from extracted trades only."""

from __future__ import annotations

from typing import Any

from hotflow.analytics.pnl_velocity import pnl_velocity
from hotflow.analytics.stats import max_drawdown, mean, profit_factor
from hotflow.analytics.trades import TradeExtract

SMALL_SAMPLE = 10
STRONG_SAMPLE = 50


def _mean(values: list[float]) -> float | None:
    return mean(values)


def sample_caveat(n: int) -> dict[str, Any]:
    if n <= 0:
        return {
            "n": 0,
            "caveat": "empty_sample",
            "strong_conclusion": False,
            "detail": "no closed trades; nothing invented",
        }
    if n < SMALL_SAMPLE:
        return {
            "n": n,
            "caveat": "too_small_for_inference",
            "strong_conclusion": False,
            "detail": "do not draw strong conclusions from tiny samples",
        }
    if n < STRONG_SAMPLE:
        return {
            "n": n,
            "caveat": "small_sample_no_strong_conclusion",
            "strong_conclusion": False,
            "detail": f"n<{STRONG_SAMPLE}; treat metrics as descriptive only",
        }
    return {
        "n": n,
        "caveat": None,
        "strong_conclusion": True,
        "detail": "sample meets the 50-trade descriptive bar; still not a LIVE promotion",
    }


def half_life_bucket(ms: float | None) -> str:
    if ms is None:
        return "N/A"
    if ms < 1_000:
        return "<1s"
    if ms < 5_000:
        return "1-5s"
    if ms < 30_000:
        return "5-30s"
    return ">=30s"


def review_extract(extract: TradeExtract) -> dict[str, Any]:
    trades = extract.trades
    pnls = extract.pnls
    n = len(pnls)
    fees = [row.fee for row in trades if row.fee is not None]
    slips = [row.slippage for row in trades if row.slippage is not None]
    holdings = [row.holding_s for row in trades if row.holding_s is not None]
    maes = [row.mae for row in trades if row.mae is not None]
    mfes = [row.mfe for row in trades if row.mfe is not None]
    styles = [row.style for row in trades if row.style]
    net = sum(pnls) if pnls else 0.0
    fee_total = sum(fees) if fees else extract.session_fees
    gross = (net + fee_total) if fee_total is not None else None
    stamps = [row.ts for row in trades if row.ts is not None]
    hours = None
    pnl_per_hour = None
    if len(stamps) >= 2:
        span = (max(stamps) - min(stamps)).total_seconds() / 3600.0
        if span > 1e-9:
            hours = span
            pnl_per_hour = net / span
    start = extract.starting_cash if extract.starting_cash is not None else 0.0
    equity = [start]
    running = start
    for pnl in pnls:
        running += pnl
        equity.append(running)
    drawdown = extract.session_drawdown
    if drawdown is None:
        drawdown = max_drawdown(equity) if len(equity) > 1 else 0.0
    pf = profit_factor(pnls) if pnls else 0.0
    pf_out: float | None
    pf_note = None
    if pf == float("inf"):
        pf_out = None
        pf_note = "undefined_no_losses"
    else:
        pf_out = pf
    variance = 0.0
    if len(pnls) >= 2:
        mu = sum(pnls) / len(pnls)
        variance = sum((item - mu) ** 2 for item in pnls) / (len(pnls) - 1)
    avg_hold = _mean(holdings)
    holding_ms = avg_hold * 1000.0 if avg_hold is not None else None
    velocity = None
    velocity_note = "N/A"
    if pnls and holding_ms is not None:
        velocity = pnl_velocity(_mean(pnls) or 0.0, holding_ms, variance)
        velocity_note = "from_mean_holding"
    elif pnls and extract.signal_half_life_ms is not None:
        velocity = pnl_velocity(_mean(pnls) or 0.0, extract.signal_half_life_ms, max(variance, 1e-6))
        velocity_note = "used_metadata_half_life_not_estimated"
    maker = sum(1 for style in styles if style.upper() == "MAKER")
    taker = sum(1 for style in styles if style.upper() == "TAKER")
    return {
        "mode": "paper",
        "live": False,
        "strategy_id": extract.strategy_id,
        "session_id": extract.session_id,
        "source_kind": extract.source_kind,
        "sample": sample_caveat(n),
        "gross_pnl": gross,
        "net_pnl": net if pnls else None,
        "fees": fee_total,
        "slippage": sum(slips) if slips else None,
        "pnl_per_trade": _mean(pnls),
        "pnl_per_hour": pnl_per_hour,
        "hours_observed": hours,
        "pnl_velocity": velocity,
        "pnl_velocity_note": velocity_note,
        "win_rate": (sum(1 for item in pnls if item > 0) / n) if n else None,
        "profit_factor": pf_out,
        "profit_factor_note": pf_note,
        "max_drawdown": drawdown,
        "mae": _mean(maes),
        "mfe": _mean(mfes),
        "avg_holding_s": _mean(holdings),
        "maker_count": maker if styles else None,
        "taker_count": taker if styles else None,
        "maker_fill_rate": (maker / len(styles)) if styles else None,
        "half_life": {
            "metadata_ms": extract.signal_half_life_ms,
            "bucket": half_life_bucket(extract.signal_half_life_ms),
            "estimated_from_trades": None,
            "note": "N/A unless strategy metadata provides signal_half_life_ms",
        },
        "abs_pnl": net if pnls else None,
        "abs_pnl_not_a_selection_metric": True,
        "notes": list(extract.notes),
        "unavailable": [
            name
            for name, value in (
                ("slippage", slips),
                ("mae", maes),
                ("mfe", mfes),
                ("holding", holdings),
                ("style", styles),
            )
            if not value
        ],
    }
