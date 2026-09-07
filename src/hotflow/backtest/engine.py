"""Event-driven backtester. Decisions see only events at or before now."""

from __future__ import annotations

from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from hotflow.analytics.experiments import git_commit
from hotflow.backtest.events import (
    EventSource,
    FixtureEventSource,
    ListEventSource,
    MarketEvent,
    candle_only,
    fee_schedule_marked,
    market_from_fixture,
    order_book_from_payload,
)
from hotflow.backtest.fills import FillAssumptions, fill_delay, simulate_execution
from hotflow.backtest.metrics import summarize_trades
from hotflow.backtest.splits import assign_split, parse_split, walk_forward_windows
from hotflow.config import HotflowConfig
from hotflow.fairvalue.esports import FixtureEsportsSource
from hotflow.marketdata.rtds_twap import FixtureTwapSource
from hotflow.marketdata.sports_ws import FixtureSportsSource
from hotflow.marketdata.weather_fixtures import FixtureWeatherSource
from hotflow.monitoring.observer import Observability
from hotflow.pipeline import PaperPipeline
from hotflow.reason_codes import ReasonCode
from hotflow.types import (
    LiquidityStyle,
    MarketRecord,
    OfficialTwapObservation,
    OrderBook,
    Side,
    SportsGameState,
    WeatherForecast,
)


