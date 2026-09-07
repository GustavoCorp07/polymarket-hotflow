"""Paper pipeline: scan → HMS → fair value → risk → paper (no LLM)."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from hotflow.config import HotflowConfig
from hotflow.discovery.scanner import UniverseScanner, infer_category
from hotflow.execution.live_gate import live_gates_open
from hotflow.execution.paper import PaperBroker
from hotflow.fairvalue.crypto import CryptoFairValue
from hotflow.features.snapshot import build_feature_snapshot
from hotflow.hotmarket.opportunity import score_opportunity
from hotflow.hotmarket.score import score_hot_market
from hotflow.marketdata.freshness import FeedClock
from hotflow.reason_codes import ReasonCode
from hotflow.risk.engine import RiskEngine
from hotflow.risk.kill_switch import KillSwitchBoard
from hotflow.storage.sqlite_store import SqliteStore
from hotflow.types import (
    BookLevel,
    KillSwitchReason,
    MarketRecord,
    OrderBook,
    Side,
    SignalAudit,
)


def _category_enabled(config: HotflowConfig, category: str) -> bool:
    toggles = config.trading.categories.model_dump()
    key = category if category in toggles else "other"
    return bool(toggles.get(key, toggles.get("other", True)))


def _resolution_unknown(market: MarketRecord) -> bool:
    meta = market.resolution
    return not (meta.source or meta.uma_status or meta.end_date or meta.resolved_by)


def _intended_shares(market: MarketRecord, config: HotflowConfig) -> float:
    min_size = market.order_min_size or (market.book.min_order_size if market.book else None) or 5.0
    return float(min_size)


class PaperPipeline:
    def __init__(self, config: HotflowConfig, store: SqliteStore | None = None) -> None:
        self.config = config
        self.kills = KillSwitchBoard()
        self.risk = RiskEngine(config.risk, self.kills)
        self.broker = PaperBroker(config.trading)
        self.fair = CryptoFairValue()
        self.clock = FeedClock(config.feeds)
        self.store = store
        self.audits: list[SignalAudit] = []

    def _audit(self, **kwargs: Any) -> SignalAudit:
        row = SignalAudit(session_id=self.config.trading.session_id, **kwargs)
        self.audits.append(row)
        if self.store:
            self.store.save_signal(row)
        return row

    def _on_stale_critical(self, feeds: list[str]) -> None:
        self.kills.trip(KillSwitchReason.STALE_CRITICAL_DATA, ",".join(feeds))
        self.broker.cancel_open()

    def evaluate_market(
        self,
        market: MarketRecord,
        *,
        latency_ms: float = 50.0,
        p_info: float | None = None,
    ) -> dict[str, Any]:
        now = datetime.now(UTC)
        self.clock.touch("gamma", observed_at=market.fetched_at)
        if market.book:
            self.clock.touch("clob_book", observed_at=market.book.fetched_at)
        if market.fees.known:
            self.clock.touch("clob_fees", observed_at=market.fees.fetched_at)

        stale = self.clock.critical_stale(now)
        if stale:
            self._on_stale_critical(stale)
            self._audit(
                market_id=market.market_id,
                accepted=False,
                reason=ReasonCode.STALE_DATA,
                detail=",".join(stale),
            )
            return {"accepted": False, "reason": ReasonCode.STALE_DATA}

        category = infer_category(market.tags, market.category)
        if not _category_enabled(self.config, category):
            self._audit(market_id=market.market_id, accepted=False, reason=ReasonCode.CATEGORY_DISABLED)
            return {"accepted": False, "reason": ReasonCode.CATEGORY_DISABLED}

        if market.accepting_orders is False:
            self._audit(market_id=market.market_id, accepted=False, reason=ReasonCode.NOT_ACCEPTING_ORDERS)
            return {"accepted": False, "reason": ReasonCode.NOT_ACCEPTING_ORDERS}

        if _resolution_unknown(market):
            self._audit(market_id=market.market_id, accepted=False, reason=ReasonCode.UNKNOWN_RESOLUTION)
            return {"accepted": False, "reason": ReasonCode.UNKNOWN_RESOLUTION}

        hms = score_hot_market(market, self.config.hot_market)
        snap = build_feature_snapshot(market, hms)
        if self.store:
            self.store.save_feature(market.market_id, snap.model_dump(mode="json"))

        if hms.score < self.config.hot_market.min_score_to_trade:
            self._audit(
                market_id=market.market_id,
                accepted=False,
                reason=ReasonCode.MARKET_NOT_HOT,
                hms=hms.score,
                tier=hms.tier.value,
            )
            return {"accepted": False, "reason": ReasonCode.MARKET_NOT_HOT, "hms": hms.score}

        token_id = market.token_ids[0] if market.token_ids else "unknown"
        shares = _intended_shares(market, self.config)
        edge = self.fair.evaluate(
            market,
            side=Side.BUY,
            shares=shares,
            min_required_edge=self.config.trading.min_required_edge,
            config=self.config.fair_value,
            p_info=p_info,
        )
        if edge.skip:
            self._audit(
                market_id=market.market_id,
                accepted=False,
                reason=edge.reason or ReasonCode.NO_TRADE,
                hms=hms.score,
                tier=hms.tier.value,
                net_edge=edge.net_expected_edge,
            )
            return {"accepted": False, "reason": edge.reason, "edge": edge.model_dump()}

        opp = score_opportunity(
            market=market,
            hms=hms,
            edge=edge,
            side=Side.BUY,
            token_id=token_id,
            shares=shares,
            cfg=self.config.opportunity,
        )
        age = self.clock.age_ms("clob_book") if market.book else self.clock.age_ms("gamma")
        decision = self.risk.decide(
            opp,
            category=category,
            spread=market.spread,
            data_age_ms=age,
            latency_ms=latency_ms,
            now=now,
        )
        if self.store:
            self.store.save_risk(market.market_id, decision)
        if not decision.allowed:
            self.risk.note_reject()
            self._audit(
                market_id=market.market_id,
                accepted=False,
                reason=decision.reason,
                detail=decision.detail,
                hms=hms.score,
                net_edge=edge.net_expected_edge,
                opportunity_score=opp.score,
            )
            return {"accepted": False, "reason": decision.reason, "detail": decision.detail}

        if self.config.trading.shadow:
            self._audit(
                market_id=market.market_id,
                accepted=False,
                reason=ReasonCode.SHADOW_MODE,
                hms=hms.score,
                net_edge=edge.net_expected_edge,
                opportunity_score=opp.score,
            )
            return {"accepted": False, "reason": ReasonCode.SHADOW_MODE, "opportunity": opp.model_dump()}

        if not self.config.is_paper and not live_gates_open(self.config):
            self._audit(market_id=market.market_id, accepted=False, reason=ReasonCode.LIVE_GATES_BLOCKED)
            return {"accepted": False, "reason": ReasonCode.LIVE_GATES_BLOCKED}

        order = self.broker.create(opp, price=edge.market_price, size=shares)
        order = self.broker.submit(order.client_order_id)
        filled_before = order.filled_size
        order = self.broker.simulate_fill(order.client_order_id)
        self.risk.state.open_orders = sum(
            1
            for o in self.broker.orders.values()
            if o.status.value in {"SUBMITTED", "ACKNOWLEDGED", "PARTIAL"}
        )
        self.risk.state.last_order_at = now
        self.risk.note_fill(
            market_id=market.market_id,
            category=category,
            notional=order.filled_size * (order.avg_fill_price or order.price),
        )
        if self.store:
            self.store.save_order(order)
            delta = order.filled_size - filled_before
            if delta > 0:
                self.store.save_trade(order, delta, order.avg_fill_price or order.price)
        self._audit(
            market_id=market.market_id,
            accepted=True,
            reason=ReasonCode.OK,
            hms=hms.score,
            tier=hms.tier.value,
            net_edge=edge.net_expected_edge,
            opportunity_score=opp.score,
            extra={"client_order_id": order.client_order_id, "status": order.status.value},
        )
        return {"accepted": True, "reason": ReasonCode.OK, "order": order.model_dump(mode="json")}

    async def run_scan(
        self,
        *,
        scanner: UniverseScanner | None = None,
        markets: list[MarketRecord] | None = None,
        use_network: bool = True,
    ) -> dict[str, Any]:
        if markets is None:
            scanner = scanner or UniverseScanner(self.config)
            try:
                markets = await scanner.scan(use_network=use_network)
            except Exception as exc:  # noqa: BLE001
                return {"ok": False, "error": type(exc).__name__, "markets": 0, "audits": []}
        results = [self.evaluate_market(m) for m in markets]
        return {
            "ok": True,
            "mode": self.config.trading.mode,
            "markets": len(markets),
            "accepted": sum(1 for r in results if r.get("accepted")),
            "results": results,
            "audits": [a.model_dump(mode="json") for a in self.audits],
        }


def write_report(path: Path, payload: dict[str, Any]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    return path


def demo_market(*, hot: bool = True, fees_enabled: bool = True, rate: float = 0.04) -> MarketRecord:
    """Deterministic market for offline paper-run / tests (not live prices)."""
    from hotflow.types import FeeSchedule, ResolutionMeta

    if hot:
        asks = [BookLevel(price=0.42, size=80.0), BookLevel(price=0.44, size=120.0)]
        bids = [BookLevel(price=0.40, size=90.0), BookLevel(price=0.38, size=100.0)]
        liq, vol, spread, bid, ask, competitive = 25_000.0, 12_000.0, 0.02, 0.40, 0.42, 0.7
    else:
        asks = [BookLevel(price=0.55, size=5.0)]
        bids = [BookLevel(price=0.30, size=5.0)]
        liq, vol, spread, bid, ask, competitive = 10.0, 1.0, 0.25, 0.30, 0.55, 0.05
    return MarketRecord(
        market_id="demo-btc-updown",
        condition_id="0xdemo",
        slug="demo-btc-updown",
        question="Demo BTC up/down (fixture, not a live market)",
        category="crypto",
        tags=["crypto", "btc"],
        token_ids=["demo-yes"],
        outcomes=["Yes", "No"],
        active=True,
        closed=False,
        enable_order_book=True,
        accepting_orders=True,
        liquidity=liq,
        volume=vol * 3,
        volume_24hr=vol,
        best_bid=bid,
        best_ask=ask,
        spread=spread,
        competitive=competitive,
        order_min_size=5.0,
        tick_size=0.01,
        fees=FeeSchedule(enabled=fees_enabled, rate=rate, exponent=1.0, taker_only=True, source="fixture"),
        resolution=ResolutionMeta(source="demo-fixture", end_date="2099-01-01T00:00:00Z"),
        book=OrderBook(
            token_id="demo-yes",
            condition_id="0xdemo",
            bids=bids,
            asks=asks,
            min_order_size=5.0,
            tick_size=0.01,
        ),
    )
