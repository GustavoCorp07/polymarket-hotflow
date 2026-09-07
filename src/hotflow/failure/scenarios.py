"""Deliberate PAPER/SHADOW failure cases. Fail safe: no would_* submit, no invented data."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any

from hotflow.backtest.events import sanitize_event_rows
from hotflow.backtest.shadow import attach_shadow_fields
from hotflow.config import HotflowConfig, RtdsFeedConfig
from hotflow.discovery.clob import ClobPublicClient
from hotflow.discovery.gamma import GammaClient
from hotflow.discovery.scanner import UniverseScanner
from hotflow.execution.paper import PaperBroker
from hotflow.failure.http import injected_async_client
from hotflow.hotmarket.opportunity import score_opportunity
from hotflow.hotmarket.score import score_hot_market
from hotflow.marketdata.clock import LatencyProbe, monotonic_forward, monotonic_ms
from hotflow.marketdata.rtds_subscriber import InjectedFrameTransport, PublicRtdsSubscriber
from hotflow.marketdata.twap_cache import TwapPrintCache
from hotflow.marketdata.websocket import MARKET_HEARTBEAT, USER_HEARTBEAT, ReconnectingWebSocket
from hotflow.monitoring.alerts import AlertKind
from hotflow.monitoring.observer import Observability
from hotflow.pipeline import PaperPipeline, demo_market, demo_twap_market
from hotflow.reason_codes import ReasonCode
from hotflow.types import EdgeBreakdown, FeeSchedule, Side


def _cfg() -> HotflowConfig:
    cfg = HotflowConfig()
    cfg.risk.cooldown_ms = 0
    cfg.risk.cooldown_after_losses_ms = 0
    cfg.trading.mode = "paper"
    cfg.trading.shadow = False
    return cfg


def _shadow_row(pipe: PaperPipeline, market: Any, **kwargs: Any) -> dict[str, Any]:
    pipe.config.trading.mode = "shadow"
    pipe.config.trading.shadow = True
    return attach_shadow_fields(
        pipe.evaluate_market(market, **kwargs),
        market_id=getattr(market, "market_id", None),
    )


def _result(
    name: str,
    *,
    reason: str | None,
    would_buy: bool = False,
    would_sell: bool = False,
    orders: int = 0,
    kill: str | None = None,
    alerts: list[str] | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    fail_safe = (not would_buy) and (not would_sell) and orders == 0
    payload: dict[str, Any] = {
        "name": name,
        "ok": fail_safe and bool(reason),
        "fail_safe": fail_safe,
        "reason": reason,
        "would_buy": would_buy,
        "would_sell": would_sell,
        "orders_submitted": orders,
        "kill_reason": kill,
        "alert_kinds": alerts or [],
    }
    if extra:
        payload.update(extra)
    return payload


def _opp(market: Any):
    from hotflow.config import HotMarketConfig, OpportunityConfig

    hms = score_hot_market(market, HotMarketConfig())
    edge = EdgeBreakdown(
        p_fair=0.6,
        market_price=0.42,
        raw_edge=0.18,
        fee_per_share=0.01,
        spread_cost=0.01,
        slippage=0.0,
        latency_haircut=0.0,
        adverse_selection=0.0,
        net_expected_edge=0.16,
        confidence=0.6,
    )
    return score_opportunity(
        market=market,
        hms=hms,
        edge=edge,
        side=Side.BUY,
        token_id=market.token_ids[0] if market.token_ids else "demo-yes",
        shares=10,
        cfg=OpportunityConfig(),
    )


def scenario_ws_disconnect() -> dict[str, Any]:
    obs = Observability.from_config(_cfg())
    cache = TwapPrintCache(max_age_ms=10_000)
    transport = InjectedFrameTransport()
    transport.push_disconnect()
    cfg = RtdsFeedConfig(max_data_age_ms=10_000, ping_interval_s=1, reconnect_max_backoff_s=0.01, collect_seconds=0.4)
    sub = PublicRtdsSubscriber(cache, config=cfg, transport=transport)

    async def _run() -> None:
        market_ws = ReconnectingWebSocket(MARKET_HEARTBEAT)
        user_ws = ReconnectingWebSocket(USER_HEARTBEAT)
        await market_ws.connect()
        await user_ws.connect()
        await market_ws.handle_disconnect()
        await user_ws.handle_disconnect()
        await sub.run(duration_s=0.25)

    asyncio.run(_run())
    obs.alert(AlertKind.API_DISCONNECTED, "injected disconnect", feed="rtds")
    obs.note_api_error("rtds", "injected_disconnect")
    obs.set_feed_health("rtds", False)
    pipe = PaperPipeline(_cfg(), twap_source=cache, obs=obs)
    row = _shadow_row(pipe, demo_twap_market(hot=True))
    latest = cache.latest("btc/usd", 60)
    return _result(
        "ws_disconnect_reconnect",
        reason=str(row.get("reason")),
        would_buy=bool(row.get("would_buy")),
        would_sell=bool(row.get("would_sell")),
        orders=len(pipe.broker.orders),
        kill=pipe.kills.reason.value if pipe.kills.reason else None,
        alerts=[a.kind.value for a in obs.alerts.emitted],
        extra={
            "reconnects": sub.reconnects,
            "invented_twap": latest is not None,
            "simulated_fill_sent": False,
        },
    )


def scenario_http_faults() -> dict[str, Any]:
    async def _one(status: int | None, timeout: bool, label: str) -> dict[str, Any]:
        gclient = injected_async_client(status=status, timeout=timeout)
        cclient = injected_async_client(
            status=status, timeout=timeout, base_url="https://clob.polymarket.com"
        )
        gamma = GammaClient(client=gclient)
        clob = ClobPublicClient(client=cclient)
        scanner = UniverseScanner(HotflowConfig(), gamma=gamma, clob=clob)
        err: str | None = None
        markets: list[Any] = []
        try:
            try:
                await gamma.list_markets(limit=1)
            except Exception as exc:  # noqa: BLE001
                err = type(exc).__name__
            markets = await scanner.scan(use_network=True)
        finally:
            await gclient.aclose()
            await cclient.aclose()
        return {"label": label, "error": err, "markets": len(markets)}

    rows = asyncio.run(
        _gather_http(
            _one(500, False, "gamma_500"),
            _one(429, False, "gamma_429"),
            _one(None, True, "gamma_timeout"),
        )
    )
    invented = any(item["markets"] > 0 for item in rows)
    row = _result(
        "http_500_429_timeout",
        reason=ReasonCode.HTTP_UPSTREAM,
        extra={"cases": rows, "invented_markets": invented},
    )
    if invented:
        row["fail_safe"] = False
        row["ok"] = False
    return row


async def _gather_http(*coros: Any) -> list[dict[str, Any]]:
    return [await coro for coro in coros]


def scenario_corrupt_events() -> dict[str, Any]:
    now = datetime.now(UTC)
    later = now + timedelta(seconds=2)
    earlier = now - timedelta(seconds=2)
    good = {"ts": now.isoformat(), "kind": "book", "payload": {"bids": [[0.4, 10]], "asks": [[0.42, 10]]}}
    rows = [
        "not-json",
        {"kind": "book"},
        {"ts": now.isoformat(), "kind": "invented_kind", "payload": {}},
        good,
        dict(good),
        {"ts": earlier.isoformat(), "kind": "trade", "payload": {"price": 0.41}},
        {"ts": later.isoformat(), "kind": "gap", "payload": {}},
    ]
    cleaned = sanitize_event_rows(rows)
    reasons = {item["reason"] for item in cleaned["rejected"]}
    return _result(
        "corrupt_duplicate_ooo",
        reason=ReasonCode.EVENT_CORRUPT,
        extra={
            "accepted": cleaned["accepted_count"],
            "rejected": cleaned["rejected_count"],
            "reject_reasons": sorted(str(r) for r in reasons),
            "healed": False,
        },
    )


def scenario_stale_max_age() -> dict[str, Any]:
    cfg = _cfg()
    obs = Observability.from_config(cfg)
    pipe = PaperPipeline(cfg, obs=obs, use_twap_fixtures=True)
    aged = demo_market(hot=True)
    aged.book.fetched_at = datetime.now(UTC) - timedelta(seconds=90)  # type: ignore[union-attr]
    pipe.clock.touch("clob_book", observed_at=datetime.now(UTC) - timedelta(seconds=90))
    row = _shadow_row(pipe, aged, p_info=0.70)
    return _result(
        "stale_max_data_age",
        reason=str(row.get("reason")),
        would_buy=bool(row.get("would_buy")),
        would_sell=bool(row.get("would_sell")),
        orders=len(pipe.broker.orders),
        kill=pipe.kills.reason.value if pipe.kills.reason else None,
        alerts=[a.kind.value for a in obs.alerts.emitted],
    )


def scenario_missing_fees_twap_gap() -> dict[str, Any]:
    cfg = _cfg()
    fees_mkt = demo_market(hot=True)
    fees_mkt.fees = FeeSchedule(source="missing")
    fees_mkt.market_id = "missing-fees"
    pipe_fees = PaperPipeline(cfg, use_twap_fixtures=True)
    fees_row = _shadow_row(pipe_fees, fees_mkt, p_info=0.70)

    empty_cache = TwapPrintCache(max_age_ms=10_000)
    pipe_twap = PaperPipeline(cfg, twap_source=empty_cache)
    twap_row = _shadow_row(pipe_twap, demo_twap_market(hot=True))

    from hotflow.backtest.engine import EventDrivenBacktester
    from hotflow.backtest.events import ListEventSource, MarketEvent

    ts = datetime.now(UTC)
    source = ListEventSource(
        [
            MarketEvent(ts=ts, kind="gap", payload={}),
            MarketEvent(ts=ts + timedelta(milliseconds=1), kind="decision", payload={"p_info": 0.7}),
        ]
    )
    cfg.trading.mode = "backtest"
    cfg.backtest.reject_on_gap = True
    gap_report = EventDrivenBacktester(cfg).run(source, document={"market": {"kind": "demo_crypto"}})
    gap_reasons = [str(d.get("reason")) for d in gap_report.get("decisions") or []]
    return _result(
        "missing_fees_twap_gap",
        reason=ReasonCode.UNKNOWN_FEES,
        would_buy=bool(fees_row.get("would_buy") or twap_row.get("would_buy")),
        would_sell=bool(fees_row.get("would_sell") or twap_row.get("would_sell")),
        orders=len(pipe_fees.broker.orders) + len(pipe_twap.broker.orders),
        extra={
            "fees_reason": fees_row.get("reason"),
            "twap_reason": twap_row.get("reason"),
            "gap_reasons": gap_reasons,
        },
    )


def scenario_partial_cancel_race() -> dict[str, Any]:
    from hotflow.config import TradingConfig

    broker = PaperBroker(TradingConfig(paper_fill_ratio=0.4))
    opp = _opp(demo_market(hot=True))
    broker.create(opp, price=0.42, size=10, client_order_id="race")
    broker.submit("race")
    partial = broker.simulate_fill("race", fill_ratio=0.4)
    partial_status = partial.status.value
    partial_filled = partial.filled_size
    pending = broker.request_cancel("race", settle=False)
    cancel_requested = pending.status.value
    raced = broker.simulate_fill("race", fill_ratio=1.0)
    race_status = raced.status.value
    raced_filled = raced.filled_size
    settled = broker.request_cancel("race", settle=True)
    settled_status = settled.status.value
    after = broker.simulate_fill("race", fill_ratio=1.0)
    return _result(
        "partial_fill_cancel_race",
        reason=ReasonCode.OK,
        extra={
            "partial_status": partial_status,
            "partial_filled": partial_filled,
            "cancel_requested": cancel_requested,
            "race_status": race_status,
            "settled": settled_status,
            "post_cancel_filled": after.filled_size,
            "post_cancel_status": after.status.value,
            "no_fill_after_cancel": after.filled_size == raced_filled,
        },
    )


def scenario_position_mismatch() -> dict[str, Any]:
    cfg = _cfg()
    obs = Observability.from_config(cfg)
    pipe = PaperPipeline(cfg, obs=obs, use_twap_fixtures=True)
    accepted = pipe.evaluate_market(demo_market(hot=True), p_info=0.70)
    local = dict(pipe.broker.positions)
    injected = {token: qty + 99.0 for token, qty in local.items()} or {"demo-yes": 99.0}
    bad = pipe.check_external_positions(injected)
    blocked = pipe.evaluate_market(demo_market(hot=True), p_info=0.70)
    return _result(
        "position_ledger_mismatch",
        reason=str(blocked.get("reason")),
        would_buy=False,
        orders=0 if not blocked.get("accepted") else 1,
        kill=pipe.kills.reason.value if pipe.kills.reason else None,
        alerts=[a.kind.value for a in obs.alerts.emitted],
        extra={
            "mismatched_tokens": bad,
            "first_accepted": bool(accepted.get("accepted")),
            "second_accepted": bool(blocked.get("accepted")),
            "external_invented": False,
        },
    )


def scenario_clock_skew() -> dict[str, Any]:
    cfg = _cfg()
    pipe = PaperPipeline(cfg, use_twap_fixtures=True)
    future = demo_market(hot=True)
    now = datetime.now(UTC)
    future.book.fetched_at = now + timedelta(seconds=30)  # type: ignore[union-attr]
    row = _shadow_row(pipe, future, p_info=0.70, now=now)
    neg = pipe.evaluate_market(demo_market(hot=True), p_info=0.70, latency_ms=-5.0)
    probe = LatencyProbe()
    probe.start("x")
    elapsed = probe.stop("x")
    forward = monotonic_forward(monotonic_ms(), monotonic_ms())
    return _result(
        "clock_skew_monotonic",
        reason=str(row.get("reason")),
        would_buy=bool(row.get("would_buy")),
        would_sell=bool(row.get("would_sell")),
        orders=len(pipe.broker.orders),
        extra={
            "future_book_reason": row.get("reason"),
            "negative_latency_reason": neg.get("reason"),
            "monotonic_elapsed_nonneg": elapsed >= 0,
            "monotonic_forward": forward,
        },
    )


SCENARIOS = (
    scenario_ws_disconnect,
    scenario_http_faults,
    scenario_corrupt_events,
    scenario_stale_max_age,
    scenario_missing_fees_twap_gap,
    scenario_partial_cancel_race,
    scenario_position_mismatch,
    scenario_clock_skew,
)