class EventDrivenBacktester:
    def __init__(self, config: HotflowConfig, obs: Observability | None = None) -> None:
        self.config = config
        self.obs = obs or Observability.from_config(config, announce_restart=False)
        cfg = config.backtest
        self.assumptions = FillAssumptions(
            latency_ms=cfg.latency_ms,
            taker_delay_ms=cfg.taker_delay_ms,
            queue_penalty=cfg.queue_penalty,
            partial_fill_ratio=config.trading.paper_fill_ratio,
            maker_fill_probability=config.maker_taker.maker_fill_probability,
            reject_on_gap=cfg.reject_on_gap,
        )

    def run_fixture(self, path: str | Path) -> dict[str, Any]:
        source = FixtureEventSource(path)
        return self.run(source, document=source.document, fixture_path=str(path))

    def run(
        self,
        source: EventSource,
        *,
        document: dict[str, Any] | None = None,
        fixture_path: str | None = None,
        market: MarketRecord | None = None,
    ) -> dict[str, Any]:
        self.config.trading.mode = "backtest"
        events = list(source.events())
        doc = document or {}
        if self.config.backtest.refuse_candle_only and candle_only(events):
            return self._refused(
                ReasonCode.CANDLE_ONLY_REFUSED,
                events,
                fixture_path,
                "book/trade events required when strategies use book features",
            )
        template = market or market_from_fixture(doc if doc else {"market": {"kind": "demo_crypto"}})
        if not fee_schedule_marked(template.fees, doc):
            return self._refused(
                ReasonCode.UNKNOWN_FEES,
                events,
                fixture_path,
                "historical fee schedule must be dated/marked",
            )

        twap_source = FixtureTwapSource(observations={})
        weather_source = FixtureWeatherSource()
        sports_source = FixtureSportsSource()
        esports_source = FixtureEsportsSource()
        pipe = PaperPipeline(
            self.config,
            twap_source=twap_source,
            weather_source=weather_source,
            sports_source=sports_source,
            esports_source=esports_source,
            obs=self.obs,
        )

        book: OrderBook | None = template.book
        gap = False
        last_trade: float | None = None
        token_id = template.token_ids[0] if template.token_ids else "unknown"
        decisions: list[dict[str, Any]] = []
        trades: list[dict[str, Any]] = []
        skip_counts: Counter[str] = Counter()
        fees_total = 0.0
        slippage_total = 0.0
        position = 0.0
        avg_entry = 0.0
        realized = 0.0
        starting = self.config.trading.paper_starting_cash
        equity = [starting]
        split_cfg = parse_split(doc.get("split") or self.config.backtest.split.model_dump())

        for event in events:
            book, gap, last_trade = self._apply(
                event,
                book=book,
                gap=gap,
                last_trade=last_trade,
                token_id=token_id,
                twap_source=twap_source,
                weather_source=weather_source,
                sports_source=sports_source,
                esports_source=esports_source,
            )
            if event.kind == "resolve":
                price = float(event.payload.get("price") or 0.0)
                realized += self._close(trades, position, avg_entry, price)
                position = 0.0
                avg_entry = 0.0
                equity.append(starting + realized)
                continue
            if event.kind != "decision":
                continue
            if gap:
                skip_counts[ReasonCode.DATA_GAP] += 1
                decisions.append(
                    {
                        "ts": event.ts.isoformat(),
                        "accepted": False,
                        "reason": ReasonCode.DATA_GAP,
                        "split": assign_split(event.ts, split_cfg),
                    }
                )
                continue
            snapshot = self._market(template, book, last_trade, event.ts)
            result = pipe.evaluate_market(
                snapshot,
                latency_ms=self.assumptions.latency_ms,
                p_info=event.payload.get("p_info"),
                now=event.ts,
            )
            reason = str(result.get("reason") or ReasonCode.NO_TRADE)
            accepted = bool(result.get("accepted") and result.get("backtest_intent"))
            row = {
                "ts": event.ts.isoformat(),
                "accepted": accepted,
                "reason": reason,
                "expected_price": result.get("expected_price"),
                "book_ask": snapshot.book.best_ask if snapshot.book else None,
                "book_bid": snapshot.book.best_bid if snapshot.book else None,
                "split": assign_split(event.ts, split_cfg),
                "lookahead": False,
            }
            decisions.append(row)
            if not accepted:
                skip_counts[reason] += 1
                continue
            style = LiquidityStyle(str(result.get("style") or LiquidityStyle.TAKER.value))
            side = Side(str(result.get("side") or Side.BUY.value))
            shares = float(result.get("shares") or 0.0)
            fill_ts = event.ts + fill_delay(style, self.assumptions)
            fill_book, fill_gap = self._peek_book(events, event, fill_ts, book, gap, token_id)
            fill = simulate_execution(
                side=side,
                style=style,
                intended_shares=shares,
                book=fill_book,
                fees=snapshot.fees,
                assumptions=self.assumptions,
                seed=f"{event.ts.isoformat()}|{template.market_id}|{len(trades)}",
                fill_ts=fill_ts,
                gap=fill_gap,
            )
            if not fill.filled or fill.price is None:
                skip_counts[fill.reason] += 1
                row["fill"] = fill.as_dict()
                continue
            fees_total += fill.fee
            slippage_total += fill.slippage
            realized -= fill.fee
            if side == Side.BUY:
                new_pos = position + fill.size
                avg_entry = (
                    (avg_entry * position + fill.price * fill.size) / new_pos if new_pos else 0.0
                )
                position = new_pos
            else:
                position -= fill.size
            pipe.risk.note_fill(
                market_id=template.market_id,
                category=template.category or "crypto",
                notional=fill.size * fill.price,
            )
            pipe.risk.state.last_order_at = fill_ts
            trade = {
                "ts": fill_ts.isoformat(),
                "decision_ts": event.ts.isoformat(),
                "side": side.value,
                "size": fill.size,
                "price": fill.price,
                "fee": fill.fee,
                "slippage": fill.slippage,
                "style": fill.style,
                "split": assign_split(event.ts, split_cfg),
                "pnl": None,
            }
            trades.append(trade)
            row["fill"] = fill.as_dict()
            mark = fill_book.mid if fill_book and fill_book.mid is not None else fill.price
            unrealized = position * (mark - avg_entry) if position else 0.0
            equity.append(starting + realized + unrealized)

        if position and book and book.mid is not None:
            realized += self._close(trades, position, avg_entry, book.mid, marked=True)
            equity.append(starting + realized)

        metrics = summarize_trades(
            [item for item in trades if item.get("pnl") is not None],
            equity=equity,
            skip_counts=dict(skip_counts),
            fees_total=fees_total,
            slippage_total=slippage_total,
        )
        if not any(item.get("pnl") is not None for item in trades):
            metrics = summarize_trades(
                trades,
                equity=equity,
                skip_counts=dict(skip_counts),
                fees_total=fees_total,
                slippage_total=slippage_total,
            )
        split_metrics = {
            name: summarize_trades(
                [item for item in trades if item.get("split") == name and item.get("pnl") is not None]
                or [item for item in trades if item.get("split") == name],
                equity=equity,
                skip_counts={
                    key: sum(
                        1
                        for row in decisions
                        if row.get("split") == name and not row.get("accepted") and row.get("reason") == key
                    )
                    for key in skip_counts
                },
                fees_total=sum(float(item["fee"]) for item in trades if item.get("split") == name),
                slippage_total=sum(float(item["slippage"]) for item in trades if item.get("split") == name),
            )
            for name in ("train", "validation", "oos")
        }
        start = events[0].ts if events else datetime.now(UTC)
        end = events[-1].ts if events else start
        wf = self.config.backtest.walk_forward
        windows = (
            walk_forward_windows(
                start,
                end,
                train_seconds=wf.train_seconds,
                test_seconds=wf.test_seconds,
                step_seconds=wf.step_seconds,
            )
            if wf.enabled
            else []
        )
        payload = {
            "mode": "backtest",
            "backtest_id": str(uuid4()),
            "fixture": fixture_path,
            "git_commit": git_commit(),
            "lookahead": False,
            "selection_rule": "refuses_max_abs_pnl",
            "assumptions": {
                "latency_ms": self.assumptions.latency_ms,
                "taker_delay_ms": self.assumptions.taker_delay_ms,
                "queue_penalty": self.assumptions.queue_penalty,
                "partial_fill_ratio": self.assumptions.partial_fill_ratio,
                "maker_fill_probability": self.assumptions.maker_fill_probability,
                "reject_on_gap": self.assumptions.reject_on_gap,
                "note": self.assumptions.note,
                "fees": {
                    "source": template.fees.source,
                    "rate": template.fees.rate,
                    "as_of": template.fees.fetched_at.isoformat(),
                    "marked": True,
                },
            },
            "metrics": metrics,
            "splits": split_metrics,
            "walk_forward": {"status": "stub", "windows": windows},
            "decisions": decisions,
            "trades": trades,
            "event_count": len(events),
            "kinds": sorted({item.kind for item in events}),
        }
        self.obs.observe_backtest_report(payload)
        self.obs.snapshot_pipeline(pipe)
        return payload

    def _refused(
        self,
        reason: str,
        events: list[MarketEvent],
        fixture_path: str | None,
        detail: str,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "mode": "backtest",
            "fixture": fixture_path,
            "accepted": False,
            "reason": reason,
            "detail": detail,
            "lookahead": False,
            "selection_rule": "refuses_max_abs_pnl",
            "metrics": summarize_trades(
                [],
                equity=[self.config.trading.paper_starting_cash],
                skip_counts={reason: 1},
                fees_total=0.0,
                slippage_total=0.0,
            ),
            "decisions": [],
            "trades": [],
            "event_count": len(events),
        }
        self.obs.observe_backtest_report(payload)
        return payload

    def _apply(
        self,
        event: MarketEvent,
        *,
        book: OrderBook | None,
        gap: bool,
        last_trade: float | None,
        token_id: str,
        twap_source: FixtureTwapSource,
        weather_source: FixtureWeatherSource,
        sports_source: FixtureSportsSource,
        esports_source: FixtureEsportsSource,
    ) -> tuple[OrderBook | None, bool, float | None]:
        payload = event.payload
        if event.kind == "book":
            return order_book_from_payload(payload, token_id=token_id, ts=event.ts), False, last_trade
        if event.kind == "trade" and payload.get("price") is not None:
            return book, gap, float(payload["price"])
        if event.kind == "gap":
            return None, True, last_trade
        if event.kind == "twap":
            window = int(payload.get("window_seconds") or payload.get("window_s") or 0)
            symbol = str(payload.get("symbol") or "")
            if symbol and window:
                twap_source.put(
                    OfficialTwapObservation(
                        symbol=symbol,
                        window_seconds=window,
                        value=float(payload["value"]),
                        observed_at=event.ts,
                        source="backtest_fixture",
                    )
                )
        if event.kind == "weather_forecast":
            weather_source.put(
                str(payload.get("key") or "default"),
                WeatherForecast(
                    mean=payload.get("mean"),
                    p_yes=payload.get("p_yes"),
                    p_above_threshold=payload.get("p_above_threshold"),
                    source="backtest_fixture",
                    observed_at=event.ts,
                ),
            )
        if event.kind == "sports_state":
            sports_source.put(
                SportsGameState(
                    league_abbreviation=payload.get("league_abbreviation") or payload.get("leagueAbbreviation"),
                    home_team=payload.get("home_team") or payload.get("homeTeam"),
                    away_team=payload.get("away_team") or payload.get("awayTeam"),
                    status=payload.get("status"),
                    live=payload.get("live"),
                    ended=payload.get("ended"),
                    score=payload.get("score"),
                    period=payload.get("period"),
                    last_update=event.ts,
                    source="backtest_fixture",
                )
            )
        if event.kind == "esports_state":
            esports_source.put(
                SportsGameState(
                    league_abbreviation=payload.get("league_abbreviation"),
                    home_team=payload.get("home_team"),
                    away_team=payload.get("away_team"),
                    status=payload.get("status"),
                    ended=payload.get("ended"),
                    score=payload.get("score"),
                    last_update=event.ts,
                    source="backtest_fixture",
                )
            )
        return book, gap, last_trade

    def _peek_book(
        self,
        events: list[MarketEvent],
        origin: MarketEvent,
        until: datetime,
        book: OrderBook | None,
        gap: bool,
        token_id: str,
    ) -> tuple[OrderBook | None, bool]:
        """Book at fill time (decision_ts + latency). Not used for the decision."""
        current = book
        current_gap = gap
        for event in events:
            if event.seq <= origin.seq:
                continue
            if event.ts > until:
                break
            if event.kind == "gap":
                current, current_gap = None, True
            elif event.kind == "book":
                current = order_book_from_payload(event.payload, token_id=token_id, ts=event.ts)
                current_gap = False
        return current, current_gap

    def _market(
        self,
        template: MarketRecord,
        book: OrderBook | None,
        last_trade: float | None,
        ts: datetime,
    ) -> MarketRecord:
        market = template.model_copy(deep=True)
        market.fetched_at = ts
        if book is not None:
            copied = book.model_copy(deep=True)
            copied.fetched_at = ts
            market.book = copied
            market.best_bid = copied.best_bid
            market.best_ask = copied.best_ask
            market.spread = copied.spread
        else:
            market.book = None
            market.best_bid = None
            market.best_ask = None
            market.spread = None
        if last_trade is not None:
            market.last_trade_price = last_trade
        if market.fees.known:
            # Dated schedule stays valid for the replay clock; do not invent a new rate.
            market.fees = market.fees.model_copy(update={"fetched_at": ts})
        return market

    def _close(
        self,
        trades: list[dict[str, Any]],
        position: float,
        avg_entry: float,
        price: float,
        *,
        marked: bool = False,
    ) -> float:
        if position <= 0 or not trades:
            return 0.0
        open_rows = [item for item in trades if item.get("pnl") is None]
        if not open_rows:
            return 0.0
        realized = 0.0
        remaining = position
        for item in open_rows:
            size = float(item["size"])
            take = min(remaining, size)
            pnl = take * (price - float(item["price"])) - float(item.get("fee") or 0.0)
            item["pnl"] = pnl
            item["exit_price"] = price
            item["marked_to_mid"] = marked
            realized += pnl
            remaining -= take
            if remaining <= 1e-12:
                break
        return realized


class NullBacktester:
    """Empty-stream smoke used by the offline experiment script."""

    def run(self, source: EventSource) -> dict[str, Any]:
        count = sum(1 for _ in source.events())
        return {"events": count, "status": "empty" if count == 0 else "counted", "mode": "offline"}


def list_source(events: list[MarketEvent]) -> ListEventSource:
    return ListEventSource(events)
