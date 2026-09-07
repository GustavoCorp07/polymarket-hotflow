"""Time-ordered backtest events. Candle-only streams are refused when books matter."""

from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

from hotflow.reason_codes import ReasonCode
from hotflow.types import BookLevel, FeeSchedule, MarketRecord, OrderBook

BOOK_KINDS = frozenset({"book", "trade"})
STATE_KINDS = frozenset(
    {
        "book",
        "trade",
        "mid",
        "twap",
        "sports_state",
        "weather_forecast",
        "esports_state",
        "gap",
        "decision",
        "resolve",
        "candle",
    }
)


def parse_ts(raw: str | datetime | None) -> datetime | None:
    if raw is None:
        return None
    if isinstance(raw, datetime):
        return raw if raw.tzinfo else raw.replace(tzinfo=UTC)
    text = str(raw).replace("Z", "+00:00")
    return datetime.fromisoformat(text).astimezone(UTC)


@dataclass(frozen=True)
class MarketEvent:
    ts: datetime
    kind: str
    payload: dict[str, Any] = field(default_factory=dict)
    seq: int = 0


class EventSource(Protocol):
    def events(self) -> Iterable[MarketEvent]: ...


class ListEventSource:
    def __init__(self, rows: Iterable[MarketEvent]) -> None:
        self._rows = list(rows)

    def events(self) -> Iterable[MarketEvent]:
        return list(self._rows)


class FixtureEventSource:
    """Load a recorded official-shape stream. Never invents live prints."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.document = json.loads(self.path.read_text(encoding="utf-8"))
        if not isinstance(self.document, dict):
            raise ValueError("backtest fixture must be a JSON object")

    def events(self) -> Iterable[MarketEvent]:
        raw_events = self.document.get("events") or []
        out: list[MarketEvent] = []
        for index, row in enumerate(raw_events):
            if not isinstance(row, dict):
                continue
            ts = parse_ts(row.get("ts"))
            if ts is None:
                raise ValueError(f"event[{index}] missing ts")
            kind = str(row.get("kind") or "")
            if kind not in STATE_KINDS:
                raise ValueError(f"event[{index}] unknown kind {kind!r}")
            payload_raw = row.get("payload")
            payload: dict[str, Any] = dict(payload_raw) if isinstance(payload_raw, dict) else {}
            out.append(MarketEvent(ts=ts, kind=kind, payload=payload, seq=index))
        out.sort(key=lambda item: (item.ts, item.seq))
        return out


def sanitize_event_rows(rows: Iterable[Any]) -> dict[str, Any]:
    """Drop corrupt / duplicate / out-of-order rows. Never invent replacements."""
    accepted: list[MarketEvent] = []
    rejected: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    last_ts: datetime | None = None
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            rejected.append({"index": index, "reason": ReasonCode.EVENT_CORRUPT, "detail": "not_object"})
            continue
        ts = parse_ts(row.get("ts"))
        kind = str(row.get("kind") or "")
        if ts is None or kind not in STATE_KINDS:
            rejected.append({"index": index, "reason": ReasonCode.EVENT_CORRUPT, "detail": "ts_or_kind"})
            continue
        payload_raw = row.get("payload")
        payload: dict[str, Any] = dict(payload_raw) if isinstance(payload_raw, dict) else {}
        fingerprint = (ts.isoformat(), kind, json.dumps(payload, sort_keys=True, default=str))
        if fingerprint in seen:
            rejected.append({"index": index, "reason": ReasonCode.EVENT_DUPLICATE, "detail": kind})
            continue
        seen.add(fingerprint)
        if last_ts is not None and ts < last_ts:
            rejected.append({"index": index, "reason": ReasonCode.EVENT_OUT_OF_ORDER, "detail": kind})
            continue
        last_ts = ts
        accepted.append(MarketEvent(ts=ts, kind=kind, payload=payload, seq=index))
    return {
        "accepted": accepted,
        "rejected": rejected,
        "accepted_count": len(accepted),
        "rejected_count": len(rejected),
    }


def kinds_in(events: Iterable[MarketEvent]) -> set[str]:
    return {item.kind for item in events}


def candle_only(events: Iterable[MarketEvent]) -> bool:
    present = kinds_in(events)
    if not present:
        return False
    return present <= {"candle", "mid", "resolve", "decision"}


def book_levels(raw: Any) -> list[BookLevel]:
    rows: list[BookLevel] = []
    if not isinstance(raw, list):
        return rows
    for item in raw:
        if isinstance(item, dict):
            rows.append(BookLevel(price=float(item["price"]), size=float(item["size"])))
        elif isinstance(item, (list, tuple)) and len(item) >= 2:
            rows.append(BookLevel(price=float(item[0]), size=float(item[1])))
    return rows


def order_book_from_payload(payload: dict[str, Any], *, token_id: str, ts: datetime) -> OrderBook:
    return OrderBook(
        token_id=token_id,
        bids=book_levels(payload.get("bids")),
        asks=book_levels(payload.get("asks")),
        min_order_size=payload.get("min_order_size"),
        tick_size=payload.get("tick_size"),
        fetched_at=ts,
        source="backtest_fixture",
    )


def dated_fee_schedule(raw: dict[str, Any] | None) -> FeeSchedule | None:
    if not raw:
        return None
    fetched = parse_ts(raw.get("fetched_at") or raw.get("as_of"))
    kwargs: dict[str, Any] = {
        "enabled": raw.get("enabled"),
        "rate": raw.get("rate"),
        "exponent": raw.get("exponent"),
        "taker_only": raw.get("taker_only", True),
        "source": str(raw.get("source") or "fixture"),
    }
    if fetched is not None:
        kwargs["fetched_at"] = fetched
    return FeeSchedule(**kwargs)


def fee_schedule_marked(fees: FeeSchedule, extra: dict[str, Any] | None = None) -> bool:
    """Historical fee params must be dated/marked. Never treat live defaults as ancient."""
    blob = f"{fees.source} {json.dumps(extra or {})}".lower()
    return "as_of" in blob or "dated" in blob or "fixture" in blob


def market_from_fixture(document: dict[str, Any]) -> MarketRecord:
    from hotflow.pipeline import demo_market

    market_raw = document.get("market")
    row: dict[str, Any] = market_raw if isinstance(market_raw, dict) else {}
    kind = str(row.get("kind") or "demo_crypto")
    fees_raw = row.get("fees") if isinstance(row.get("fees"), dict) else document.get("fees")
    fees = dated_fee_schedule(fees_raw if isinstance(fees_raw, dict) else None)
    if kind == "demo_crypto":
        enabled = True if fees is None else bool(fees.enabled)
        rate = 0.04 if fees is None or fees.rate is None else float(fees.rate)
        market = demo_market(hot=bool(row.get("hot", True)), fees_enabled=enabled, rate=rate)
    else:
        market = MarketRecord.model_validate(row)
    if fees is not None:
        market.fees = fees
    if row.get("market_id"):
        market.market_id = str(row["market_id"])
    if row.get("question"):
        market.question = str(row["question"])
    if not market.fees.known:
        raise ValueError(ReasonCode.UNKNOWN_FEES)
    return market
