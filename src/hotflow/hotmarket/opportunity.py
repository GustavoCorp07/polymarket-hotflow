"""Opportunity score after HMS threshold."""

from __future__ import annotations

from hotflow.config import OpportunityConfig
from hotflow.types import EdgeBreakdown, HotMarketResult, MarketRecord, Opportunity, Side


def _clip01(value: float) -> float:
    return max(0.0, min(1.0, value))


def score_opportunity(
    *,
    market: MarketRecord,
    hms: HotMarketResult,
    edge: EdgeBreakdown,
    side: Side,
    token_id: str,
    shares: float,
    cfg: OpportunityConfig,
) -> Opportunity:
    liquidity_factor = _clip01((market.liquidity or 0.0) / 10_000.0)
    persistence = hms.components.get("persistence", 0.0)
    execution_probability = _clip01(0.25 + 0.75 * hms.components.get("book_open", 0.0))
    if edge.slippage > 0.02:
        execution_probability *= 0.7
    w = cfg.weights
    net = max(0.0, edge.net_expected_edge)
    score = (
        (net ** w.expected_net_edge)
        * (edge.confidence ** w.confidence)
        * (max(liquidity_factor, 1e-9) ** w.liquidity)
        * (max(persistence, 1e-9) ** w.persistence)
        * (max(execution_probability, 1e-9) ** w.execution_probability)
    )
    notional = shares * edge.market_price
    return Opportunity(
        market_id=market.market_id,
        token_id=token_id,
        side=side,
        score=float(score),
        hms=hms,
        edge=edge,
        liquidity_factor=liquidity_factor,
        persistence=persistence,
        execution_probability=execution_probability,
        intended_shares=shares,
        intended_notional=notional,
    )
