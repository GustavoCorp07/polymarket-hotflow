"""Dynamic universe scanner: Gamma metadata + public CLOB books/fees."""

from __future__ import annotations

import logging
from typing import Any

from hotflow.config import HotflowConfig, ScannerConfig
from hotflow.discovery.clob import ClobPublicClient
from hotflow.discovery.filters import basic_filter_reason
from hotflow.discovery.gamma import GammaClient, as_bool, as_float, parse_json_list, tag_labels
from hotflow.discovery.resolution import parse_resolution
from hotflow.types import FeeSchedule, MarketRecord

log = logging.getLogger("hotflow.discovery")


def infer_category(tags: list[str], gamma_category: str | None) -> str:
    blob = " ".join([*(t.lower() for t in tags), (gamma_category or "").lower()])
    if any(word in blob for word in ("esport", "cs2", "dota", "lol", "valorant")):
        return "esports"
    if any(word in blob for word in ("sport", "nba", "nfl", "mlb", "soccer", "fifa")):
        return "sports"
    if "weather" in blob or "temperature" in blob:
        return "weather"
    if any(word in blob for word in ("crypto", "bitcoin", "btc", "eth", "up or down")):
        return "crypto"
    if gamma_category:
        return gamma_category.lower()
    return "other"


def market_from_gamma(raw: dict[str, Any]) -> MarketRecord:
    tags = tag_labels(raw.get("tags"))
    category = infer_category(tags, raw.get("category"))
    fees_enabled = as_bool(raw.get("feesEnabled"))
    raw_schedule = raw.get("feeSchedule")
    schedule: dict[str, Any] = raw_schedule if isinstance(raw_schedule, dict) else {}
    rate = as_float(schedule.get("rate"))
    fees = FeeSchedule(
        enabled=fees_enabled,
        rate=rate,
        exponent=as_float(schedule.get("exponent")),
        taker_only=as_bool(schedule.get("takerOnly")),
        rebate_rate=as_float(schedule.get("rebateRate")),
        maker_base_fee_bp=raw.get("makerBaseFee"),
        taker_base_fee_bp=raw.get("takerBaseFee"),
        source="gamma",
    )
    bid = as_float(raw.get("bestBid"))
    ask = as_float(raw.get("bestAsk"))
    spread = as_float(raw.get("spread"))
    if spread is None and bid is not None and ask is not None:
        spread = max(0.0, ask - bid)
    return MarketRecord(
        market_id=str(raw.get("id") or raw.get("conditionId") or ""),
        condition_id=raw.get("conditionId") or raw.get("condition_id"),
        slug=raw.get("slug"),
        question=raw.get("question"),
        category=category,
        tags=tags,
        token_ids=parse_json_list(raw.get("clobTokenIds")),
        outcomes=parse_json_list(raw.get("outcomes")),
        active=as_bool(raw.get("active")),
        closed=as_bool(raw.get("closed")),
        archived=as_bool(raw.get("archived")),
        enable_order_book=as_bool(raw.get("enableOrderBook")),
        accepting_orders=as_bool(raw.get("acceptingOrders")),
        liquidity=as_float(raw.get("liquidityNum") if raw.get("liquidityNum") is not None else raw.get("liquidity")),
        volume=as_float(raw.get("volumeNum") if raw.get("volumeNum") is not None else raw.get("volume")),
        volume_24hr=as_float(raw.get("volume24hr")),
        best_bid=bid,
        best_ask=ask,
        spread=spread,
        last_trade_price=as_float(raw.get("lastTradePrice")),
        competitive=as_float(raw.get("competitive")),
        order_min_size=as_float(raw.get("orderMinSize")),
        tick_size=as_float(raw.get("orderPriceMinTickSize")),
        fees=fees,
        resolution=parse_resolution(raw),
        raw_gamma={
            k: raw[k]
            for k in (
                "id",
                "conditionId",
                "slug",
                "question",
                "description",
                "resolutionSource",
                "line",
                "endDate",
                "feesEnabled",
                "acceptingOrders",
                "enableOrderBook",
            )
            if k in raw
        },
    )


