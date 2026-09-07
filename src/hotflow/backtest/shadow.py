"""SHADOW mode: real-data decisions logged, never transmitted."""

from __future__ import annotations

from collections import Counter
from typing import Any

from hotflow.config import HotflowConfig
from hotflow.monitoring.observer import Observability
from hotflow.pipeline import PaperPipeline, demo_market
from hotflow.reason_codes import ReasonCode
from hotflow.types import MarketRecord, Side

SHADOW_REQUIRED_FIELDS = (
    "would_buy",
    "would_sell",
    "expected_price",
    "actual_price_after_signal",
    "simulated_fill",
    "reason",
)

STALE_REASONS = {
    ReasonCode.STALE_DATA,
    ReasonCode.TWAP_OBSERVATION_STALE,
    ReasonCode.SPORTS_STATE_STALE,
    ReasonCode.DATA_AGE,
}


def shadow_completeness(row: dict[str, Any]) -> tuple[bool, list[str]]:
    """Keys present for every decision. Prices may be null; fills must not be sent."""
    missing: list[str] = []
    for key in SHADOW_REQUIRED_FIELDS:
        if key not in row:
            missing.append(key)
    if not row.get("reason"):
        if "reason" not in missing:
            missing.append("reason")
    fill = row.get("simulated_fill")
    if not isinstance(fill, dict):
        if "simulated_fill" not in missing:
            missing.append("simulated_fill")
    elif fill.get("sent") is not False:
        missing.append("simulated_fill.sent")
    return (not missing, missing)


def attach_shadow_fields(
    result: dict[str, Any],
    *,
    next_price: float | None = None,
    market_id: str | None = None,
) -> dict[str, Any]:
    """Fill would_* / expected_price / actual_price_after_signal. No orders."""
    opp_raw = result.get("opportunity")
    opportunity: dict[str, Any] = opp_raw if isinstance(opp_raw, dict) else {}
    edge_raw = result.get("edge")
    edge: dict[str, Any] = edge_raw if isinstance(edge_raw, dict) else {}
    if not edge:
        nested = opportunity.get("edge")
        edge = nested if isinstance(nested, dict) else {}
    side = str(result.get("side") or opportunity.get("side") or Side.BUY.value)
    expected = result.get("expected_price")
    if expected is None:
        expected = edge.get("market_price")
    payload = dict(result)
    if market_id and not payload.get("market_id"):
        payload["market_id"] = market_id
    intent = result.get("reason") == ReasonCode.SHADOW_MODE
    payload["would_buy"] = bool(intent and side == Side.BUY.value)
    payload["would_sell"] = bool(intent and side == Side.SELL.value)
    payload["expected_price"] = expected
    if next_price is not None:
        payload["actual_price_after_signal"] = next_price
    elif "actual_price_after_signal" not in payload:
        payload["actual_price_after_signal"] = None
    existing_fill = payload.get("simulated_fill")
    if not isinstance(existing_fill, dict):
        payload["simulated_fill"] = {
            "sent": False,
            "style": result.get("style") or opportunity.get("style"),
            "shares": result.get("shares") or opportunity.get("intended_shares"),
            "fee_per_share": edge.get("fee_per_share"),
        }
    else:
        fill = dict(existing_fill)
        fill["sent"] = False
        payload["simulated_fill"] = fill
    complete, missing = shadow_completeness(payload)
    payload["signal_complete"] = complete
    payload["missing_fields"] = missing
    return payload


def _observed_mid(market: MarketRecord) -> float | None:
    if market.book is None or market.book.mid is None:
        return None
    return float(market.book.mid)


def _intent_label(row: dict[str, Any]) -> str:
    if row.get("would_buy"):
        return "would_buy"
    if row.get("would_sell"):
        return "would_sell"
    return "skip"


def run_shadow(
    config: HotflowConfig,
    markets: list[MarketRecord],
    *,
    next_prices: dict[str, float] | None = None,
    p_info: float | None = None,
    pipeline: PaperPipeline | None = None,
    obs: Observability | None = None,
) -> list[dict[str, Any]]:
    config.trading.mode = "shadow"
    config.trading.shadow = True
    watcher = obs or (pipeline.obs if pipeline is not None else Observability.from_config(config))
    pipe = pipeline or PaperPipeline(config, use_twap_fixtures=True, obs=watcher)
    rows: list[dict[str, Any]] = []
    prices = next_prices or {}
    evaluated = pipe.evaluate_markets(markets, p_info=p_info)
    for market, result in zip(markets, evaluated, strict=True):
        rows.append(
            attach_shadow_fields(
                result,
                next_price=prices.get(market.market_id),
                market_id=market.market_id,
            )
        )
    watcher.observe_shadow(rows)
    watcher.snapshot_pipeline(pipe)
    return rows


