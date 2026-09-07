"""Parte 44 — basic filter before spending resources."""

from __future__ import annotations

from hotflow.config import ScannerConfig
from hotflow.reason_codes import ReasonCode
from hotflow.types import MarketRecord


def basic_filter_reason(market: MarketRecord, cfg: ScannerConfig) -> str | None:
    if not market.market_id:
        return ReasonCode.BROKEN_MARKET
    if cfg.exclude_closed and market.closed:
        return ReasonCode.BROKEN_MARKET
    if market.archived:
        return ReasonCode.BROKEN_MARKET
    if cfg.require_accepting_orders and market.accepting_orders is False:
        return ReasonCode.NOT_ACCEPTING_ORDERS
    if cfg.require_enable_order_book and market.enable_order_book is False:
        return ReasonCode.UNSUPPORTED_STRUCTURE
    if market.liquidity is not None and market.liquidity < cfg.min_liquidity:
        return ReasonCode.LOW_LIQUIDITY
    if market.volume_24hr is not None and market.volume_24hr < cfg.min_volume_24h:
        return ReasonCode.LOW_LIQUIDITY
    if market.spread is not None and market.spread > cfg.max_spread:
        return ReasonCode.SPREAD_TOO_LARGE
    return None
