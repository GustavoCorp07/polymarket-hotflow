"""Record official-shape CLOB book + RTDS prints into a backtest fixture.

Live collect is optional and default-off. pytest uses parsers + synthetic
streams only — never opens CLOB or RTDS sockets.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from hotflow.discovery.clob import _levels
from hotflow.marketdata.rtds_twap import parse_official_rtds_twap_event
from hotflow.official import CLOB_BASE, CLOB_BOOK, CLOB_FEE_RATE, RTDS_CHAINLINK_SYMBOLS, RTDS_TWAP_WINDOWS
from hotflow.types import OfficialTwapObservation, OrderBook

SCHEMA = "hotflow.backtest.v1"
DEFAULT_FIXTURE_DIR = Path(__file__).resolve().parents[3] / "tests" / "fixtures" / "backtest"
LONGER_SYNTHETIC_NAME = "crypto_longer_synthetic.json"
LIVE_SAMPLE_NAME = "clob_book_live_sample.json"
MAX_SECONDS = 180.0
DEFAULT_SECONDS = 20.0
DEFAULT_POLL_S = 2.0
MAX_EVENTS = 400


def parse_clob_book_payload(data: dict[str, Any], *, token_id: str = "redacted-yes") -> OrderBook | None:
    """Parse official GET /book JSON. Ignore unknown shapes."""
    if not isinstance(data, dict):
        return None
    bids = _levels(data.get("bids"), reverse=True)
    asks = _levels(data.get("asks"), reverse=False)
    if not bids or not asks:
        return None
    ts = data.get("timestamp")
    try:
        timestamp_ms = int(float(ts)) if ts is not None else None
    except (TypeError, ValueError):
        timestamp_ms = None
    return OrderBook(
        token_id=str(data.get("asset_id") or token_id),
        condition_id=data.get("market"),
        bids=bids,
        asks=asks,
        min_order_size=_num(data.get("min_order_size")),
        tick_size=_num(data.get("tick_size")),
        timestamp_ms=timestamp_ms,
        source="clob_book",
    )


def _num(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def book_event_from_clob_json(
    data: dict[str, Any],
    *,
    ts: datetime,
    token_id: str = "redacted-yes",
) -> dict[str, Any] | None:
    book = parse_clob_book_payload(data, token_id=token_id)
    if book is None:
        return None
    return {
        "ts": ts.isoformat(),
        "kind": "book",
        "payload": {
            "bids": [[lvl.price, lvl.size] for lvl in book.bids],
            "asks": [[lvl.price, lvl.size] for lvl in book.asks],
            "source": "clob_book",
        },
    }


def mid_event_from_book(book_event: dict[str, Any]) -> dict[str, Any] | None:
    payload_raw = book_event.get("payload")
    payload: dict[str, Any] = payload_raw if isinstance(payload_raw, dict) else {}
    bids = payload.get("bids") or []
    asks = payload.get("asks") or []
    if not bids or not asks:
        return None
    bid = float(bids[0][0])
    ask = float(asks[0][0])
    return {
        "ts": book_event["ts"],
        "kind": "mid",
        "payload": {"mid": (bid + ask) / 2.0, "source": "clob_book_mid"},
    }


def twap_event_from_rtds_message(
    message: dict[str, Any],
    *,
    ts: datetime,
    source: str = "live_rtds",
) -> dict[str, Any] | None:
    parsed = parse_official_rtds_twap_event(message, source=source, observed_at=ts)
    if parsed is None:
        return None
    if parsed.symbol not in RTDS_CHAINLINK_SYMBOLS:
        return None
    if parsed.window_seconds not in RTDS_TWAP_WINDOWS:
        return None
    return twap_event_from_observation(parsed)


def twap_event_from_observation(obs: OfficialTwapObservation) -> dict[str, Any]:
    return {
        "ts": obs.observed_at.isoformat(),
        "kind": "twap",
        "payload": {
            "symbol": obs.symbol,
            "window_seconds": obs.window_seconds,
            "value": obs.value,
            "topic": obs.topic,
            "source": obs.source,
        },
    }


def dated_fee_block(*, rate: float | None, as_of: datetime, source: str) -> dict[str, Any]:
    return {
        "enabled": rate is not None,
        "rate": rate,
        "exponent": 1.0,
        "taker_only": True,
        "source": source,
        "as_of": as_of.isoformat(),
        "fetched_at": as_of.isoformat(),
        "note": "Official-shape CLOB fee-rate fields. Dated. Not a live hardcoded default.",
    }


def wrap_stream(
    events: list[dict[str, Any]],
    *,
    origin: str,
    as_of: datetime,
    note: str,
    fees: dict[str, Any],
    market_id: str,
    split: dict[str, str] | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    capped = events[:MAX_EVENTS]
    document = {
        "schema": SCHEMA,
        "mode": "backtest",
        "origin": origin,
        "as_of": as_of.isoformat(),
        "note": note,
        "endpoint_book": f"GET {CLOB_BASE}{CLOB_BOOK}",
        "endpoint_fee_rate": f"GET {CLOB_BASE}{CLOB_FEE_RATE}",
        "rtds_windows": [30, 60],
        "split": split
        or {
            "train_end": (as_of + timedelta(minutes=10)).isoformat(),
            "validation_end": (as_of + timedelta(minutes=20)).isoformat(),
            "oos_start": (as_of + timedelta(minutes=20)).isoformat(),
        },
        "fees": fees,
        "market": {
            "kind": "demo_crypto",
            "hot": True,
            "market_id": market_id,
            "fees": fees,
        },
        "events": capped,
        "event_count": len(capped),
    }
    if extra:
        document.update(extra)
    return document


def build_synthetic_longer_stream(*, as_of: datetime | None = None) -> dict[str, Any]:
    """Multi-minute official-shape stream. SYNTHETIC — not a live collect."""
    start = as_of or datetime(2026, 4, 1, tzinfo=UTC)
    fees = dated_fee_block(
        rate=0.04,
        as_of=start,
        source="synthetic_official_shape_dated_as_of_2026-04-01",
    )
    events: list[dict[str, Any]] = []
    for step in range(120):
        ts = start + timedelta(seconds=15 * step)
        delta = ((step * 17) % 9 - 4) * 0.002
        mid = max(0.32, min(0.48, 0.41 + delta))
        half = 0.01
        book = {
            "ts": ts.isoformat(),
            "kind": "book",
            "payload": {
                "bids": [[round(mid - half, 3), 90.0], [round(mid - half - 0.02, 3), 100.0]],
                "asks": [[round(mid + half, 3), 80.0], [round(mid + half + 0.02, 3), 120.0]],
                "source": "synthetic_official_shape",
            },
        }
        events.append(book)
        if step % 2 == 0:
            mid_ev = mid_event_from_book(book)
            if mid_ev:
                events.append(mid_ev)
        if step % 4 == 0:
            events.append(
                {
                    "ts": ts.isoformat(),
                    "kind": "twap",
                    "payload": {
                        "symbol": "btc/usd",
                        "window_seconds": 60,
                        "value": 65000.0 + (step % 5) * 8.0,
                        "source": "synthetic_official_shape",
                    },
                }
            )
    for minutes, p_info in ((2, 0.70), (14, 0.70), (24, 0.70)):
        events.append(
            {
                "ts": (start + timedelta(minutes=minutes)).isoformat(),
                "kind": "decision",
                "payload": {"p_info": p_info},
            }
        )
    events.append(
        {
            "ts": (start + timedelta(minutes=29, seconds=50)).isoformat(),
            "kind": "resolve",
            "payload": {"outcome": "yes", "price": 1.0},
        }
    )
    events.sort(key=lambda row: str(row.get("ts")))
    return wrap_stream(
        events,
        origin="synthetic_official_shape",
        as_of=start,
        note=(
            "SYNTHETIC official-shape CLOB book / mid / RTDS-shaped TWAP stream. "
            "Not a live collect. Fees dated. No secrets. For train/val/OOS pytest."
        ),
        fees=fees,
        market_id="bt-crypto-longer-synthetic",
        extra={"synthetic": True, "live_collect": False},
    )


def redact_live_document(document: dict[str, Any]) -> dict[str, Any]:
    """Drop token ids and other identifiers that should not sit in git."""
    blob = json.dumps(document)
    for key in ("clobTokenIds", "token_id", "asset_id"):
        if key in blob:
            pass
    dumped = json.loads(json.dumps(document))
    dumped.pop("token_id", None)
    market = dumped.get("market")
    if isinstance(market, dict):
        market.pop("token_id", None)
        market["market_id"] = str(market.get("market_id") or "redacted-live")
    extra = dumped.get("live")
    if isinstance(extra, dict):
        extra["token_id"] = "redacted"
        extra["condition_id"] = "redacted"
    text = json.dumps(dumped)
    assert "clobTokenIds" not in text
    return dumped


async def record_live_stream(
    *,
    seconds: float = DEFAULT_SECONDS,
    poll_interval_s: float = DEFAULT_POLL_S,
    token_id: str | None = None,
    include_rtds: bool = False,
    symbol: str = "btc/usd",
    book_client: Any | None = None,
    rtds_transport: Any | None = None,
) -> dict[str, Any]:
    """Optional public collect. pytest injects clients — does not open sockets."""
    from hotflow.discovery.clob import ClobPublicClient

    duration = min(max(1.0, seconds), MAX_SECONDS)
    now = datetime.now(UTC)
    events: list[dict[str, Any]] = []
    fee_rate: float | None = None
    fee_bp: int | None = None
    owns = book_client is None
    client = book_client or ClobPublicClient()
    resolved_token = token_id
    if resolved_token is None and owns:
        resolved_token = await _public_token_id()
    if not resolved_token:
        raise ValueError("live collect needs a public CLOB token_id or injected client")
    try:
        if owns:
            await client.__aenter__()
        polls = max(1, int(duration / poll_interval_s))
        for index in range(min(polls, MAX_EVENTS)):
            book = await client.get_book(resolved_token)
            ts = now + timedelta(seconds=index * poll_interval_s)
            payload = {
                "bids": [[lvl.price, lvl.size] for lvl in book.bids],
                "asks": [[lvl.price, lvl.size] for lvl in book.asks],
            }
            event = book_event_from_clob_json(
                {"bids": payload["bids"], "asks": payload["asks"]},
                ts=ts,
            )
            if event:
                events.append(event)
                mid_ev = mid_event_from_book(event)
                if mid_ev:
                    events.append(mid_ev)
            if index == 0:
                try:
                    fee_bp = await client.get_fee_rate(resolved_token)
                except Exception:
                    fee_bp = None
                if book.condition_id and hasattr(client, "get_clob_market"):
                    try:
                        bundle = await client.get_clob_market(book.condition_id)
                        schedule = client.fee_from_clob_market(bundle)
                        fee_rate = schedule.rate
                    except Exception:
                        fee_rate = None
            if index + 1 < polls:
                import asyncio

                await asyncio.sleep(0 if book_client is not None else poll_interval_s)
        if include_rtds:
            events.extend(
                await _collect_rtds_events(
                    seconds=min(duration, 12.0),
                    symbol=symbol,
                    transport=rtds_transport,
                    start=now,
                )
            )
    finally:
        if owns:
            await client.__aexit__(None, None, None)
    fees = dated_fee_block(
        rate=fee_rate,
        as_of=now,
        source=f"clob_fee_rate_dated_as_of_{now.date().isoformat()}",
    )
    if fee_bp is not None:
        fees["clob_base_fee_bp"] = fee_bp
        fees["enabled"] = True if fee_rate is not None else fees.get("enabled")
        fees["note"] = (
            "GET /fee-rate base_fee is stored as clob_base_fee_bp. "
            "Curve rate is copied from official clob-markets fd.r when present — "
            "not invented from basis points."
        )
    document = wrap_stream(
        events,
        origin="live_public_clob",
        as_of=now,
        note=(
            "Redacted public CLOB GET /book collect (optional RTDS 30s/60s). "
            "PAPER metadata. No credentials. Token ids stripped."
        ),
        fees=fees,
        market_id="redacted-live",
        extra={
            "synthetic": False,
            "live_collect": True,
            "live": {"token_id": "redacted", "seconds": duration},
        },
    )
    return redact_live_document(document)


async def _public_token_id() -> str | None:
    import httpx

    from hotflow.official import GAMMA_BASE, GAMMA_MARKETS

    async with httpx.AsyncClient(timeout=15.0) as client:
        response = await client.get(
            f"{GAMMA_BASE}{GAMMA_MARKETS}",
            params={"closed": "false", "limit": 5, "enable_order_book": "true"},
        )
        response.raise_for_status()
        rows = response.json()
    if not isinstance(rows, list):
        return None
    for row in rows:
        if not isinstance(row, dict):
            continue
        raw = row.get("clobTokenIds")
        if isinstance(raw, str):
            try:
                parsed = json.loads(raw)
            except json.JSONDecodeError:
                parsed = []
        else:
            parsed = raw
        if isinstance(parsed, list) and parsed:
            return str(parsed[0])
    return None


async def _collect_rtds_events(
    *,
    seconds: float,
    symbol: str,
    transport: Any | None,
    start: datetime,
) -> list[dict[str, Any]]:
    from hotflow.config import RtdsFeedConfig
    from hotflow.marketdata.rtds_subscriber import (
        LivePublicRtdsTransport,
        PublicRtdsSubscriber,
    )
    from hotflow.marketdata.twap_cache import TwapPrintCache

    if symbol.lower() not in RTDS_CHAINLINK_SYMBOLS:
        raise ValueError(f"symbol {symbol!r} is not documented")
    events: list[dict[str, Any]] = []

    def _on(obs: OfficialTwapObservation) -> None:
        events.append(twap_event_from_observation(obs))

    cache = TwapPrintCache(max_age_ms=30_000)
    cfg = RtdsFeedConfig(
        max_data_age_ms=10_000,
        collect_seconds=seconds,
        subscribe_symbols=[symbol.lower()],
        subscribe_windows=[30, 60],
    )
    used = transport if transport is not None else LivePublicRtdsTransport()
    sub = PublicRtdsSubscriber(cache, config=cfg, transport=used, on_observation=_on)
    await sub.run(duration_s=seconds)
    if not events:
        events.append(
            {
                "ts": start.isoformat(),
                "kind": "gap",
                "payload": {"reason": "rtds_no_prints", "source": "live_rtds"},
            }
        )
    return events


def write_stream(path: Path, document: dict[str, Any]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document, indent=2), encoding="utf-8")
    return path