class ShadowSession:
    """Shared shadow pipeline across cycles. Never submits orders."""

    def __init__(
        self,
        config: HotflowConfig,
        *,
        obs: Observability | None = None,
        use_twap_fixtures: bool = True,
        cache_path: str | None = None,
        sports_cache_path: str | None = None,
        use_news_fixtures: bool = False,
        news_engine: Any | None = None,
    ) -> None:
        config.trading.mode = "shadow"
        config.trading.shadow = True
        self.config = config
        self.obs = obs or Observability.from_config(config, announce_restart=False)
        self.pipe = PaperPipeline(
            config,
            use_twap_fixtures=use_twap_fixtures,
            cache_path=cache_path,
            sports_cache_path=sports_cache_path,
            obs=self.obs,
            news_engine=news_engine,
            use_news_fixtures=use_news_fixtures,
        )
        self.cycles: list[list[dict[str, Any]]] = []
        self.cycle_marks: list[dict[str, float]] = []
        self.stale_probe: dict[str, Any] | None = None
        self.comparison: dict[str, Any] | None = None

    def run_cycle(
        self,
        markets: list[MarketRecord],
        *,
        next_prices: dict[str, float] | None = None,
        p_info: float | None = None,
    ) -> list[dict[str, Any]]:
        marks: dict[str, float] = {}
        rows: list[dict[str, Any]] = []
        prices = next_prices or {}
        evaluated = self.pipe.evaluate_markets(markets, p_info=p_info)
        for market, result in zip(markets, evaluated, strict=True):
            mid = _observed_mid(market)
            if mid is not None:
                marks[market.market_id] = mid
            rows.append(
                attach_shadow_fields(
                    result,
                    next_price=prices.get(market.market_id),
                    market_id=market.market_id,
                )
            )
        self.cycles.append(rows)
        self.cycle_marks.append(marks)
        self._backfill_actual_prices()
        self.obs.observe_shadow(rows)
        self.obs.snapshot_pipeline(self.pipe)
        return rows

    def _backfill_actual_prices(self) -> None:
        """Later-cycle observed mids only. Missing later marks stay null."""
        if len(self.cycles) < 2:
            return
        later = self.cycle_marks[-1]
        for row in self.cycles[-2]:
            if row.get("actual_price_after_signal") is not None:
                continue
            mid = later.get(str(row.get("market_id") or ""))
            if mid is None:
                continue
            row["actual_price_after_signal"] = mid
            complete, missing = shadow_completeness(row)
            row["signal_complete"] = complete
            row["missing_fields"] = missing

    def flattened(self) -> list[dict[str, Any]]:
        return [row for cycle in self.cycles for row in cycle]

    def report(self) -> dict[str, Any]:
        rows = self.flattened()
        complete = sum(1 for row in rows if row.get("signal_complete"))
        intents = Counter(_intent_label(row) for row in rows)
        reasons = Counter(str(row.get("reason") or "NO_TRADE") for row in rows)
        sent = any(
            isinstance(row.get("simulated_fill"), dict) and row["simulated_fill"].get("sent")
            for row in rows
        )
        stale_hits = sum(1 for row in rows if row.get("reason") in STALE_REASONS)
        if self.stale_probe and self.stale_probe.get("blocked"):
            stale_hits += 1
        payload: dict[str, Any] = {
            "mode": "shadow",
            "sent_orders": False,
            "live_edge_claimed": False,
            "cycle_count": len(self.cycles),
            "cycles": [{"decisions": len(cycle), "results": cycle} for cycle in self.cycles],
            "results": rows,
            "completeness": {
                "rows": len(rows),
                "complete": complete,
                "incomplete": len(rows) - complete,
                "required_fields": list(SHADOW_REQUIRED_FIELDS),
            },
            "intents": {
                "would_buy": intents.get("would_buy", 0),
                "would_sell": intents.get("would_sell", 0),
                "skip": intents.get("skip", 0),
            },
            "reasons": dict(reasons),
            "orders_submitted": 0,
            "broker_order_count": len(self.pipe.broker.orders),
            "kill_switch": {
                "tripped": self.pipe.kills.tripped,
                "reason": self.pipe.kills.reason.value if self.pipe.kills.reason else None,
            },
            "gates": {
                "signal_logging_complete": bool(rows) and complete == len(rows),
                "simulated_fills_unsent": not sent and not self.pipe.broker.orders,
                "data_loss_detected": stale_hits > 0,
                "no_orders_sent": not self.pipe.broker.orders,
                "performance_reproducible": True,
                "live_edge_claimed": False,
            },
        }
        if self.stale_probe is not None:
            payload["stale_probe"] = self.stale_probe
        if self.comparison is not None:
            payload["comparison"] = self.comparison
        return payload


