"""Shared paper session: one ledger across cycles, soak report, kill drill."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from hotflow.config import HotflowConfig
from hotflow.monitoring.observer import Observability
from hotflow.pipeline import (
    PaperPipeline,
    demo_sports_nba_market,
    demo_twap_market,
    demo_weather_market,
    gamma_esports_demo_markets,
    gamma_weather_demo_markets,
)
from hotflow.portfolio.ledger import PaperLedger
from hotflow.reason_codes import ReasonCode
from hotflow.storage.sqlite_store import SqliteStore
from hotflow.types import KillSwitchReason, MarketRecord


def mock_markets() -> list[MarketRecord]:
    return [
        demo_twap_market(hot=True),
        demo_weather_market(hot=True),
        demo_sports_nba_market(hot=True),
        *gamma_weather_demo_markets(hot=True),
        *gamma_esports_demo_markets(hot=True),
    ]


class PaperSession:
    """One pipeline + ledger for a paper soak. Recreating the pipeline resets risk."""

    def __init__(
        self,
        config: HotflowConfig,
        store: SqliteStore | None = None,
        *,
        obs: Observability | None = None,
        use_twap_fixtures: bool = False,
        cache_path: str | None = None,
        sports_cache_path: str | None = None,
        use_news_fixtures: bool = False,
        news_engine: Any | None = None,
    ) -> None:
        self.config = config
        self.obs = obs or Observability.from_config(config, announce_restart=False)
        self.ledger = PaperLedger(
            starting_cash=config.trading.paper_starting_cash,
            session_id=config.trading.session_id,
        )
        self.pipe = PaperPipeline(
            config,
            store,
            use_twap_fixtures=use_twap_fixtures,
            cache_path=cache_path,
            sports_cache_path=sports_cache_path,
            obs=self.obs,
            ledger=self.ledger,
            news_engine=news_engine,
            use_news_fixtures=use_news_fixtures,
        )
        self.marks: dict[str, float] = {}
        self.cycle_summaries: list[dict[str, Any]] = []

    def _remember_marks(self, market: MarketRecord, result: dict[str, Any]) -> None:
        token = market.token_ids[0] if market.token_ids else None
        mid = market.book.mid if market.book else None
        order = result.get("order") if isinstance(result.get("order"), dict) else None
        if mid is None and order is not None:
            mid = order.get("avg_fill_price") or order.get("price")
        if token is None or mid is None:
            return
        price = float(mid)
        self.marks[token] = price
        self.ledger.mark(token, price, market_id=market.market_id)

    def run_markets(
        self,
        markets: list[MarketRecord],
        *,
        p_info: float | None = None,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        results = self.pipe.evaluate_markets(markets, p_info=p_info, now=now)
        for market, result in zip(markets, results, strict=True):
            self._remember_marks(market, result)
        self.obs.snapshot_pipeline(self.pipe)
        snap = self.ledger.snapshot()
        self.obs.publish_ledger(snap)
        summary = {
            "ok": True,
            "mode": self.config.trading.mode,
            "markets": len(results),
            "accepted": sum(1 for item in results if item.get("accepted")),
            "results": results,
            "accounting": snap.as_dict(),
        }
        self.cycle_summaries.append(summary)
        return summary

    def flatten(self, *, note: str = "session_flatten") -> list[dict[str, Any]]:
        events = self.ledger.flatten(self.marks, note=note)
        for event in events:
            if event.closed:
                self.obs.metrics.note_closed_trade(event.realized_delta)
            if self.pipe.store:
                self.pipe.store.save_ledger_event(event)
        self.pipe.risk.sync_from_ledger(self.ledger.snapshot())
        self.pipe.risk.enforce_session_limits()
        self.obs.publish_ledger(self.ledger.snapshot())
        if self.pipe.store:
            self.pipe.store.save_ledger_snapshot(self.ledger.snapshot())
        return [event.as_dict() for event in events]

    def report(self) -> dict[str, Any]:
        snap = self.ledger.snapshot()
        return {
            "mode": self.config.trading.mode,
            "session_id": self.config.trading.session_id,
            "cycles": self.cycle_summaries,
            "cycle_count": len(self.cycle_summaries),
            "shadow": self.config.trading.shadow,
            "accounting": snap.as_dict(),
            "events": [event.as_dict() for event in self.ledger.events],
            "kill_switch": {
                "tripped": self.pipe.kills.tripped,
                "reason": self.pipe.kills.reason.value if self.pipe.kills.reason else None,
            },
        }


def run_kill_recovery_drill(
    session: PaperSession,
    *,
    acknowledge: str | None = None,
    open_price: float = 0.50,
    close_price: float = 0.20,
    size: float = 2_000.0,
) -> dict[str, Any]:
    """Trip via an explicit paper round-trip that exceeds daily-loss, then recover.

    Prices are arguments (not invented venue prints). New paper orders must block
    until `KillSwitchBoard.reset(acknowledge=...)`.
    """
    token = "paper-kill-drill"
    market_id = "paper-kill-drill"
    opened = session.ledger.apply_fill(
        token_id=token,
        market_id=market_id,
        side="BUY",
        size=size,
        price=open_price,
        fee=0.0,
        note="kill_drill_open",
    )
    closed = session.ledger.apply_fill(
        token_id=token,
        market_id=market_id,
        side="SELL",
        size=size,
        price=close_price,
        fee=0.0,
        note="kill_drill_close",
    )
    if closed.closed:
        session.obs.metrics.note_closed_trade(closed.realized_delta)
    session.pipe.risk.sync_from_ledger(session.ledger.snapshot())
    session.pipe.risk.enforce_session_limits()
    session.obs.publish_ledger(session.ledger.snapshot())
    trip_reason = session.pipe.kills.reason.value if session.pipe.kills.reason else None
    probe = demo_twap_market(hot=True)
    probe.market_id = "paper-kill-drill-probe"
    blocked = session.pipe.evaluate_market(probe, p_info=0.70)
    blank_error = None
    try:
        session.pipe.kills.reset(acknowledge="")
    except ValueError as exc:
        blank_error = str(exc)
    recovered = False
    if acknowledge and acknowledge.strip():
        session.pipe.kills.reset(acknowledge=acknowledge)
        recovered = not session.pipe.kills.tripped
    return {
        "open": opened.as_dict(),
        "close": closed.as_dict(),
        "realized_delta": closed.realized_delta,
        "tripped": trip_reason is not None,
        "kill_reason": trip_reason or KillSwitchReason.DAILY_LOSS_EXCEEDED.value,
        "blocked_reason": blocked.get("reason"),
        "blocked_accepted": bool(blocked.get("accepted")),
        "blank_ack_rejected": blank_error is not None,
        "recovered": recovered,
        "acknowledge_used": bool(acknowledge and acknowledge.strip()),
        "probe_reason_ok": blocked.get("reason") == ReasonCode.KILL_SWITCH,
    }
