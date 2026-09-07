"""Parte 22 — edge/confidence/liquidity sizing. Capped fractional Kelly. No martingale."""

from __future__ import annotations

from hotflow.config import RiskConfig, SizingConfig
from hotflow.types import EdgeBreakdown


def size_notional(
    edge: EdgeBreakdown,
    *,
    bankroll: float,
    liquidity: float | None,
    sizing: SizingConfig,
    risk: RiskConfig,
) -> float:
    if edge.net_expected_edge <= 0 or edge.confidence <= 0:
        return 0.0
    variance = max(sizing.variance_floor, edge.p_fair * (1.0 - edge.p_fair))
    raw_kelly = edge.net_expected_edge / variance
    frac = max(0.0, min(sizing.max_kelly, sizing.kelly_fraction * raw_kelly * edge.confidence))
    notional = bankroll * frac
    if liquidity is not None:
        notional = min(notional, max(0.0, liquidity * sizing.book_frac))
    return min(notional, risk.max_order_notional)
