"""Mixed PAPER soak: 5m/15m crypto + news + uncorrelated names through the allocator.

Deterministic fixtures only (no Gamma scan, no invented rho). Exercises
Parte 24 allocation and Parte 25 regime overlays on one book. Risk VETO is
unchanged. Prices and news items are fixture arguments.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from hotflow.config import RegimeStrategyConfig
from hotflow.news.item import NewsClass, NewsItem
from hotflow.pipeline import demo_crypto_window_market, demo_sports_nba_market, demo_weather_market
from hotflow.portfolio.session import PaperSession
from hotflow.reason_codes import ReasonCode
from hotflow.types import MarketRecord

ORIGIN = "mixed_fixture_book"
DEFAULT_MIXED_CYCLES = 5
P_INFO = 0.70
OVERLAY_IDS = ("news_shock", "near_resolution", "liquidity_vacuum")

BTC_5M = "soak-btc-5m"
ETH_5M = "soak-eth-5m"
BTC_15M = "soak-btc-15m"
ETH_15M = "soak-eth-15m"
WEATHER_ID = "demo-weather-chicago"
SPORTS_ID = "demo-nba-lal-bos"

CROSS_WINDOW_NOTE = (
    "5m vs 15m: same_category_window links only equal parsed windows "
    "(BTC 5m↔ETH 5m, BTC 15m↔ETH 15m). same_underlying links BTC 5m↔BTC 15m. "
    "YAML crypto_short_window joins all 5m/15m/30s/60s (max_markets=1 by default) "
    "— not a measured rho. Cross-window TAKEs are not expected on the default group."
)


@dataclass(frozen=True)
class CycleSpec:
    name: str
    flatten_after: bool
    attach_news: bool = False
    weather_near: bool = False
    crypto_near: bool = False
    downsize_crypto_group: bool = False
    disable_crypto_normal: bool = False


DEFAULT_PLAN: tuple[CycleSpec, ...] = (
    CycleSpec("baseline", flatten_after=True),
    CycleSpec("news_shock", flatten_after=True, attach_news=True),
    CycleSpec("near_resolution", flatten_after=True, weather_near=True, crypto_near=True),
    CycleSpec("partial_room", flatten_after=False, downsize_crypto_group=True),
    CycleSpec("carry", flatten_after=False),
)


def cycle_plan(n: int) -> list[CycleSpec]:
    if n < 1:
        raise ValueError("mixed soak cycles must be >= 1")
    plan = list(DEFAULT_PLAN)
    if n <= len(plan):
        return plan[:n]
    extra = n - len(plan)
    pad = [CycleSpec("baseline", flatten_after=True) for _ in range(extra)]
    return plan[:-1] + pad + [plan[-1]]


def _iso(stamp: datetime) -> str:
    return stamp.strftime("%Y-%m-%dT%H:%M:%SZ")


def _stamp_close(market: MarketRecord, close: datetime) -> MarketRecord:
    raw = dict(market.raw_gamma or {})
    raw["endDate"] = _iso(close)
    resolution = market.resolution.model_copy(update={"end_date": _iso(close)})
    return market.model_copy(update={"resolution": resolution, "raw_gamma": raw})


def _with_token(market: MarketRecord, token_id: str) -> MarketRecord:
    book = market.book.model_copy(update={"token_id": token_id}) if market.book is not None else None
    return market.model_copy(update={"token_ids": [token_id], "book": book})


def mixed_soak_markets(
    *,
    now: datetime | None = None,
    weather_near: bool = False,
    crypto_near: bool = False,
) -> list[MarketRecord]:
    """One scan book: BTC/ETH 5m + BTC/ETH 15m + Chicago weather + NBA."""
    stamp = now or datetime.now(UTC)
    crypto_close = stamp + timedelta(minutes=10 if crypto_near else 240)
    weather_close = stamp + timedelta(minutes=20 if weather_near else 12 * 60)
    sports_close = stamp + timedelta(hours=3)
    names = [
        demo_crypto_window_market(symbol="btc/usd", window="5m", market_id=BTC_5M),
        demo_crypto_window_market(symbol="eth/usd", window="5m", market_id=ETH_5M),
        demo_crypto_window_market(symbol="btc/usd", window="15m", market_id=BTC_15M),
        demo_crypto_window_market(symbol="eth/usd", window="15m", market_id=ETH_15M),
    ]
    crypto = [_stamp_close(item, crypto_close) for item in names]
    weather = _with_token(_stamp_close(demo_weather_market(hot=True), weather_close), f"{WEATHER_ID}-yes")
    sports = _with_token(_stamp_close(demo_sports_nba_market(hot=True), sports_close), f"{SPORTS_ID}-yes")
    return [*crypto, weather, sports]


def news_shock_items(*, now: datetime, cycle: int) -> list[NewsItem]:
    """Validated official fixtures bound to soak crypto ids. Not live headlines."""
    published = now - timedelta(minutes=5)
    items: list[NewsItem] = []
    for market_id, terms in (
        (BTC_5M, ["btc", "5m"]),
        (ETH_5M, ["eth", "5m"]),
        (BTC_15M, ["btc", "15m"]),
        (ETH_15M, ["eth", "15m"]),
    ):
        items.append(
            NewsItem(
                news_id=f"soak-shock-{market_id}-{cycle}",
                headline=f"SEC filing names {market_id} up/down window terms",
                body="Labeled mixed-soak fixture. Official-source text only.",
                source_id="sec.gov",
                source_name="SEC EDGAR (fixture)",
                published_at=published,
                market_id=market_id,
                resolution_terms=list(terms),
                event_key=f"soak-shock-{market_id}-{cycle}",
                classification_label=NewsClass.OFFICIAL,
                claimed_p_shift=0.08,
                pre_event_mid=0.41,
                origin="fixture",
                labels={"role": "mixed_soak_news_shock"},
            )
        )
    return items


def _count_overlays(assumptions: list[str], labels: list[str], primary: str | None) -> tuple[list[str], list[str]]:
    blob = " ".join(assumptions)
    applied: list[str] = []
    labeled: list[str] = []
    for overlay in OVERLAY_IDS:
        if f"Regime {overlay}:" in blob:
            applied.append(overlay)
        if overlay in labels or primary == overlay:
            labeled.append(overlay)
    return applied, labeled


def summarize_results(results: list[dict[str, Any]], *, recipe: str) -> dict[str, Any]:
    reasons: Counter[str] = Counter()
    actions: Counter[str] = Counter()
    regimes: Counter[str] = Counter()
    overlay_applied: Counter[str] = Counter()
    overlay_labeled: Counter[str] = Counter()
    windows: Counter[str] = Counter()
    hit_rules: Counter[str] = Counter()
    accepted = 0
    rows: list[dict[str, Any]] = []
    for row in results:
        ok = bool(row.get("accepted"))
        if ok:
            accepted += 1
        reason = str(row.get("reason") or ReasonCode.NO_TRADE)
        reasons[reason] += 1
        port = row.get("portfolio") if isinstance(row.get("portfolio"), dict) else {}
        port = port or {}
        action = port.get("action")
        if action:
            actions[str(action)] += 1
        for hit in port.get("hits") or []:
            rule = str(hit).split(":", 1)[0]
            hit_rules[rule] += 1
        regime = row.get("regime") if isinstance(row.get("regime"), dict) else {}
        regime = regime or {}
        primary = regime.get("primary")
        if primary:
            regimes[str(primary)] += 1
        labels = [str(item) for item in (regime.get("labels") or [])]
        applied, labeled = _count_overlays(
            [str(item) for item in (port.get("assumptions") or [])],
            labels,
            str(primary) if primary else None,
        )
        overlay_applied.update(applied)
        overlay_labeled.update(labeled)
        ident = row.get("exposure_identity") if isinstance(row.get("exposure_identity"), dict) else {}
        ident = ident or {}
        window = ident.get("window")
        if window:
            windows[str(window)] += 1
        news = row.get("news") if isinstance(row.get("news"), dict) else {}
        news = news or {}
        rows.append(
            {
                "market_id": row.get("market_id"),
                "accepted": ok,
                "reason": reason,
                "portfolio": action,
                "allocated_notional": port.get("allocated_notional"),
                "hits": list(port.get("hits") or []),
                "regime": primary,
                "window": window,
                "news_apply": news.get("apply"),
                "overlay_applied": applied,
                "overlay_labeled": labeled,
            }
        )
    return {
        "recipe": recipe,
        "markets": len(results),
        "accepted": accepted,
        "skipped": len(results) - accepted,
        "reasons": dict(reasons),
        "portfolio_actions": dict(actions),
        "regimes": dict(regimes),
        "overlay_applied": dict(overlay_applied),
        "overlay_labeled": dict(overlay_labeled),
        "windows": dict(windows),
        "correlation_hit_rules": dict(hit_rules),
        "rows": rows,
    }


def _add_counters(into: dict[str, int], add: dict[str, int]) -> None:
    for key, value in add.items():
        into[key] = into.get(key, 0) + int(value)


def aggregate_summaries(cycles: list[dict[str, Any]]) -> dict[str, Any]:
    reasons: dict[str, int] = {}
    actions: dict[str, int] = {}
    regimes: dict[str, int] = {}
    overlay_applied: dict[str, int] = {}
    overlay_labeled: dict[str, int] = {}
    accepted = 0
    skipped = 0
    markets = 0
    for item in cycles:
        accepted += int(item.get("accepted") or 0)
        skipped += int(item.get("skipped") or 0)
        markets += int(item.get("markets") or 0)
        _add_counters(reasons, item.get("reasons") or {})
        _add_counters(actions, item.get("portfolio_actions") or {})
        _add_counters(regimes, item.get("regimes") or {})
        _add_counters(overlay_applied, item.get("overlay_applied") or {})
        _add_counters(overlay_labeled, item.get("overlay_labeled") or {})
    return {
        "markets": markets,
        "accepted": accepted,
        "skipped": skipped,
        "reasons": reasons,
        "portfolio_actions": actions,
        "regimes": regimes,
        "overlay_applied": overlay_applied,
        "overlay_labeled": overlay_labeled,
        "correlated_exposure": int(reasons.get(ReasonCode.CORRELATED_EXPOSURE, 0)),
        "portfolio_downsized": int(actions.get("DOWNSIZE", 0)),
        "portfolio_concentration": int(reasons.get(ReasonCode.PORTFOLIO_CONCENTRATION, 0)),
        "regime_disabled": int(reasons.get(ReasonCode.REGIME_DISABLED, 0)),
        "correlation_events": int(reasons.get(ReasonCode.CORRELATED_EXPOSURE, 0))
        + int(actions.get("DOWNSIZE", 0)),
        "regime_overlay_events": sum(overlay_applied.values()),
        "regime_label_events": sum(overlay_labeled.values()),
    }


@dataclass
class _GroupRestore:
    max_markets: int
    max_exposure: float | None


def _apply_downsize_group(session: PaperSession) -> _GroupRestore | None:
    for group in session.config.portfolio.groups:
        if group.id == "crypto_short_window":
            restore = _GroupRestore(group.max_markets, group.max_exposure)
            group.max_markets = 2
            group.max_exposure = 400.0
            return restore
    return None


def _reset_flat_risk(session: PaperSession) -> None:
    """After an explicit flatten, drop residual paper exposure so the next recipe is independent.

    `RiskEngine.sync_from_ledger` copies equity/PnL but does not rebuild concurrent
    markets / category caps / open-order counts. Soak recipes that flatten must
    not inherit PARTIAL paper orders as live concentration.
    """
    session.pipe.exposure.clear()
    session.pipe.broker.cancel_open()
    session.pipe.risk.sync_from_ledger(session.ledger.snapshot())
    if session.ledger.snapshot().positions:
        return
    session.pipe.risk.state.market_exposure.clear()
    session.pipe.risk.state.category_exposure.clear()
    session.pipe.risk.state.total_exposure = 0.0
    session.pipe.risk.state.concurrent_markets.clear()
    session.pipe.risk.state.open_orders = 0
    session.pipe.risk.state.reject_streak = 0


def _restore_group(session: PaperSession, saved: _GroupRestore | None) -> None:
    if saved is None:
        return
    for group in session.config.portfolio.groups:
        if group.id == "crypto_short_window":
            group.max_markets = saved.max_markets
            group.max_exposure = saved.max_exposure
            return


def _set_crypto_disabled(session: PaperSession, labels: list[str]) -> list[str]:
    strat = session.config.regimes.strategies.get("crypto")
    if strat is None:
        strat = RegimeStrategyConfig()
        session.config.regimes.strategies["crypto"] = strat
    previous = list(strat.disabled_regimes)
    strat.disabled_regimes = list(labels)
    return previous


def run_mixed_paper_soak(
    session: PaperSession,
    *,
    cycles: int = DEFAULT_MIXED_CYCLES,
    now: datetime | None = None,
    p_info: float = P_INFO,
) -> dict[str, Any]:
    """Run documented fixture recipes through evaluate_markets. PAPER only."""
    if session.config.trading.mode.lower() == "live":
        raise ValueError("mixed paper soak refuses LIVE mode")
    stamp = now or datetime.now(UTC)
    plan = cycle_plan(cycles)
    cycle_rows: list[dict[str, Any]] = []
    for index, spec in enumerate(plan):
        session.pipe.news.clear()
        if spec.attach_news:
            session.pipe.news.ingest_many(news_shock_items(now=stamp, cycle=index))
        group_saved = _apply_downsize_group(session) if spec.downsize_crypto_group else None
        disabled_saved: list[str] | None = None
        if spec.disable_crypto_normal:
            disabled_saved = _set_crypto_disabled(session, ["normal"])
        markets = mixed_soak_markets(
            now=stamp,
            weather_near=spec.weather_near,
            crypto_near=spec.crypto_near,
        )
        summary = session.run_markets(markets, p_info=p_info, now=stamp)
        audit = summarize_results(summary.get("results") or [], recipe=spec.name)
        audit["flatten_after"] = spec.flatten_after
        audit["attach_news"] = spec.attach_news
        cycle_rows.append(audit)
        if spec.flatten_after:
            session.flatten(note=f"mixed_soak_flatten:{spec.name}")
            _reset_flat_risk(session)
        _restore_group(session, group_saved)
        if disabled_saved is not None:
            _set_crypto_disabled(session, disabled_saved)
    totals = aggregate_summaries(cycle_rows)
    snap = session.ledger.snapshot()
    return {
        "origin": ORIGIN,
        "mixed_soak": True,
        "long_soak": False,
        "live": False,
        "auto_disable": False,
        "fail_safe": True,
        "cycles": len(cycle_rows),
        "recipes": [item["recipe"] for item in cycle_rows],
        "cycle_audits": cycle_rows,
        "totals": totals,
        "cross_window_note": CROSS_WINDOW_NOTE,
        "fixture_note": (
            "Deterministic mixed book (BTC/ETH 5m+15m, Chicago weather, NBA). "
            "No Gamma scan. No estimated correlation. News items are labeled fixtures."
        ),
        "kill_switch": {
            "tripped": session.pipe.kills.tripped,
            "reason": session.pipe.kills.reason.value if session.pipe.kills.reason else None,
        },
        "ledger_summary": {
            "equity": snap.equity,
            "realized_pnl": snap.realized_pnl,
            "unrealized_pnl": snap.unrealized_pnl,
            "closed_count": snap.closed_count,
            "starting_cash": snap.starting_cash,
        },
    }
