"""Crypto-oriented fair value: P(outcome|info), RAW_EDGE, NET after costs."""

from __future__ import annotations

from hotflow.config import FairValueConfig
from hotflow.fairvalue.fees import UnknownFeesError, taker_fee_per_share, walk_slippage
from hotflow.reason_codes import ReasonCode
from hotflow.types import EdgeBreakdown, MarketRecord, Side


def _clip_prob(value: float) -> float:
    return max(1e-6, min(1.0 - 1e-6, value))


class CryptoFairValue:
    name = "crypto"

    def implied_mid(self, market: MarketRecord) -> float | None:
        if market.book and market.book.mid is not None:
            return market.book.mid
        if market.best_bid is not None and market.best_ask is not None:
            return (market.best_bid + market.best_ask) / 2.0
        return None

    def p_outcome(
        self,
        market: MarketRecord,
        *,
        config: FairValueConfig,
        p_info: float | None = None,
    ) -> float | None:
        mid = self.implied_mid(market)
        if p_info is not None:
            if mid is None:
                return _clip_prob(p_info)
            blend = config.crypto.prior_blend
            return _clip_prob((1.0 - blend) * p_info + blend * mid)
        if mid is None:
            return None
        return _clip_prob(mid)

    def evaluate(
        self,
        market: MarketRecord,
        *,
        side: Side,
        shares: float,
        min_required_edge: float,
        config: FairValueConfig,
        p_info: float | None = None,
    ) -> EdgeBreakdown:
        book = market.book
        bid = book.best_bid if book else market.best_bid
        ask = book.best_ask if book else market.best_ask
        if bid is None or ask is None:
            return EdgeBreakdown(
                p_fair=0.0,
                market_price=0.0,
                raw_edge=0.0,
                fee_per_share=0.0,
                spread_cost=0.0,
                slippage=0.0,
                latency_haircut=config.latency_haircut,
                adverse_selection=config.adverse_selection_haircut,
                fill_penalty=config.fill_penalty,
                net_expected_edge=0.0,
                confidence=0.0,
                skip=True,
                reason=ReasonCode.NO_BOOK,
            )
        p_fair = self.p_outcome(market, config=config, p_info=p_info)
        if p_fair is None:
            return EdgeBreakdown(
                p_fair=0.0,
                market_price=ask if side == Side.BUY else bid,
                raw_edge=0.0,
                fee_per_share=0.0,
                spread_cost=(ask - bid) / 2.0,
                slippage=0.0,
                latency_haircut=config.latency_haircut,
                adverse_selection=config.adverse_selection_haircut,
                fill_penalty=config.fill_penalty,
                net_expected_edge=0.0,
                confidence=0.0,
                skip=True,
                reason=ReasonCode.NO_TRADE,
            )
        market_price = ask if side == Side.BUY else bid
        raw_edge = (p_fair - market_price) if side == Side.BUY else (market_price - p_fair)
        try:
            fee = taker_fee_per_share(market_price, market.fees)
        except UnknownFeesError:
            return EdgeBreakdown(
                p_fair=p_fair,
                market_price=market_price,
                raw_edge=raw_edge,
                fee_per_share=0.0,
                spread_cost=(ask - bid) / 2.0,
                slippage=0.0,
                latency_haircut=config.latency_haircut,
                adverse_selection=config.adverse_selection_haircut,
                fill_penalty=config.fill_penalty,
                net_expected_edge=0.0,
                confidence=config.default_confidence,
                skip=True,
                reason=ReasonCode.UNKNOWN_FEES,
            )
        if book:
            levels = [(lvl.price, lvl.size) for lvl in (book.asks if side == Side.BUY else book.bids)]
        else:
            levels = [(market_price, shares)]
        slippage = walk_slippage(levels, shares, is_buy=(side == Side.BUY))
        spread_cost = max(0.0, (ask - bid) / 2.0)
        fill_penalty = config.fill_penalty
        net = (
            raw_edge
            - fee
            - spread_cost
            - slippage
            - config.latency_haircut
            - config.adverse_selection_haircut
            - fill_penalty
        )
        skip = net <= min_required_edge
        return EdgeBreakdown(
            p_fair=p_fair,
            market_price=market_price,
            raw_edge=raw_edge,
            fee_per_share=fee,
            spread_cost=spread_cost,
            slippage=slippage,
            latency_haircut=config.latency_haircut,
            adverse_selection=config.adverse_selection_haircut,
            fill_penalty=fill_penalty,
            net_expected_edge=net,
            confidence=config.default_confidence if p_info is None else min(0.85, config.default_confidence + 0.2),
            fee_rate_used=market.fees.rate,
            skip=skip,
            reason=ReasonCode.EDGE_TOO_SMALL if skip else ReasonCode.OK,
        )