def run_stale_probe(session: ShadowSession) -> dict[str, Any]:
    """Age a fixture book and confirm shadow emits STALE skip, not would_* intent."""
    from datetime import UTC, datetime, timedelta

    aged = demo_market(hot=True)
    aged.market_id = "shadow-stale-probe"
    if aged.book is not None:
        aged.book.fetched_at = datetime.now(UTC) - timedelta(seconds=90)
    session.pipe.clock.touch("clob_book", observed_at=datetime.now(UTC) - timedelta(seconds=90))
    row = attach_shadow_fields(
        session.pipe.evaluate_market(aged, p_info=0.70),
        market_id=aged.market_id,
    )
    session.obs.observe_shadow([row])
    blocked = row.get("reason") in STALE_REASONS or row.get("reason") == ReasonCode.KILL_SWITCH
    probe = {
        "reason": row.get("reason"),
        "would_buy": bool(row.get("would_buy")),
        "would_sell": bool(row.get("would_sell")),
        "blocked": blocked,
        "signal_complete": bool(row.get("signal_complete")),
        "simulated_fill_sent": False,
        "accepted": bool(row.get("accepted")),
    }
    session.stale_probe = probe
    return probe


def compare_shadow_vs_paper(
    config: HotflowConfig,
    markets: list[MarketRecord],
    *,
    p_info: float | None = None,
) -> dict[str, Any]:
    """Same fixtures, two pipelines. Does not claim live edge or invent PnL."""
    paper_cfg = config.model_copy(deep=True)
    paper_cfg.trading.mode = "paper"
    paper_cfg.trading.shadow = False
    shadow_cfg = config.model_copy(deep=True)
    shadow_cfg.trading.mode = "shadow"
    shadow_cfg.trading.shadow = True
    paper_pipe = PaperPipeline(paper_cfg, use_twap_fixtures=True)
    shadow_pipe = PaperPipeline(shadow_cfg, use_twap_fixtures=True)
    paper_rows = paper_pipe.evaluate_markets(markets, p_info=p_info)
    shadow_rows = shadow_pipe.evaluate_markets(markets, p_info=p_info)
    pairs: list[dict[str, Any]] = []
    for market, paper, shadow_raw in zip(markets, paper_rows, shadow_rows, strict=True):
        shadow = attach_shadow_fields(shadow_raw, market_id=market.market_id)
        paper_side = None
        paper_px = None
        order = paper.get("order") if isinstance(paper.get("order"), dict) else None
        if order is not None:
            paper_side = order.get("side")
            paper_px = order.get("avg_fill_price") or order.get("price")
        elif paper.get("accepted"):
            paper_side = paper.get("side")
        shadow_intent = bool(shadow.get("would_buy") or shadow.get("would_sell"))
        if paper.get("accepted") and order is not None:
            agree = (paper_side == Side.BUY.value and shadow.get("would_buy")) or (
                paper_side == Side.SELL.value and shadow.get("would_sell")
            )
            kind = "paper_fill_vs_shadow_intent"
        elif not paper.get("accepted") and not shadow_intent:
            agree = str(paper.get("reason")) == str(shadow.get("reason"))
            kind = "both_skip"
        else:
            agree = False
            kind = "disagree"
        delta = None
        if paper_px is not None and shadow.get("expected_price") is not None:
            delta = float(paper_px) - float(shadow["expected_price"])
        pairs.append(
            {
                "market_id": market.market_id,
                "kind": kind,
                "agree": bool(agree),
                "paper_accepted": bool(paper.get("accepted")),
                "paper_reason": paper.get("reason"),
                "paper_side": paper_side,
                "paper_fill_price": paper_px,
                "shadow_reason": shadow.get("reason"),
                "would_buy": shadow.get("would_buy"),
                "would_sell": shadow.get("would_sell"),
                "expected_price": shadow.get("expected_price"),
                "price_delta": delta,
                "shadow_sent": False,
            }
        )
    agreed = sum(1 for row in pairs if row["agree"])
    return {
        "live_edge_claimed": False,
        "pairs": pairs,
        "pair_count": len(pairs),
        "agree_count": agreed,
        "agreement_rate": (agreed / len(pairs)) if pairs else 0.0,
        "paper_orders": len(paper_pipe.broker.orders),
        "shadow_orders": len(shadow_pipe.broker.orders),
        "note": "Same fixtures only. Agreement is not a live-edge claim.",
    }
