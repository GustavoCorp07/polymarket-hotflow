"""Fetch public Gamma esports-tag metadata for PAPER fixtures.

Uses official GET /events?tag_slug= and GET /markets/{id}.
Stores only public resolution fields. Never invents odds, maps, or live state.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

from hotflow.discovery.gamma import GammaClient, parse_json_list, tag_labels
from hotflow.official import (
    ESPORTS_TITLE_ALIASES,
    GAMMA_BASE,
    GAMMA_EVENTS,
    GAMMA_MARKETS,
    GAMMA_SPORTS,
    canonicalize_esports_title,
)

ESPORTS_EVENT_TAG_SLUGS = ("esports", "cs2", "lol", "dota-2", "valorant")
DEFAULT_FIXTURE_DIR = Path(__file__).resolve().parents[3] / "tests" / "fixtures" / "esports"

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
    "sportsMarketType",
    "line",
)


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
        extra = tag_labels(event.get("tags"))
        if extra:
            row["tags"] = list(dict.fromkeys([*(row.get("tags") or []), *extra]))
    inferred = _tags_from_text(
        str(raw.get("question") or ""),
        str(raw.get("slug") or ""),
        str(raw.get("description") or ""),
        *(row.get("tags") or []),
    )
    if inferred:
        row["tags"] = list(dict.fromkeys([*(row.get("tags") or []), *inferred]))
    row["collected_from"] = f"gamma GET {GAMMA_EVENTS}?tag_slug=esports"
    return row


def _tags_from_text(*parts: str) -> list[str]:
    blob = " ".join(parts).lower().replace("-", " ")
    found = ["esports"]
    for alias, title in ESPORTS_TITLE_ALIASES.items():
        if alias in blob and canonicalize_esports_title(title):
            found.append(title)
    return list(dict.fromkeys(found))


def preferred_fixture_ids() -> tuple[str, ...]:
    """Public Gamma market ids captured 2026-09-07."""
    return (
        "1923406",  # Dota 2 moneyline BO3
        "2268716",  # LoL moneyline BO3
        "2308640",  # Valorant moneyline BO5
        "536506",  # CS2 match (source in description)
        "693580",  # LCK season winner (incomplete match rules)
    )


async def fetch_preferred_markets(client: GammaClient) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for market_id in preferred_fixture_ids():
        try:
            raw = await client.get_market(market_id)
        except (httpx.HTTPError, ValueError):
            continue
        if not isinstance(raw, dict):
            continue
        row = redact_market(raw)
        row["collected_from"] = f"gamma GET {GAMMA_MARKETS}/{market_id}"
        rows.append(row)
    return rows


async def fetch_esports_event_markets(
    client: GammaClient,
    *,
    include_closed: bool = True,
    pages: int = 4,
    page_size: int = 15,
) -> list[dict[str, Any]]:
    seen: set[str] = set()
    rows: list[dict[str, Any]] = []
    closed_flags = [False, True] if include_closed else [False]
    for tag in ESPORTS_EVENT_TAG_SLUGS:
        for closed in closed_flags:
            for page in range(pages):
                events = await client.list_events(
                    closed=closed,
                    limit=page_size,
                    offset=page * page_size,
                    tag_slug=tag,
                )
                if not events:
                    break
                for event in events:
                    for market in event.get("markets") or []:
                        if not isinstance(market, dict):
                            continue
                        key = str(market.get("id") or market.get("slug") or "")
                        if not key or key in seen:
                            continue
                        seen.add(key)
                        row = redact_market(market, event=event)
                        row["collected_from"] = f"gamma GET {GAMMA_EVENTS}?tag_slug={tag}"
                        rows.append(row)
                if len(events) < page_size:
                    break
    return rows


def select_distinct_fixtures(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    wanted = {str(item) for item in preferred_fixture_ids()}
    picked = [row for row in rows if str(row.get("id")) in wanted]
    if picked:
        order = {mid: idx for idx, mid in enumerate(preferred_fixture_ids())}
        picked.sort(key=lambda row: order.get(str(row.get("id")), 99))
        return picked
    return rows[:5]


def write_esports_fixtures(rows: list[dict[str, Any]], directory: Path) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    payload = {
        "source": "gamma_public",
        "tag_slugs": list(ESPORTS_EVENT_TAG_SLUGS),
        "endpoint": f"GET {GAMMA_BASE}{GAMMA_EVENTS}?tag_slug=esports",
        "sports_metadata_endpoint": f"GET {GAMMA_BASE}{GAMMA_SPORTS}",
        "preferred_market_endpoint": f"GET {GAMMA_BASE}{GAMMA_MARKETS}/{{id}}",
        "collected_at": datetime.now(UTC).isoformat(),
        "note": (
            "Public Gamma esports-tag market text only. No secrets, token ids, or fees. "
            "No live odds, maps, or economies. Resolution rules are copied, not invented."
        ),
        "markets": rows,
    }
    target = directory / "gamma_esports_markets.json"
    target.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    for row in rows:
        slug = str(row.get("slug") or row.get("id") or "market")
        safe = "".join(ch if ch.isalnum() or ch in "-_" else "-" for ch in slug)[:80]
        (directory / f"{safe}.json").write_text(
            json.dumps(row, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
    return target


def load_esports_fixture_bundle(path: Path | None = None) -> list[dict[str, Any]]:
    if path is None:
        target = DEFAULT_FIXTURE_DIR / "gamma_esports_markets.json"
    elif path.is_dir() or path.suffix != ".json":
        target = path / "gamma_esports_markets.json"
    else:
        target = path
    if not target.exists():
        return []
    raw = json.loads(target.read_text(encoding="utf-8"))
    rows = raw.get("markets") if isinstance(raw, dict) else raw
    if not isinstance(rows, list):
        return []
    return [item for item in rows if isinstance(item, dict)]


async def collect_esports_fixtures(
    *,
    directory: Path | None = None,
    data_directory: Path | None = None,
    include_closed: bool = True,
    client: GammaClient | None = None,
) -> dict[str, Any]:
    dest = directory or DEFAULT_FIXTURE_DIR

    async def _pull(gamma: GammaClient) -> list[dict[str, Any]]:
        preferred = await fetch_preferred_markets(gamma)
        scanned = await fetch_esports_event_markets(gamma, include_closed=include_closed)
        seen: set[str] = set()
        merged: list[dict[str, Any]] = []
        for row in [*preferred, *scanned]:
            key = str(row.get("id") or "")
            if not key or key in seen:
                continue
            seen.add(key)
            merged.append(row)
        return merged

    if client is not None:
        rows = await _pull(client)
    else:
        async with GammaClient() as gamma:
            rows = await _pull(gamma)
    selected = select_distinct_fixtures(rows)
    path = write_esports_fixtures(selected, dest)
    data_path = None
    if data_directory is not None:
        data_path = str(write_esports_fixtures(selected, data_directory))
    return {
        "ok": True,
        "source": "gamma",
        "tag_slugs": list(ESPORTS_EVENT_TAG_SLUGS),
        "scanned": len(rows),
        "saved": len(selected),
        "path": str(path),
        "data_path": data_path,
        "ids": [row.get("id") for row in selected],
        "empty": len(selected) == 0,
        "note": (
            "No esports markets returned; fetcher kept."
            if not selected
            else "Redacted public Gamma fields only. No live esports feed."
        ),
    }
