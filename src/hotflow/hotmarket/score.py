"""Hot Market Score 0–100 and COLD/WARM/HOT/ULTRA-HOT tiers."""

from __future__ import annotations

import math

from hotflow.config import HotMarketConfig
from hotflow.features.time_features import time_to_resolution_seconds, urgency_score
from hotflow.types import HotMarketResult, MarketRecord, ResourceTier


def _log_scale(value: float | None, ref: float) -> float:
    if value is None or value <= 0 or ref <= 0:
        return 0.0
    return max(0.0, min(1.0, math.log10(1.0 + value) / math.log10(1.0 + ref)))


def _spread_score(spread: float | None, max_spread: float) -> float:
    if spread is None:
        return 0.0
    if max_spread <= 0:
        return 0.0
    return max(0.0, min(1.0, 1.0 - (spread / max_spread)))


def _book_open(market: MarketRecord) -> float:
    if market.accepting_orders is False or market.enable_order_book is False:
        return 0.0
    if market.accepting_orders and market.enable_order_book:
        return 1.0
    if market.accepting_orders or market.enable_order_book:
        return 0.6
    return 0.3


def _persistence(market: MarketRecord) -> float:
    if market.volume_24hr is None or market.volume is None or market.volume <= 0:
        if market.volume_24hr and market.volume_24hr > 0:
            return 0.5
        return 0.0
    ratio = market.volume_24hr / market.volume
    return max(0.0, min(1.0, ratio))


def _competitive(market: MarketRecord) -> float:
    if market.competitive is None:
        return 0.4
    return max(0.0, min(1.0, float(market.competitive)))


def tier_for(score: float, cfg: HotMarketConfig) -> ResourceTier:
    if score >= cfg.tiers.ultra_hot:
        return ResourceTier.ULTRA_HOT
    if score >= cfg.tiers.hot:
        return ResourceTier.HOT
    if score >= cfg.tiers.warm:
        return ResourceTier.WARM
    return ResourceTier.COLD


def score_hot_market(market: MarketRecord, cfg: HotMarketConfig) -> HotMarketResult:
    components = {
        "liquidity": _log_scale(market.liquidity, cfg.liquidity_ref),
        "volume": _log_scale(market.volume_24hr if market.volume_24hr is not None else market.volume, cfg.volume_ref),
        "spread": _spread_score(market.spread, cfg.max_spread_for_full_score),
        "book_open": _book_open(market),
        "competitive": _competitive(market),
        "persistence": _persistence(market),
        "urgency": urgency_score(time_to_resolution_seconds(market)),
    }
    weights = cfg.weights.model_dump()
    total_w = sum(weights.values()) or 1.0
    score = 100.0 * sum(components[name] * (weights[name] / total_w) for name in components)
    score = max(0.0, min(100.0, score))
    return HotMarketResult(
        market_id=market.market_id,
        score=round(score, 4),
        tier=tier_for(score, cfg),
        components=components,
    )