def is_eligible(market: MarketRecord, cfg: ScannerConfig) -> bool:
    if basic_filter_reason(market, cfg) is not None:
        return False
    if cfg.include_tags:
        wanted = {tag.lower() for tag in cfg.include_tags}
        have = {tag.lower() for tag in market.tags}
        if wanted.isdisjoint(have):
            return False
    return True


class UniverseScanner:
    def __init__(
        self,
        config: HotflowConfig,
        gamma: GammaClient | None = None,
        clob: ClobPublicClient | None = None,
    ) -> None:
        self.config = config
        self.gamma = gamma
        self.clob = clob

    async def scan(self, *, use_network: bool = True) -> list[MarketRecord]:
        cfg = self.config.scanner
        if not use_network and self.gamma is None:
            return []
        gamma = self.gamma or GammaClient()
        clob = self.clob or ClobPublicClient()
        owns_gamma = self.gamma is None
        owns_clob = self.clob is None
        markets: list[MarketRecord] = []
        try:
            if owns_gamma:
                await gamma.__aenter__()
            if owns_clob and (cfg.fetch_clob_books or cfg.fetch_clob_fees):
                await clob.__aenter__()
            try:
                raw_rows = await gamma.list_markets(
                    closed=cfg.closed,
                    limit=cfg.gamma_limit,
                    offset=cfg.gamma_offset,
                )
            except Exception as exc:  # noqa: BLE001 — fail safe: empty universe, no invented markets
                log.warning("gamma list failed err=%s", type(exc).__name__)
                return []
            for raw in raw_rows:
                record = market_from_gamma(raw)
                if not is_eligible(record, cfg):
                    continue
                if cfg.fetch_clob_books and record.token_ids:
                    try:
                        book = await clob.get_book(record.token_ids[0], record.condition_id)
                        record.book = book
                        if book.best_bid is not None:
                            record.best_bid = book.best_bid
                        if book.best_ask is not None:
                            record.best_ask = book.best_ask
                        if book.spread is not None:
                            record.spread = book.spread
                        if book.min_order_size is not None:
                            record.order_min_size = book.min_order_size
                        if book.tick_size is not None:
                            record.tick_size = book.tick_size
                    except Exception as exc:  # noqa: BLE001 — public scan continues
                        log.warning("book fetch failed market=%s err=%s", record.market_id, type(exc).__name__)
                if cfg.fetch_clob_fees and record.token_ids:
                    try:
                        bp = await clob.get_fee_rate(record.token_ids[0])
                        if bp is not None:
                            record.fees.clob_base_fee_bp = bp
                            record.fees.source = f"{record.fees.source}+clob_fee_rate"
                    except Exception as exc:  # noqa: BLE001
                        log.warning("fee-rate fetch failed market=%s err=%s", record.market_id, type(exc).__name__)
                    if record.condition_id:
                        try:
                            bundle = await clob.get_clob_market(record.condition_id)
                            clob_fees = clob.fee_from_clob_market(bundle)
                            if clob_fees.rate is not None:
                                record.fees.rate = clob_fees.rate
                                record.fees.exponent = clob_fees.exponent
                                record.fees.taker_only = clob_fees.taker_only
                                if record.fees.enabled is None:
                                    record.fees.enabled = clob_fees.enabled
                            if bundle.get("mos") is not None:
                                record.order_min_size = float(bundle["mos"])
                            if bundle.get("mts") is not None:
                                record.tick_size = float(bundle["mts"])
                        except Exception as exc:  # noqa: BLE001
                            log.warning(
                                "clob-markets fetch failed market=%s err=%s",
                                record.market_id,
                                type(exc).__name__,
                            )
                if record.spread is not None and record.spread > cfg.max_spread:
                    continue
                markets.append(record)
                if len(markets) >= cfg.max_markets:
                    break
        finally:
            if owns_clob and clob._client is not None:  # noqa: SLF001
                await clob.__aexit__(None, None, None)
            if owns_gamma and gamma._client is not None:  # noqa: SLF001
                await gamma.__aexit__(None, None, None)
        return markets
