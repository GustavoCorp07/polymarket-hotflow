"""Paper pipeline: scan → HMS → fair value → risk → paper (no LLM)."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from hotflow.analytics.experiments import git_commit
from hotflow.analytics.pnl_velocity import pnl_velocity
from hotflow.analytics.regimes import RegimeReport, detect_regime, strategy_blocked
from hotflow.analytics.signal_quality import signal_quality
from hotflow.config import HotflowConfig
from hotflow.discovery.resolution import (
    parse_esports_resolution,
    parse_resolution,
    parse_sports_resolution,
    parse_twap_resolution,
    parse_weather_resolution,
)
from hotflow.discovery.scanner import UniverseScanner, infer_category
from hotflow.execution.live_gate import live_gates_open
from hotflow.execution.paper import PaperBroker
from hotflow.fairvalue.crypto import CryptoFairValue
from hotflow.fairvalue.esports import FixtureEsportsSource, esports_adapter_for
from hotflow.fairvalue.maker_taker import choose_style
from hotflow.fairvalue.sports import sports_model_for
from hotflow.fairvalue.twap import compute_twap_snapshot, time_remaining_seconds, twap_p_info_for_market
from hotflow.fairvalue.weather import weather_p_yes
from hotflow.features.snapshot import build_feature_snapshot
from hotflow.features.time_features import time_to_resolution_seconds
from hotflow.hotmarket.opportunity import score_opportunity
from hotflow.hotmarket.score import score_hot_market
from hotflow.hotmarket.watchlist import resource_plan
from hotflow.marketdata.clock import monotonic_ms
from hotflow.marketdata.freshness import FeedClock
from hotflow.marketdata.rtds_twap import FixtureTwapSource, TwapObservationSource
from hotflow.marketdata.sports_cache import SportsGameCache, game_state_status
from hotflow.marketdata.sports_ws import (
    FixtureSportsSource,
    SportsStateSource,
    game_state_from_metadata,
)
from hotflow.marketdata.twap_cache import TwapPrintCache, observation_status
from hotflow.marketdata.weather_fixtures import (
    FixtureWeatherSource,
    WeatherForecastSource,
    labeled_gamma_weather_forecasts,
)
from hotflow.monitoring.observer import Observability
from hotflow.news.engine import NewsEngine
from hotflow.portfolio.allocator import AllocationCandidate, AllocationDecision, PortfolioAllocator
from hotflow.portfolio.correlation import ExposureBook, ExposureIdentity, extract_identity
from hotflow.portfolio.ledger import PaperLedger
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
    SportsGameState,
    TwapSnapshot,
    WeatherForecast,
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


def make_sports_source(
    config: HotflowConfig,
    *,
    use_twap_fixtures: bool = False,
    sports_source: SportsStateSource | None = None,
    sports_cache_path: str | Path | None = None,
) -> SportsStateSource:
    """Fixtures for --mock; otherwise an empty or on-disk official-shape cache.

    Never invents a live score. A missing cache is empty until a subscriber
    or `--sports-cache` injects official-shape frames.
    """
    if sports_source is not None:
        return sports_source
    if sports_cache_path:
        return SportsGameCache.from_path(
            sports_cache_path, max_age_ms=config.feeds.sports_ws.max_data_age_ms
        )
    if use_twap_fixtures:
        return FixtureSportsSource([default_nba_state(), default_soccer_state()])
    cache = SportsGameCache(
        max_age_ms=config.feeds.sports_ws.max_data_age_ms,
        path=config.feeds.sports_ws.cache_path,
        persist=config.feeds.sports_ws.persist_cache,
    )
    if config.feeds.sports_ws.persist_cache:
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
        weather_source: WeatherForecastSource | None = None,
        sports_source: SportsStateSource | None = None,
        sports_cache_path: str | Path | None = None,
        esports_source: FixtureEsportsSource | None = None,
        obs: Observability | None = None,
        ledger: PaperLedger | None = None,
        news_engine: NewsEngine | None = None,
        use_news_fixtures: bool = False,
    ) -> None:
        self.config = config
        self.obs = obs or Observability.from_config(config, announce_restart=False)
        self.kills = KillSwitchBoard(on_trip=self.obs.on_kill_event, on_reset=self.obs.note_kill_clear)
        self.risk = RiskEngine(config.risk, self.kills)
        self.ledger = ledger or PaperLedger(
            starting_cash=config.trading.paper_starting_cash,
            session_id=config.trading.session_id,
        )
        self.broker = PaperBroker(config.trading, ledger=self.ledger)
        self.risk.sync_from_ledger(self.ledger.snapshot())
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
        if weather_source is not None:
            self.weather_source = weather_source
        elif use_twap_fixtures:
            src = FixtureWeatherSource()
            for key, forecast in labeled_gamma_weather_forecasts().items():
                src.put(key, forecast)
            self.weather_source = src
        else:
            self.weather_source = FixtureWeatherSource()
        self.esports_source = esports_source if esports_source is not None else FixtureEsportsSource()
        self.sports_source = make_sports_source(
            config,
            use_twap_fixtures=use_twap_fixtures,
            sports_source=sports_source,
            sports_cache_path=sports_cache_path,
        )
        self.allocator = PortfolioAllocator(config.portfolio, config.risk)
        self.exposure = ExposureBook()
        self.news = news_engine if news_engine is not None else NewsEngine(config.news)
        if use_news_fixtures and not self.news.items:
            from hotflow.news.fixtures import labeled_news_items

            self.news.ingest_many(labeled_news_items())

    def _detect_regime(
        self,
        market: MarketRecord,
        category: str,
        extras: dict[str, Any],
        *,
        now: datetime,
        forecast: WeatherForecast | None = None,
        sports_state: SportsGameState | None = None,
        ttr_seconds: float | None = None,
    ) -> RegimeReport:
        ttr = ttr_seconds
        if ttr is None:
            ttr = time_to_resolution_seconds(market, now=now)
        if forecast is None and extras.get("weather_forecast"):
            forecast = WeatherForecast.model_validate(extras["weather_forecast"])
        if sports_state is None and extras.get("sports_state"):
            sports_state = SportsGameState.model_validate(extras["sports_state"])
        report = detect_regime(
            market,
            category=category,
            ttr_seconds=ttr,
            news=extras.get("news") if isinstance(extras.get("news"), dict) else None,
            forecast=forecast,
            sports_state=sports_state,
            config=self.config.regimes,
        )
        extras["regime"] = report.as_dict()
        return report

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
        now: datetime | None = None,
    ) -> dict[str, Any]:
        started = monotonic_ms()
        result = self._evaluate_market(market, latency_ms=latency_ms, p_info=p_info, now=now)
        if result.get("dry_run"):
            return result
        category = infer_category(market.tags, market.category)
        peak = self.risk.state.peak_equity
        drawdown = ((peak - self.risk.state.equity) / peak) if peak > 0 else 0.0
        self.obs.after_evaluate(
            result,
            latency_ms=monotonic_ms() - started,
            market_id=market.market_id,
            category=category,
            session_id=self.config.trading.session_id,
            kill_switch=self.kills.tripped,
            exposure=self.risk.state.total_exposure,
            drawdown=drawdown,
        )
        return result

    def check_external_positions(self, external_qty: dict[str, float], *, tol: float = 1e-9) -> list[str]:
        """Compare ledger qty to a caller-supplied view. Does not invent venue balances."""
        from hotflow.portfolio.consistency import position_mismatches

        local = {token: float(qty) for token, qty in self.broker.positions.items()}
        remote = {token: float(qty) for token, qty in external_qty.items()}
        bad = position_mismatches(local, remote, tol=tol)
        if bad:
            self.kills.trip(KillSwitchReason.POSITION_MISMATCH, ",".join(bad))
        return bad

    def _evaluate_market(
        self,
        market: MarketRecord,
        *,
        latency_ms: float = 50.0,
        p_info: float | None = None,
        now: datetime | None = None,
        dry_run: bool = False,
        allocation: AllocationDecision | None = None,
        enforce_cooldown: bool = True,
    ) -> dict[str, Any]:
        now = now or datetime.now(UTC)
        if latency_ms < 0:
            self._audit(
                market_id=market.market_id,
                accepted=False,
                reason=ReasonCode.CLOCK_SKEW,
                detail="negative_latency",
            )
            return {"accepted": False, "reason": ReasonCode.CLOCK_SKEW, "detail": "negative_latency"}
        if market.book and market.book.fetched_at is not None:
            skew_ms = (market.book.fetched_at - now).total_seconds() * 1000.0
            if skew_ms > self.clock.skew_tolerance_ms:
                self._audit(
                    market_id=market.market_id,
                    accepted=False,
                    reason=ReasonCode.CLOCK_SKEW,
                    detail="book_in_future",
                )
                return {"accepted": False, "reason": ReasonCode.CLOCK_SKEW, "detail": "book_in_future"}
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

        extras: dict[str, Any] = {}
        if category == "esports":
            if not self.config.esports.enabled:
                self._audit(market_id=market.market_id, accepted=False, reason=ReasonCode.CATEGORY_DISABLED)
                return {"accepted": False, "reason": ReasonCode.CATEGORY_DISABLED}
            esports_spec = parse_esports_resolution(market)
            extras_es: dict[str, Any] = {"esports_spec": esports_spec.model_dump()}
            if (
                not esports_spec.complete
                or esports_spec.parse_confidence < self.config.esports.min_parse_confidence
            ):
                reason = esports_spec.skip_reason or ReasonCode.ESPORTS_RULES_UNKNOWN
                self._audit(market_id=market.market_id, accepted=False, reason=reason, extra=extras_es)
                return {
                    "accepted": False,
                    "reason": reason,
                    "market_id": market.market_id,
                    "question": market.question,
                    "esports_spec": esports_spec.model_dump(),
                }
            adapter = esports_adapter_for(esports_spec.game)
            if adapter is None:
                self._audit(
                    market_id=market.market_id,
                    accepted=False,
                    reason=ReasonCode.UNSUPPORTED_SPORT,
                    extra=extras_es,
                )
                return {
                    "accepted": False,
                    "reason": ReasonCode.UNSUPPORTED_SPORT,
                    "market_id": market.market_id,
                    "question": market.question,
                    "esports_spec": esports_spec.model_dump(),
                    "game": esports_spec.game,
                }
            state = self.esports_source.latest(esports_spec)
            extras_es["esports_adapter"] = adapter.title
            if state is None:
                self._audit(
                    market_id=market.market_id,
                    accepted=False,
                    reason=ReasonCode.ESPORTS_STATE_MISSING,
                    extra=extras_es,
                )
                return {
                    "accepted": False,
                    "reason": ReasonCode.ESPORTS_STATE_MISSING,
                    "market_id": market.market_id,
                    "question": market.question,
                    "esports_spec": esports_spec.model_dump(),
                    "esports_adapter": adapter.title,
                }
            extras_es["esports_state"] = state.model_dump(mode="json")
            extras_es["esports_state_source"] = state.source
            esports_p = adapter.p_home_win(esports_spec, state)
            if esports_p is None:
                self._audit(
                    market_id=market.market_id,
                    accepted=False,
                    reason=ReasonCode.UNSUPPORTED_STRUCTURE,
                    extra=extras_es,
                )
                return {
                    "accepted": False,
                    "reason": ReasonCode.UNSUPPORTED_STRUCTURE,
                    "market_id": market.market_id,
                    "question": market.question,
                    **extras_es,
                }
            if p_info is None:
                p_info = esports_p
            extras.update(extras_es)

        twap_spec = parse_twap_resolution(market)
        twap_snap: TwapSnapshot | None = None
        twap_p_info = p_info

        if category == "weather":
            if not self.config.weather.enabled:
                self._audit(market_id=market.market_id, accepted=False, reason=ReasonCode.CATEGORY_DISABLED)
                return {"accepted": False, "reason": ReasonCode.CATEGORY_DISABLED}
            weather_spec = parse_weather_resolution(market)
            extras["weather_spec"] = weather_spec.model_dump()
            if (
                not weather_spec.complete
                or weather_spec.parse_confidence < self.config.weather.min_parse_confidence
            ):
                reason = weather_spec.skip_reason or ReasonCode.UNKNOWN_RESOLUTION
                self._audit(market_id=market.market_id, accepted=False, reason=reason, extra=extras)
                return {
                    "accepted": False,
                    "reason": reason,
                    "market_id": market.market_id,
                    "question": market.question,
                    "weather_spec": weather_spec.model_dump(),
                }
            forecast = self.weather_source.latest(weather_spec)
            if forecast is None:
                self._detect_regime(market, category, extras, now=now)
                self._audit(
                    market_id=market.market_id,
                    accepted=False,
                    reason=ReasonCode.WEATHER_FORECAST_MISSING,
                    extra=extras,
                )
                return {
                    "accepted": False,
                    "reason": ReasonCode.WEATHER_FORECAST_MISSING,
                    "market_id": market.market_id,
                    "question": market.question,
                    "weather_spec": weather_spec.model_dump(),
                }
            extras["weather_forecast"] = forecast.model_dump(mode="json")
            extras["forecast_role"] = "feature_only"
            extras["forecast_source"] = forecast.source
            weather_p = weather_p_yes(weather_spec, forecast)
            if weather_p is None:
                self._audit(
                    market_id=market.market_id,
                    accepted=False,
                    reason=ReasonCode.WEATHER_FORECAST_MISSING,
                    extra=extras,
                )
                return {
                    "accepted": False,
                    "reason": ReasonCode.WEATHER_FORECAST_MISSING,
                    "market_id": market.market_id,
                    "question": market.question,
                    "weather_spec": weather_spec.model_dump(),
                    "weather_forecast": extras["weather_forecast"],
                }
            if p_info is None:
                twap_p_info = weather_p

        if category == "sports":
            if not self.config.sports.enabled:
                self._audit(market_id=market.market_id, accepted=False, reason=ReasonCode.CATEGORY_DISABLED)
                return {"accepted": False, "reason": ReasonCode.CATEGORY_DISABLED}
            sports_spec = parse_sports_resolution(market)
            extras["sports_spec"] = sports_spec.model_dump()
            if (
                not sports_spec.complete
                or sports_spec.parse_confidence < self.config.sports.min_parse_confidence
            ):
                reason = sports_spec.skip_reason or ReasonCode.UNKNOWN_RESOLUTION
                self._audit(market_id=market.market_id, accepted=False, reason=reason, extra=extras)
                return {"accepted": False, "reason": reason, "sports_spec": sports_spec.model_dump()}
            model = sports_model_for(sports_spec.league)
            if model is None:
                self._audit(
                    market_id=market.market_id,
                    accepted=False,
                    reason=ReasonCode.UNSUPPORTED_SPORT,
                    extra=extras,
                )
                return {"accepted": False, "reason": ReasonCode.UNSUPPORTED_SPORT, "league": sports_spec.league}
            cached = self.sports_source.latest(sports_spec)
            freshness = game_state_status(
                cached,
                max_age_ms=self.config.feeds.sports_ws.max_data_age_ms,
                now=now,
            )
            if freshness == "stale":
                self._audit(
                    market_id=market.market_id,
                    accepted=False,
                    reason=ReasonCode.SPORTS_STATE_STALE,
                    extra=extras,
                )
                return {"accepted": False, "reason": ReasonCode.SPORTS_STATE_STALE}
            state = cached if freshness == "fresh" else game_state_from_metadata(sports_spec)
            if state is None:
                self._audit(
                    market_id=market.market_id,
                    accepted=False,
                    reason=ReasonCode.SPORTS_STATE_MISSING,
                    extra=extras,
                )
                return {"accepted": False, "reason": ReasonCode.SPORTS_STATE_MISSING}
            if cached is not None:
                self.clock.touch("sports_ws", observed_at=state.last_update)
            extras["sports_state"] = state.model_dump(mode="json")
            extras["sports_model"] = model.sport
            sports_p = model.p_home_win(sports_spec, state)
            if sports_p is None:
                self._audit(
                    market_id=market.market_id,
                    accepted=False,
                    reason=ReasonCode.SPORTS_STATE_MISSING,
                    extra=extras,
                )
                return {"accepted": False, "reason": ReasonCode.SPORTS_STATE_MISSING}
            if p_info is None:
                twap_p_info = sports_p

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

        news_impact = None
        if self.config.news.enabled:
            news_impact = self.news.impact_for(market, p_base=twap_p_info, now=now)
            extras["news"] = news_impact.as_dict()
            extras["news_orders"] = False
            if news_impact.apply and news_impact.p_info_adjusted is not None:
                twap_p_info = news_impact.p_info_adjusted

        twap_ttr = twap_snap.time_remaining_s if twap_snap is not None else None
        regime_report = self._detect_regime(market, category, extras, now=now, ttr_seconds=twap_ttr)

        hms = score_hot_market(market, self.config.hot_market)
        snap = build_feature_snapshot(market, hms)
        snap.extras["resource_plan"] = resource_plan(hms.tier)
        snap.extras.update(extras)
        if twap_snap is not None:
            snap.extras["twap"] = twap_snap.model_dump()
            extras["twap"] = snap.extras["twap"]
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
            return {
                "accepted": False,
                "reason": ReasonCode.MARKET_NOT_HOT,
                "hms": hms.score,
                **extras,
            }

        token_id = market.token_ids[0] if market.token_ids else "unknown"
        probe_shares = market.order_min_size or 5.0
        prior_blend = None
        if category == "weather":
            prior_blend = self.config.weather.prior_blend
        elif category == "sports":
            prior_blend = self.config.sports.prior_blend
        elif category == "esports":
            prior_blend = self.config.esports.prior_blend
        edge = self.fair.evaluate(
            market,
            side=Side.BUY,
            shares=probe_shares,
            min_required_edge=self.config.trading.min_required_edge,
            config=self.config.fair_value,
            p_info=twap_p_info,
            twap=twap_snap,
            prior_blend=prior_blend,
        )
        if news_impact is not None and news_impact.apply:
            edge = edge.model_copy(update={"confidence": min(edge.confidence, news_impact.confidence)})
        if edge.skip:
            self._audit(
                market_id=market.market_id,
                accepted=False,
                reason=edge.reason or ReasonCode.NO_TRADE,
                hms=hms.score,
                tier=hms.tier.value,
                net_edge=edge.net_expected_edge,
            )
            return {"accepted": False, "reason": edge.reason, "edge": edge.model_dump(), **extras}

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
        age = self.clock.age_ms("clob_book", now) if market.book else self.clock.age_ms("gamma", now)
        identity = extract_identity(
            market, category=category, extra_labels=regime_report.label_ids
        )
        extras["exposure_identity"] = {
            "underlying": identity.underlying,
            "window": identity.window,
            "city": identity.city,
            "game": identity.game,
            "match": identity.match,
            "regime": identity.regime_label,
            "regimes": list(identity.regime_labels),
            "notes": list(identity.source_notes),
        }
        blocked = strategy_blocked(category, regime_report, self.config.regimes)
        if blocked:
            self._audit(
                market_id=market.market_id,
                accepted=False,
                reason=ReasonCode.REGIME_DISABLED,
                detail=blocked,
                hms=hms.score,
                net_edge=edge.net_expected_edge,
                opportunity_score=opp.score,
                extra={"regime": extras.get("regime"), **extras},
            )
            return {
                "accepted": False,
                "reason": ReasonCode.REGIME_DISABLED,
                "detail": blocked,
                **extras,
            }
        candidate = AllocationCandidate.from_opportunity(
            opp, market=market, category=category, identity=identity
        )
        if dry_run:
            return {
                "dry_run": True,
                "accepted": None,
                "candidate": candidate,
                "prepared": {
                    "market": market,
                    "category": category,
                    "edge": edge,
                    "opp": opp,
                    "shares": shares,
                    "style": style,
                    "ev_maker": ev_maker,
                    "ev_taker": ev_taker,
                    "extras": extras,
                    "hms": hms,
                    "age": age,
                    "now": now,
                    "latency_ms": latency_ms,
                    "token_id": token_id,
                    "identity": identity,
                },
            }
        return self._commit_prepared(
            {
                "market": market,
                "category": category,
                "edge": edge,
                "opp": opp,
                "shares": shares,
                "style": style,
                "ev_maker": ev_maker,
                "ev_taker": ev_taker,
                "extras": extras,
                "hms": hms,
                "age": age,
                "now": now,
                "latency_ms": latency_ms,
                "token_id": token_id,
                "identity": identity,
            },
            allocation=allocation,
            candidate=candidate,
            enforce_cooldown=enforce_cooldown,
        )

    def _apply_allocation(
        self,
        prepared: dict[str, Any],
        allocation: AllocationDecision | None,
        candidate: AllocationCandidate,
    ) -> tuple[Any, Any, float, AllocationDecision]:
        market = prepared["market"]
        edge = prepared["edge"]
        opp = prepared["opp"]
        shares = float(prepared["shares"])
        extras = prepared["extras"]
        alloc = allocation
        if alloc is None:
            allocs = self.allocator.allocate(
                [candidate],
                existing=self.exposure.snapshot(),
                category_exposure=dict(self.risk.state.category_exposure),
                total_exposure=self.risk.state.total_exposure,
                concurrent_markets=set(self.risk.state.concurrent_markets),
            )
            alloc = allocs[0]
        extras["portfolio"] = alloc.as_dict()
        if alloc.action != "SKIP" and alloc.allocated_notional + 1e-9 < opp.intended_notional:
            price = edge.market_price
            shares = _intended_shares(market, self.config, alloc.allocated_notional, price)
            if price > 0:
                shares = min(shares, self.config.risk.max_order_notional / price)
            notional = shares * price if price > 0 else alloc.allocated_notional
            opp = opp.model_copy(update={"intended_shares": shares, "intended_notional": notional})
        return opp, extras, shares, alloc

    def _commit_prepared(
        self,
        prepared: dict[str, Any],
        *,
        allocation: AllocationDecision | None = None,
        candidate: AllocationCandidate | None = None,
        enforce_cooldown: bool = True,
    ) -> dict[str, Any]:
        market: MarketRecord = prepared["market"]
        category: str = prepared["category"]
        edge = prepared["edge"]
        extras: dict[str, Any] = dict(prepared["extras"])
        hms = prepared["hms"]
        age = prepared["age"]
        now = prepared["now"]
        latency_ms = float(prepared["latency_ms"])
        style = prepared["style"]
        identity: ExposureIdentity = prepared["identity"]
        cand = candidate or AllocationCandidate.from_opportunity(
            prepared["opp"], market=market, category=category, identity=identity
        )
        prepared = {**prepared, "extras": extras}
        opp, extras, shares, alloc = self._apply_allocation(prepared, allocation, cand)
        if alloc.action == "SKIP":
            self._audit(
                market_id=market.market_id,
                accepted=False,
                reason=alloc.reason,
                detail=alloc.detail,
                hms=hms.score,
                net_edge=edge.net_expected_edge,
                opportunity_score=opp.score,
                extra={"portfolio": alloc.as_dict(), **extras},
            )
            return {
                "accepted": False,
                "reason": alloc.reason,
                "detail": alloc.detail,
                "portfolio": alloc.as_dict(),
                **extras,
                "market_id": market.market_id,
                "question": market.question,
            }

        decision = self.risk.decide(
            opp,
            category=category,
            spread=market.spread,
            data_age_ms=age,
            latency_ms=latency_ms,
            now=now,
            requested_notional=min(opp.intended_notional, self.config.risk.max_order_notional),
            enforce_cooldown=enforce_cooldown,
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
                extra={"portfolio": alloc.as_dict(), **extras},
            )
            return {
                "accepted": False,
                "reason": decision.reason,
                "detail": decision.detail,
                "portfolio": alloc.as_dict(),
                **extras,
                "market_id": market.market_id,
                "question": market.question,
            }

        quality = signal_quality(
            opp,
            decision="TRADE" if decision.allowed else "SKIP",
            reason_codes=[decision.reason, alloc.reason],
            strategy=self.config.experiment.strategy_id,
        )
        if self.config.is_shadow:
            shadow = {
                "would_buy": opp.side == Side.BUY,
                "would_sell": opp.side == Side.SELL,
                "expected_price": edge.market_price,
                "actual_price_after_signal": None,
                "simulated_fill": {
                    "sent": False,
                    "style": style.value,
                    "shares": shares,
                    "fee_per_share": edge.fee_per_share,
                },
            }
            self._audit(
                market_id=market.market_id,
                accepted=False,
                reason=ReasonCode.SHADOW_MODE,
                hms=hms.score,
                net_edge=edge.net_expected_edge,
                opportunity_score=opp.score,
                extra={**shadow, "signal": quality, "portfolio": alloc.as_dict(), **extras},
            )
            return {
                "accepted": False,
                "reason": ReasonCode.SHADOW_MODE,
                "opportunity": opp.model_dump(),
                "edge": edge.model_dump(),
                "side": opp.side.value,
                "shares": shares,
                "style": style.value,
                "portfolio": alloc.as_dict(),
                **shadow,
                **extras,
            }

        if self.config.is_backtest:
            self._audit(
                market_id=market.market_id,
                accepted=True,
                reason=ReasonCode.OK,
                hms=hms.score,
                tier=hms.tier.value,
                net_edge=edge.net_expected_edge,
                opportunity_score=opp.score,
                extra={"backtest_intent": True, "signal": quality, "portfolio": alloc.as_dict(), **extras},
            )
            return {
                "accepted": True,
                "reason": ReasonCode.OK,
                "backtest_intent": True,
                "market_id": market.market_id,
                "question": market.question,
                "opportunity": opp.model_dump(),
                "edge": edge.model_dump(),
                "side": opp.side.value,
                "shares": shares,
                "style": style.value,
                "expected_price": edge.market_price,
                "portfolio": alloc.as_dict(),
                **extras,
            }

        if not self.config.is_paper and not live_gates_open(self.config):
            self._audit(market_id=market.market_id, accepted=False, reason=ReasonCode.LIVE_GATES_BLOCKED)
            return {"accepted": False, "reason": ReasonCode.LIVE_GATES_BLOCKED}

        order_started = monotonic_ms()
        order = self.broker.create(opp, price=edge.market_price, size=shares)
        order = self.broker.submit(order.client_order_id)
        filled_before = order.filled_size
        order = self.broker.simulate_fill(
            order.client_order_id,
            fee_per_share=float(edge.fee_per_share or 0.0),
        )
        self.obs.observe_order_latency(monotonic_ms() - order_started)
        fill_event = self.broker.last_fill_event
        self.risk.state.open_orders = sum(
            1
            for o in self.broker.orders.values()
            if o.status.value in {"SUBMITTED", "ACKNOWLEDGED", "PARTIAL"}
        )
        self.risk.state.last_order_at = now
        realized_delta = fill_event.realized_delta if fill_event is not None else 0.0
        filled_notional = order.filled_size * (order.avg_fill_price or order.price)
        self.risk.note_fill(
            market_id=market.market_id,
            category=category,
            notional=filled_notional,
            pnl_delta=realized_delta,
        )
        self.exposure.add_notional(identity, filled_notional, category=category)
        self.risk.sync_from_ledger(self.ledger.snapshot())
        self.risk.enforce_session_limits()
        if fill_event is not None and fill_event.closed:
            self.obs.metrics.note_closed_trade(fill_event.realized_delta)
        self.obs.publish_ledger(self.ledger.snapshot())
        if self.store:
            self.store.save_order(order)
            delta = order.filled_size - filled_before
            if delta > 0:
                self.store.save_trade(order, delta, order.avg_fill_price or order.price)
            if fill_event is not None:
                self.store.save_ledger_event(fill_event)
            self.store.save_ledger_snapshot(self.ledger.snapshot())
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
                "twap": extras.get("twap"),
                "portfolio": alloc.as_dict(),
                **extras,
            },
        )
        return {
            "accepted": True,
            "reason": ReasonCode.OK,
            "market_id": market.market_id,
            "question": market.question,
            "order": order.model_dump(mode="json"),
            "edge": edge.model_dump(),
            "twap": extras.get("twap"),
            "portfolio": alloc.as_dict(),
            **extras,
        }

    def evaluate_markets(
        self,
        markets: list[MarketRecord],
        *,
        latency_ms: float = 50.0,
        p_info: float | None = None,
        now: datetime | None = None,
    ) -> list[dict[str, Any]]:
        """Score the batch, allocate, then commit. One scan tick — no inter-name cooldown."""
        now = now or datetime.now(UTC)
        results: list[dict[str, Any] | None] = [None] * len(markets)
        packed_idx: list[int] = []
        packed_rows: list[dict[str, Any]] = []
        for index, market in enumerate(markets):
            started = monotonic_ms()
            row = self._evaluate_market(market, latency_ms=latency_ms, p_info=p_info, now=now, dry_run=True)
            if row.get("dry_run"):
                packed_idx.append(index)
                packed_rows.append(row)
            else:
                category = infer_category(market.tags, market.category)
                peak = self.risk.state.peak_equity
                drawdown = ((peak - self.risk.state.equity) / peak) if peak > 0 else 0.0
                self.obs.after_evaluate(
                    row,
                    latency_ms=monotonic_ms() - started,
                    market_id=market.market_id,
                    category=category,
                    session_id=self.config.trading.session_id,
                    kill_switch=self.kills.tripped,
                    exposure=self.risk.state.total_exposure,
                    drawdown=drawdown,
                )
                results[index] = row

        candidates = [row["candidate"] for row in packed_rows]
        allocations = self.allocator.allocate(
            candidates,
            existing=self.exposure.snapshot(),
            category_exposure=dict(self.risk.state.category_exposure),
            total_exposure=self.risk.state.total_exposure,
            concurrent_markets=set(self.risk.state.concurrent_markets),
        )
        for index, row, alloc in zip(packed_idx, packed_rows, allocations, strict=True):
            started = monotonic_ms()
            market = markets[index]
            result = self._commit_prepared(
                row["prepared"],
                allocation=alloc,
                candidate=row["candidate"],
                enforce_cooldown=False,
            )
            category = infer_category(market.tags, market.category)
            peak = self.risk.state.peak_equity
            drawdown = ((peak - self.risk.state.equity) / peak) if peak > 0 else 0.0
            self.obs.after_evaluate(
                result,
                latency_ms=monotonic_ms() - started,
                market_id=market.market_id,
                category=category,
                session_id=self.config.trading.session_id,
                kill_switch=self.kills.tripped,
                exposure=self.risk.state.total_exposure,
                drawdown=drawdown,
            )
            results[index] = result
        return [item if item is not None else {"accepted": False, "reason": ReasonCode.NO_TRADE} for item in results]

    async def run_scan(
        self,
        *,
        scanner: UniverseScanner | None = None,
        markets: list[MarketRecord] | None = None,
        use_network: bool = True,
        attach_subscriber: bool = False,
        subscriber_transport: Any | None = None,
        attach_sports_subscriber: bool = False,
        sports_subscriber_transport: Any | None = None,
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
                rtds_sub = PublicRtdsSubscriber(
                    cache, config=self.config.feeds.rtds, transport=subscriber_transport
                )
                await rtds_sub.run(duration_s=self.config.feeds.rtds.collect_seconds)
            else:
                await run_live_public_collect(cache, self.config.feeds.rtds)
        if attach_sports_subscriber:
            from hotflow.marketdata.sports_subscriber import (
                PublicSportsSubscriber,
                run_live_public_sports_collect,
            )

            sports_cache = (
                self.sports_source
                if isinstance(self.sports_source, SportsGameCache)
                else SportsGameCache(max_age_ms=self.config.feeds.sports_ws.max_data_age_ms)
            )
            self.sports_source = sports_cache
            if sports_subscriber_transport is not None:
                sports_sub = PublicSportsSubscriber(
                    sports_cache,
                    config=self.config.feeds.sports_ws,
                    transport=sports_subscriber_transport,
                )
                await sports_sub.run(duration_s=self.config.feeds.sports_ws.collect_seconds)
            else:
                await run_live_public_sports_collect(sports_cache, self.config.feeds.sports_ws)
        if markets is None:
            scanner = scanner or UniverseScanner(self.config)
            try:
                markets = await scanner.scan(use_network=use_network)
            except Exception as exc:  # noqa: BLE001
                self.obs.note_api_error("scanner", type(exc).__name__)
                return {"ok": False, "error": type(exc).__name__, "markets": 0, "audits": []}
        results = self.evaluate_markets(markets)
        self.obs.snapshot_pipeline(self)
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


def default_nba_state() -> SportsGameState:
    return SportsGameState(
        game_id=5127839,
        league_abbreviation="NBA",
        home_team="Los Angeles Lakers",
        away_team="Boston Celtics",
        status="InProgress",
        live=True,
        ended=False,
        score="110-90",
        period="Q4",
        elapsed="05:12",
        source="fixture",
    )


def default_soccer_state() -> SportsGameState:
    return SportsGameState(
        game_id=9001,
        league_abbreviation="Soccer",
        home_team="Arsenal",
        away_team="Chelsea",
        status="InProgress",
        live=True,
        ended=False,
        score="2-0",
        period="2H",
        elapsed="75:00",
        source="fixture",
    )


def demo_weather_market(*, hot: bool = True) -> MarketRecord:
    """Deterministic weather fixture with explicit official-source wording."""
    from datetime import timedelta

    market = demo_market(hot=hot)
    close = (datetime.now(UTC) + timedelta(hours=12)).strftime("%Y-%m-%dT%H:%M:%SZ")
    source = (
        "National Weather Service ASOS observations at station KORD (Chicago O'Hare). "
        "Official high temperature for the local calendar day in America/Chicago, "
        "rounded to the nearest degree Fahrenheit. Resolves Yes if the official high "
        "is above 70. City: Chicago."
    )
    market.market_id = "demo-weather-chicago"
    market.slug = "demo-weather-chicago"
    market.category = "weather"
    market.tags = ["weather", "temperature"]
    market.question = "Will the official high temperature in Chicago be above 70°F?"
    market.raw_gamma = {
        "description": source,
        "resolutionSource": source,
        "line": 70,
        "endDate": close,
    }
    market.resolution = parse_resolution(
        {"resolutionSource": source, "endDate": close, "line": 70, "description": source}
    )
    return market


def weather_market_from_gamma_fixture(row: dict[str, Any], *, hot: bool = True) -> MarketRecord:
    """Build a paper MarketRecord from redacted public Gamma weather text."""
    market = demo_market(hot=hot)
    market.market_id = str(row.get("id") or row.get("slug") or "gamma-weather")
    market.slug = str(row.get("slug") or market.market_id)
    market.category = "weather"
    market.tags = list(row.get("tags") or ["weather"])
    market.question = str(row.get("question") or "")
    if row.get("outcomes"):
        if isinstance(row["outcomes"], list):
            market.outcomes = [str(item) for item in row["outcomes"]]
    raw = {
        "description": row.get("description"),
        "resolutionSource": row.get("resolutionSource"),
        "endDate": row.get("endDate"),
        "line": row.get("line"),
        "groupItemTitle": row.get("groupItemTitle"),
        "id": row.get("id"),
        "slug": row.get("slug"),
    }
    market.raw_gamma = {key: value for key, value in raw.items() if value is not None}
    market.resolution = parse_resolution(
        {
            "resolutionSource": row.get("resolutionSource") or "",
            "endDate": row.get("endDate"),
            "line": row.get("line"),
            "description": row.get("description"),
            "groupItemTitle": row.get("groupItemTitle"),
        }
    )
    # Gamma city markets often put the official source in description, not resolutionSource.
    if not market.resolution.source:
        parsed = parse_weather_resolution(market)
        if parsed.source:
            market.resolution.source = parsed.source
            market.resolution.tradeable = True
            market.resolution.parse_confidence = max(market.resolution.parse_confidence, parsed.parse_confidence)
    return market


def gamma_weather_demo_markets(*, hot: bool = True) -> list[MarketRecord]:
    from hotflow.discovery.weather_gamma import load_weather_fixture_bundle

    return [weather_market_from_gamma_fixture(row, hot=hot) for row in load_weather_fixture_bundle()]


def esports_market_from_gamma_fixture(row: dict[str, Any], *, hot: bool = True) -> MarketRecord:
    """Build a paper MarketRecord from redacted public Gamma esports text."""
    market = demo_market(hot=hot)
    market.market_id = str(row.get("id") or row.get("slug") or "gamma-esports")
    market.slug = str(row.get("slug") or market.market_id)
    market.category = "esports"
    market.tags = list(row.get("tags") or ["esports"])
    market.question = str(row.get("question") or "")
    if row.get("outcomes") and isinstance(row["outcomes"], list):
        market.outcomes = [str(item) for item in row["outcomes"]]
    raw = {
        "description": row.get("description"),
        "resolutionSource": row.get("resolutionSource"),
        "endDate": row.get("endDate"),
        "sportsMarketType": row.get("sportsMarketType"),
        "groupItemTitle": row.get("groupItemTitle"),
        "id": row.get("id"),
        "slug": row.get("slug"),
    }
    market.raw_gamma = {key: value for key, value in raw.items() if value is not None}
    market.resolution = parse_resolution(
        {
            "resolutionSource": row.get("resolutionSource") or "",
            "endDate": row.get("endDate"),
            "sportsMarketType": row.get("sportsMarketType"),
            "description": row.get("description"),
        }
    )
    if not market.resolution.source:
        parsed = parse_esports_resolution(market)
        if parsed.source:
            market.resolution.source = parsed.source
            market.resolution.tradeable = True
            market.resolution.parse_confidence = max(
                market.resolution.parse_confidence, parsed.parse_confidence
            )
    return market


def gamma_esports_demo_markets(*, hot: bool = True) -> list[MarketRecord]:
    from hotflow.discovery.esports_gamma import load_esports_fixture_bundle

    return [esports_market_from_gamma_fixture(row, hot=hot) for row in load_esports_fixture_bundle()]


def demo_sports_nba_market(*, hot: bool = True) -> MarketRecord:
    """Deterministic NBA moneyline fixture using official Sports WS field names."""
    from datetime import timedelta

    market = demo_market(hot=hot)
    start = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    close = (datetime.now(UTC) + timedelta(hours=3)).strftime("%Y-%m-%dT%H:%M:%SZ")
    source = "Official NBA scoreboard via Polymarket Sports WebSocket sport_result fields."
    market.market_id = "demo-nba-lal-bos"
    market.slug = "demo-nba-lal-bos"
    market.category = "sports"
    market.tags = ["sports", "nba"]
    market.question = "Los Angeles Lakers vs Boston Celtics"
    market.outcomes = ["Los Angeles Lakers", "Boston Celtics"]
    market.raw_gamma = {
        "description": source,
        "resolutionSource": source,
        "endDate": close,
        "leagueAbbreviation": "NBA",
        "homeTeam": "Los Angeles Lakers",
        "awayTeam": "Boston Celtics",
        "sportsMarketType": "moneyline",
        "gameStartTime": start,
    }
    market.resolution = parse_resolution(
        {
            "resolutionSource": source,
            "endDate": close,
            "sportsMarketType": "moneyline",
            "gameStartTime": start,
        }
    )
    return market


def demo_sports_soccer_market(*, hot: bool = True) -> MarketRecord:
    """Deterministic Soccer moneyline fixture. League is official 'Soccer', not an invented abbrev."""
    from datetime import timedelta

    market = demo_market(hot=hot)
    start = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    close = (datetime.now(UTC) + timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M:%SZ")
    source = "Official soccer scoreboard via Polymarket Sports WebSocket sport_result fields."
    market.market_id = "demo-soccer-ars-che"
    market.slug = "demo-soccer-ars-che"
    market.category = "sports"
    market.tags = ["sports", "soccer"]
    market.question = "Arsenal vs Chelsea"
    market.outcomes = ["Arsenal", "Chelsea"]
    market.raw_gamma = {
        "description": source,
        "resolutionSource": source,
        "endDate": close,
        "leagueAbbreviation": "Soccer",
        "homeTeam": "Arsenal",
        "awayTeam": "Chelsea",
        "sportsMarketType": "moneyline",
        "gameStartTime": start,
    }
    market.resolution = parse_resolution(
        {
            "resolutionSource": source,
            "endDate": close,
            "sportsMarketType": "moneyline",
            "gameStartTime": start,
        }
    )
    return market


def demo_sports_tennis_market(*, hot: bool = True) -> MarketRecord:
    """Complete tennis identity — model must refuse rather than reuse NBA/Soccer."""
    from datetime import timedelta

    market = demo_market(hot=hot)
    start = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    close = (datetime.now(UTC) + timedelta(hours=4)).strftime("%Y-%m-%dT%H:%M:%SZ")
    source = "Official tennis scoreboard via Polymarket Sports WebSocket sport_result fields."
    market.market_id = "demo-tennis"
    market.slug = "demo-tennis"
    market.category = "sports"
    market.tags = ["sports", "tennis"]
    market.question = "Player A vs Player B"
    market.outcomes = ["Player A", "Player B"]
    market.raw_gamma = {
        "description": source,
        "resolutionSource": source,
        "endDate": close,
        "leagueAbbreviation": "Tennis",
        "homeTeam": "Player A",
        "awayTeam": "Player B",
        "sportsMarketType": "moneyline",
        "gameStartTime": start,
        "score": "2-1",
        "period": "3/5",
        "live": True,
        "ended": False,
    }
    market.resolution = parse_resolution(
        {
            "resolutionSource": source,
            "endDate": close,
            "sportsMarketType": "moneyline",
            "gameStartTime": start,
        }
    )
    return market


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


def demo_crypto_window_market(
    *,
    symbol: str,
    window: str,
    market_id: str,
    hot: bool = True,
    regime: str | None = None,
) -> MarketRecord:
    """PAPER fixture: explicit symbol + window in text. No invented correlation."""
    from hotflow.official import RTDS_CHAINLINK_SYMBOLS

    symbol_l = symbol.lower()
    if symbol_l not in RTDS_CHAINLINK_SYMBOLS:
        raise ValueError(f"symbol {symbol!r} is not a documented Chainlink pair")
    alias = symbol_l.split("/", 1)[0]
    market = demo_market(hot=hot)
    market.market_id = market_id
    market.condition_id = f"0x{market_id}"
    market.slug = market_id
    market.token_ids = [f"{market_id}-yes"]
    market.tags = ["crypto", alias, window]
    market.question = f"Will {symbol_l.upper()} finish up over the next {window}?"
    if market.book is not None:
        market.book = market.book.model_copy(update={"token_id": f"{market_id}-yes"})
    raw = dict(market.raw_gamma or {})
    if regime:
        raw["hotflow_regime"] = regime
    market.raw_gamma = raw
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
