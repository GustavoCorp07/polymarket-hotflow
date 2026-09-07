"""Paper pipeline: scan → HMS → fair value → risk → paper (no LLM)."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from hotflow.analytics.experiments import git_commit
from hotflow.analytics.pnl_velocity import pnl_velocity
from hotflow.analytics.signal_quality import signal_quality
from hotflow.config import HotflowConfig
from hotflow.discovery.resolution import parse_resolution, parse_twap_resolution
from hotflow.discovery.scanner import UniverseScanner, infer_category
from hotflow.execution.live_gate import live_gates_open
from hotflow.execution.paper import PaperBroker
from hotflow.fairvalue.crypto import CryptoFairValue
from hotflow.fairvalue.maker_taker import choose_style
from hotflow.fairvalue.twap import compute_twap_snapshot, time_remaining_seconds, twap_p_info_for_market
from hotflow.features.snapshot import build_feature_snapshot
from hotflow.hotmarket.opportunity import score_opportunity
from hotflow.hotmarket.score import score_hot_market
from hotflow.hotmarket.watchlist import resource_plan
from hotflow.marketdata.freshness import FeedClock
from hotflow.marketdata.rtds_twap import FixtureTwapSource, TwapObservationSource
from hotflow.marketdata.twap_cache import TwapPrintCache, observation_status
from hotflow.portfolio.sizing import size_notional
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
    TwapSnapshot,
)


def _category_enabled(config: HotflowConfig, category: str) -> bool:
    toggles = config.trading.categories.model_dump()
    key = category if category in toggles else "other"
    return bool(toggles.get(key, toggles.get("other", True)))


def make_twap_source(
    config: HotflowConfig,
    *,
    use_twap_fixtures: bool = False,
    twap_source: TwapObservationSource | None = None,
    cache_path: str | Path | None = None,
) -> TwapObservationSource:
    """Fixtures for --mock; otherwise an empty or on-disk official-print cache.

    Never invents a live TWAP. A missing cache is empty until a subscriber
    or `--twap-cache` injects official-shape prints.
    """
    if twap_source is not None:
        return twap_source
    if cache_path:
        return TwapPrintCache.from_path(cache_path, max_age_ms=config.feeds.rtds.max_data_age_ms)
    if use_twap_fixtures:
        return FixtureTwapSource()
    cache = TwapPrintCache(
        max_age_ms=config.feeds.rtds.max_data_age_ms,
        path=config.feeds.rtds.cache_path,
        persist=config.feeds.rtds.persist_cache,
    )
    if config.feeds.rtds.persist_cache:
        cache.load()
    return cache


def _intended_shares(market: MarketRecord, config: HotflowConfig, notional: float, price: float) -> float:
    min_size = market.order_min_size or (market.book.min_order_size if market.book else None) or 5.0
    if price <= 0:
        return float(min_size)
    sized = notional / price
    return max(float(min_size), sized)


class PaperPipeline:
    def __init__(
        self,
        config: HotflowConfig,
        store: SqliteStore | None = None,
        *,
        twap_source: TwapObservationSource | None = None,
        use_twap_fixtures: bool = False,
        cache_path: str | Path | None = None,
    ) -> None:
        self.config = config
        self.kills = KillSwitchBoard()
        self.risk = RiskEngine(config.risk, self.kills)
        self.broker = PaperBroker(config.trading)
        self.fair = CryptoFairValue()
        self.clock = FeedClock(config.feeds)
        self.store = store
        self.audits: list[SignalAudit] = []
        self.twap_source = make_twap_source(
            config,
            use_twap_fixtures=use_twap_fixtures,
            twap_source=twap_source,
            cache_path=cache_path,
        )

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

        if not market.resolution.tradeable:
            self._audit(market_id=market.market_id, accepted=False, reason=ReasonCode.UNKNOWN_RESOLUTION)
            return {"accepted": False, "reason": ReasonCode.UNKNOWN_RESOLUTION}

        twap_spec = parse_twap_resolution(market)
        twap_snap: TwapSnapshot | None = None
        twap_p_info = p_info
        if self.config.fair_value.crypto.twap.enabled and twap_spec.is_twap_market:
            if not twap_spec.complete:
                reason = twap_spec.skip_reason or ReasonCode.UNKNOWN_RESOLUTION
                self._audit(
                    market_id=market.market_id,
                    accepted=False,
                    reason=reason,
                    detail="twap_spec_incomplete",
                    extra={"twap_spec": twap_spec.model_dump()},
                )
                return {"accepted": False, "reason": reason, "twap_spec": twap_spec.model_dump()}
            observation = self.twap_source.latest(twap_spec.symbol or "", twap_spec.window_seconds or 0)
            freshness = observation_status(
                observation,
                max_age_ms=self.config.feeds.rtds.max_data_age_ms,
                now=now,
            )
            if freshness == "missing":
                self._audit(
                    market_id=market.market_id,
                    accepted=False,
                    reason=ReasonCode.TWAP_OBSERVATION_MISSING,
                    extra={"twap_spec": twap_spec.model_dump()},
                )
                return {
                    "accepted": False,
                    "reason": ReasonCode.TWAP_OBSERVATION_MISSING,
                    "twap_spec": twap_spec.model_dump(),
                }
            if freshness == "stale":
                self._audit(
                    market_id=market.market_id,
                    accepted=False,
                    reason=ReasonCode.TWAP_OBSERVATION_STALE,
                    detail="rtds",
                    extra={"twap_spec": twap_spec.model_dump()},
                )
                return {
                    "accepted": False,
                    "reason": ReasonCode.TWAP_OBSERVATION_STALE,
                    "detail": "rtds",
                    "twap_spec": twap_spec.model_dump(),
                }
            assert observation is not None
            remaining = time_remaining_seconds(market.resolution.end_date, now=now)
            if remaining is None:
                self._audit(market_id=market.market_id, accepted=False, reason=ReasonCode.UNKNOWN_RESOLUTION)
                return {"accepted": False, "reason": ReasonCode.UNKNOWN_RESOLUTION}
            twap_snap = compute_twap_snapshot(
                twap_spec,
                observation,
                time_remaining_s=remaining,
                config=self.config.fair_value.crypto.twap,
            )
            self.clock.touch("rtds", observed_at=observation.observed_at)
            if p_info is None:
                twap_p_info = twap_p_info_for_market(market, twap_snap)

        hms = score_hot_market(market, self.config.hot_market)
        snap = build_feature_snapshot(market, hms)
        snap.extras["resource_plan"] = resource_plan(hms.tier)
        if twap_snap is not None:
            snap.extras["twap"] = twap_snap.model_dump()
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
        probe_shares = market.order_min_size or 5.0
        edge = self.fair.evaluate(
            market,
            side=Side.BUY,
            shares=probe_shares,
            min_required_edge=self.config.trading.min_required_edge,
            config=self.config.fair_value,
            p_info=twap_p_info,
            twap=twap_snap,
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

        notional = size_notional(
            edge,
            bankroll=self.config.trading.paper_starting_cash,
            liquidity=market.liquidity,
            sizing=self.config.sizing,
            risk=self.config.risk,
        )
        shares = _intended_shares(market, self.config, notional, edge.market_price)
        if edge.market_price > 0:
            max_shares = self.config.risk.max_order_notional / edge.market_price
            shares = min(shares, max_shares)
        style, ev_maker, ev_taker = choose_style(edge, self.config.maker_taker)
        half_life = self.config.trading.signal_half_life_ms
        velocity = pnl_velocity(edge.net_expected_edge * shares, half_life, edge.p_fair * (1 - edge.p_fair))
        opp = score_opportunity(
            market=market,
            hms=hms,
            edge=edge,
            side=Side.BUY,
            token_id=token_id,
            shares=shares,
            cfg=self.config.opportunity,
            style=style,
            ev_maker=ev_maker,
            ev_taker=ev_taker,
            pnl_velocity=velocity,
            signal_half_life_ms=half_life,
        )
        age = self.clock.age_ms("clob_book") if market.book else self.clock.age_ms("gamma")
        decision = self.risk.decide(
            opp,
            category=category,
            spread=market.spread,
            data_age_ms=age,
            latency_ms=latency_ms,
            now=now,
            requested_notional=min(opp.intended_notional, self.config.risk.max_order_notional),
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

        quality = signal_quality(
            opp,
            decision="TRADE" if decision.allowed else "SKIP",
            reason_codes=[decision.reason],
            strategy=self.config.experiment.strategy_id,
        )
        if self.config.is_shadow or self.config.is_backtest:
            self._audit(
                market_id=market.market_id,
                accepted=False,
                reason=ReasonCode.SHADOW_MODE,
                hms=hms.score,
                net_edge=edge.net_expected_edge,
                opportunity_score=opp.score,
                extra={"would_buy": True, "signal": quality},
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
            extra={
                "client_order_id": order.client_order_id,
                "status": order.status.value,
                "signal": quality,
                "git_commit": git_commit(),
                "strategy_version": self.config.experiment.version,
                "twap": twap_snap.model_dump() if twap_snap else None,
            },
        )
        return {
            "accepted": True,
            "reason": ReasonCode.OK,
            "order": order.model_dump(mode="json"),
            "edge": edge.model_dump(),
            "twap": twap_snap.model_dump() if twap_snap else None,
        }

    async def run_scan(
        self,
        *,
        scanner: UniverseScanner | None = None,
        markets: list[MarketRecord] | None = None,
        use_network: bool = True,
        attach_subscriber: bool = False,
        subscriber_transport: Any | None = None,
    ) -> dict[str, Any]:
        if attach_subscriber:
            from hotflow.marketdata.rtds_subscriber import PublicRtdsSubscriber, run_live_public_collect

            cache = (
                self.twap_source
                if isinstance(self.twap_source, TwapPrintCache)
                else TwapPrintCache(max_age_ms=self.config.feeds.rtds.max_data_age_ms)
            )
            self.twap_source = cache
            if subscriber_transport is not None:
                sub = PublicRtdsSubscriber(
                    cache, config=self.config.feeds.rtds, transport=subscriber_transport
                )
                await sub.run(duration_s=self.config.feeds.rtds.collect_seconds)
            else:
                await run_live_public_collect(cache, self.config.feeds.rtds)
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


def demo_twap_market(
    *,
    hot: bool = True,
    fees_enabled: bool = True,
    rate: float = 0.04,
    window_seconds: int = 60,
    strike: float = 65000.0,
    end_date: str | None = None,
) -> MarketRecord:
    """Deterministic crypto Up/Down fixture with official 30s/60s TWAP wording."""
    from datetime import timedelta

    from hotflow.official import RTDS_TWAP_WINDOWS, rtds_twap_topic

    if window_seconds not in RTDS_TWAP_WINDOWS:
        raise ValueError("demo TWAP window must be an official 30 or 60 seconds")
    market = demo_market(hot=hot, fees_enabled=fees_enabled, rate=rate)
    close = end_date or (datetime.now(UTC) + timedelta(seconds=90)).strftime("%Y-%m-%dT%H:%M:%SZ")
    topic = rtds_twap_topic(window_seconds)
    source = (
        f"Chainlink {window_seconds}-second TWAP via Polymarket RTDS topic {topic} "
        f"(btc/usd). Opening reference {strike}. Resolves Yes if the official "
        f"Chainlink {window_seconds}s TWAP finishes above the opening reference."
    )
    market.market_id = "demo-btc-twap"
    market.slug = "demo-btc-twap"
    market.question = (
        f"Will BTC/USD official Chainlink {window_seconds}-second TWAP finish "
        f"above the opening reference {strike}?"
    )
    market.raw_gamma = {
        "description": source,
        "resolutionSource": source,
        "line": strike,
        "endDate": close,
    }
    market.resolution = parse_resolution(
        {
            "resolutionSource": source,
            "endDate": close,
            "line": strike,
            "description": source,
        }
    )
    return market


def demo_market(*, hot: bool = True, fees_enabled: bool = True, rate: float = 0.04) -> MarketRecord:
    """Deterministic market for offline paper-run / tests (not live prices)."""
    from hotflow.types import FeeSchedule

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
        resolution=parse_resolution(
            {"resolutionSource": "demo-fixture", "endDate": "2099-01-01T00:00:00Z"}
        ),
        book=OrderBook(
            token_id="demo-yes",
            condition_id="0xdemo",
            bids=bids,
            asks=asks,
            min_order_size=5.0,
            tick_size=0.01,
        ),
    )
