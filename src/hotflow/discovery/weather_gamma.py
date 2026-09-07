"""Fetch public Gamma weather-event metadata for PAPER fixtures.

Uses official GET /events?tag_slug=weather (docs.polymarket.com list-events)
and public GET /markets/{id} for stable preferred ids. Stores only public
resolution fields. Never invents market text or forecasts.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

from hotflow.discovery.gamma import GammaClient, parse_json_list, tag_labels
from hotflow.official import GAMMA_BASE, GAMMA_EVENTS, GAMMA_MARKETS

WEATHER_EVENT_TAG_SLUG = "weather"
DEFAULT_FIXTURE_DIR = Path(__file__).resolve().parents[3] / "tests" / "fixtures" / "weather"

# Public fields only — no token ids, fees, or private metadata.
_MARKET_KEEP = (
    "id",
    "conditionId",
    "slug",
    "question",
    "description",
    "resolutionSource",
    "outcomes",
    "endDate",
    "closed",
    "active",
    "groupItemTitle",
    "line",
)

_WEATHER_HINTS = (
    "temperature",
    "precip",
    "rainfall",
    "snowfall",
    "fahrenheit",
    "celsius",
    "°c",
    "°f",
    "hottest",
    "weather",
)


def looks_like_weather_text(*parts: str | None) -> bool:
    blob = " ".join(part or "" for part in parts).lower()
    return any(hint in blob for hint in _WEATHER_HINTS)


def redact_market(raw: dict[str, Any], *, event: dict[str, Any] | None = None) -> dict[str, Any]:
    row: dict[str, Any] = {}
    for key in _MARKET_KEEP:
        if key == "outcomes":
            continue
        value = raw.get(key)
        if value not in (None, ""):
            row[key] = value
    outcomes = parse_json_list(raw.get("outcomes"))
    if outcomes:
        row["outcomes"] = outcomes
    tags = tag_labels(raw.get("tags"))
    if tags:
        row["tags"] = tags
    if event:
        row["event_id"] = event.get("id")
        row["event_slug"] = event.get("slug")
        row["event_title"] = event.get("title")
    row["collected_from"] = f"gamma GET {GAMMA_EVENTS}?tag_slug={WEATHER_EVENT_TAG_SLUG}"
    return row


async def fetch_preferred_markets(client: GammaClient) -> list[dict[str, Any]]:
    """Pull preferred public market ids via GET /markets/{id}. Skip missing ids."""
    rows: list[dict[str, Any]] = []
    for market_id in preferred_fixture_ids():
        try:
            raw = await client.get_market(market_id)
        except (httpx.HTTPError, ValueError):
            continue
        if not isinstance(raw, dict):
            continue
        if not looks_like_weather_text(raw.get("question"), raw.get("description"), raw.get("slug")):
            continue
        row = redact_market(raw)
        row["collected_from"] = f"gamma GET {GAMMA_MARKETS}/{market_id}"
        rows.append(row)
    return rows


async def fetch_weather_event_markets(
    client: GammaClient,
    *,
    include_closed: bool = True,
    pages: int = 12,
    page_size: int = 15,
) -> list[dict[str, Any]]:
    """Page official weather-tag events. Client-side keyword filter only."""
    seen: set[str] = set()
    rows: list[dict[str, Any]] = []
    closed_flags = [False, True] if include_closed else [False]
    for closed in closed_flags:
        for page in range(pages):
            events = await client.list_events(
                closed=closed,
                limit=page_size,
                offset=page * page_size,
                tag_slug=WEATHER_EVENT_TAG_SLUG,
            )
            if not events:
                break
            for event in events:
                if not looks_like_weather_text(event.get("title"), event.get("slug")):
                    continue
                for market in event.get("markets") or []:
                    if not isinstance(market, dict):
                        continue
                    if not looks_like_weather_text(
                        market.get("question"),
                        market.get("description"),
                        market.get("slug"),
                    ):
                        continue
                    key = str(market.get("id") or market.get("slug") or "")
                    if not key or key in seen:
                        continue
                    seen.add(key)
                    rows.append(redact_market(market, event=event))
            if len(events) < page_size:
                break
    return rows


def preferred_fixture_ids() -> tuple[str, ...]:
    """Stable public Gamma market ids captured 2026-09-07 (weather tag)."""
    return (
        "2290078",  # Jinan highest temp 15°C or below
        "4238333",  # London lowest temp 13°C or below
        "4027989",  # Seoul precip <75mm
        "678686",  # 2026 hottest year (incomplete rules)
    )


def select_distinct_fixtures(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    wanted = {str(item) for item in preferred_fixture_ids()}
    picked = [row for row in rows if str(row.get("id")) in wanted]
    if picked:
        order = {mid: idx for idx, mid in enumerate(preferred_fixture_ids())}
        picked.sort(key=lambda row: order.get(str(row.get("id")), 99))
        return picked
    # If those ids are gone, keep first distinct city/metric texts — still real Gamma.
    distinct: list[dict[str, Any]] = []
    seen_slug: set[str] = set()
    for row in rows:
        slug = str(row.get("event_slug") or row.get("slug") or "")
        stem = slug.split("-on-")[0] if "-on-" in slug else slug
        if stem in seen_slug:
            continue
        seen_slug.add(stem)
        distinct.append(row)
        if len(distinct) >= 4:
            break
    return distinct


def _merge_rows(*groups: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged: list[dict[str, Any]] = []
    seen: set[str] = set()
    for group in groups:
        for row in group:
            key = str(row.get("id") or row.get("slug") or "")
            if not key or key in seen:
                continue
            seen.add(key)
            merged.append(row)
    return merged


def fixture_bundle_payload(rows: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "source": "gamma_public",
        "tag_slug": WEATHER_EVENT_TAG_SLUG,
        "endpoint": f"GET {GAMMA_BASE}{GAMMA_EVENTS}?tag_slug={WEATHER_EVENT_TAG_SLUG}",
        "preferred_market_endpoint": f"GET {GAMMA_BASE}{GAMMA_MARKETS}/{{id}}",
        "collected_at": datetime.now(UTC).isoformat(),
        "query": {
            "endpoint": f"{GAMMA_BASE}{GAMMA_EVENTS}",
            "params": {"tag_slug": WEATHER_EVENT_TAG_SLUG, "closed": "false|true"},
        },
        "note": (
            "Public Gamma weather-tag market text only. No secrets, token ids, or fees. "
            "Forecasts are not included. Resolution rules are copied, not invented. "
            "Forecasts used later in paper FV are labeled source=fixture — not live NWS/KMA/NOAA."
        ),
        "markets": rows,
    }


def write_weather_fixtures(rows: list[dict[str, Any]], directory: Path) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    payload = fixture_bundle_payload(rows)
    target = directory / "gamma_weather_markets.json"
    target.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    for row in rows:
        slug = str(row.get("slug") or row.get("id") or "market")
        safe = "".join(ch if ch.isalnum() or ch in "-_" else "-" for ch in slug)[:80]
        (directory / f"{safe}.json").write_text(
            json.dumps(row, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
    return target


def load_weather_fixture_bundle(path: Path | None = None) -> list[dict[str, Any]]:
    if path is None:
        target = DEFAULT_FIXTURE_DIR / "gamma_weather_markets.json"
    elif path.is_dir() or path.suffix != ".json":
        target = path / "gamma_weather_markets.json"
    else:
        target = path
    if not target.exists():
        return []
    raw = json.loads(target.read_text(encoding="utf-8"))
    rows = raw.get("markets") if isinstance(raw, dict) else raw
    if not isinstance(rows, list):
        return []
    return [item for item in rows if isinstance(item, dict)]


async def collect_weather_fixtures(
    *,
    directory: Path | None = None,
    data_directory: Path | None = None,
    include_closed: bool = True,
    client: GammaClient | None = None,
) -> dict[str, Any]:
    dest = directory or DEFAULT_FIXTURE_DIR

    async def _pull(gamma: GammaClient) -> list[dict[str, Any]]:
        preferred = await fetch_preferred_markets(gamma)
        scanned = await fetch_weather_event_markets(gamma, include_closed=include_closed)
        return _merge_rows(preferred, scanned)

    if client is not None:
        rows = await _pull(client)
    else:
        async with GammaClient() as gamma:
            rows = await _pull(gamma)
    selected = select_distinct_fixtures(rows)
    path = write_weather_fixtures(selected, dest)
    data_path = None
    if data_directory is not None:
        data_path = str(write_weather_fixtures(selected, data_directory))
    return {
        "ok": True,
        "source": "gamma",
        "tag_slug": WEATHER_EVENT_TAG_SLUG,
        "scanned": len(rows),
        "saved": len(selected),
        "path": str(path),
        "data_path": data_path,
        "ids": [row.get("id") for row in selected],
        "empty": len(selected) == 0,
        "note": (
            "No weather markets returned; fetcher kept. Parser tests must use previously "
            "captured public Gamma text only — do not invent market wording."
            if not selected
            else "Redacted public Gamma fields only. Forecasts are not part of this collect."
        ),
    }
