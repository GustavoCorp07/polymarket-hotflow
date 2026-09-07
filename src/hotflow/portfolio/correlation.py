"""Parte 24 — explicit exposure identity and correlation rules.

Never invent a residual / price-implied correlation. A pair is correlated only
when an explicit rule fires: same underlying, same category+window, tag overlap
above a configured floor, or a named YAML group. Optional fixture-labeled
regimes may scale group caps; they do not create new links by themselves.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from hotflow.config import CorrelationGroupConfig, PortfolioConfig, PortfolioRulesConfig
from hotflow.discovery.resolution import (
    parse_esports_resolution,
    parse_sports_resolution,
    parse_twap_resolution,
    parse_weather_resolution,
)
from hotflow.discovery.scanner import infer_category
from hotflow.official import RTDS_CHAINLINK_SYMBOL_ALIASES, RTDS_CHAINLINK_SYMBOLS
from hotflow.types import MarketRecord

# Word-boundary windows only. Do not treat "75mm" precipitation as 75 minutes.
_WINDOW_TOKEN = re.compile(
    r"\b(\d+)\s*-?\s*(minutes?|mins?|m(?![a-z])|hours?|hrs?|h(?![a-z])|seconds?|secs?|s(?![a-z]))\b",
    re.I,
)


def _norm(value: str | None) -> str | None:
    if not value:
        return None
    text = value.strip().lower()
    return text or None


def normalize_window_label(raw: str, unit: str) -> str | None:
    try:
        count = int(raw)
    except ValueError:
        return None
    token = unit.lower()
    if token.startswith("m") and "h" not in token:
        return f"{count}m"
    if token.startswith("h"):
        return f"{count}h"
    if token.startswith("s"):
        return f"{count}s"
    return None


def parse_window_label(*parts: str | None) -> str | None:
    """Parse 5m / 15m / 4h / 30s-style labels from explicit text. None if absent."""
    blob = " ".join(part for part in parts if part)
    if not blob:
        return None
    match = _WINDOW_TOKEN.search(blob)
    if not match:
        return None
    return normalize_window_label(match.group(1), match.group(2))


def parse_underlying(*parts: str | None) -> str | None:
    """Official Chainlink symbol or documented alias only. Never invent a pair."""
    blob = " ".join(part for part in parts if part).lower()
    if not blob:
        return None
    slash = re.search(r"\b([a-z]{2,5})/([a-z]{3,4})\b", blob)
    if slash:
        symbol = f"{slash.group(1)}/{slash.group(2)}"
        if symbol in RTDS_CHAINLINK_SYMBOLS:
            return symbol
    for alias, symbol in RTDS_CHAINLINK_SYMBOL_ALIASES.items():
        if re.search(rf"\b{re.escape(alias)}\b", blob):
            return symbol
    return None


def _game_key(home: str | None, away: str | None, league: str | None, game_id: int | None) -> str | None:
    if game_id is not None:
        return f"game:{game_id}"
    left = _norm(home)
    right = _norm(away)
    if left and right:
        pair = "|".join(sorted((left, right)))
        league_bit = _norm(league) or "unknown"
        return f"{league_bit}:{pair}"
    return None


@dataclass(frozen=True)
class ExposureIdentity:
    market_id: str
    category: str
    underlying: str | None
    window: str | None
    tags: frozenset[str]
    city: str | None
    station: str | None
    game: str | None
    match: str | None
    regime_label: str | None
    regime_labels: tuple[str, ...] = ()
    source_notes: tuple[str, ...] = ()

    def specific_tags(self, generic: list[str]) -> frozenset[str]:
        drop = {item.lower() for item in generic}
        return frozenset(tag for tag in self.tags if tag not in drop and tag != self.window)


@dataclass
class CorrelationHit:
    rule: str
    bucket: str
    assumption: str


@dataclass
class OpenExposure:
    market_id: str
    category: str
    notional: float
    identity: ExposureIdentity


def extract_identity(
    market: MarketRecord,
    *,
    category: str | None = None,
    extra_labels: list[str] | tuple[str, ...] | None = None,
) -> ExposureIdentity:
    cat = category or infer_category(market.tags, market.category)
    tags = frozenset(tag.strip().lower() for tag in market.tags if tag and tag.strip())
    question = market.question or ""
    slug = market.slug or ""
    notes: list[str] = []

    twap = parse_twap_resolution(market)
    underlying = twap.symbol if twap.symbol else parse_underlying(question, slug, " ".join(market.tags))
    if twap.symbol:
        notes.append(f"underlying from official TWAP symbol {twap.symbol}")
    elif underlying:
        notes.append(f"underlying from documented alias → {underlying}")

    window: str | None = None
    if twap.window_seconds is not None:
        window = f"{twap.window_seconds}s"
        notes.append(f"window from official TWAP {window}")
    else:
        window = parse_window_label(question, slug, market.resolution.time_window, " ".join(market.tags))
        if window:
            notes.append(f"window from explicit text {window}")

    city = None
    station = None
    game = None
    match = None
    if cat == "weather":
        weather = parse_weather_resolution(market)
        city = _norm(weather.city)
        station = _norm(weather.station)
        if city:
            notes.append(f"weather city={city}")
        if station:
            notes.append(f"weather station={station}")
    elif cat == "sports":
        sports = parse_sports_resolution(market)
        raw_id = (market.raw_gamma or {}).get("gameId") or (market.raw_gamma or {}).get("game_id")
        game_id = int(raw_id) if raw_id not in (None, "") else None
        game = _game_key(sports.home_team, sports.away_team, sports.league, game_id)
        if game:
            notes.append(f"sports game={game}")
    elif cat == "esports":
        esports = parse_esports_resolution(market)
        match = _game_key(esports.home_team, esports.away_team, esports.game, None)
        if match:
            notes.append(f"esports match={match}")

    labels: list[str] = []
    raw = market.raw_gamma or {}
    labeled = raw.get("hotflow_regime") or raw.get("regime")
    if isinstance(labeled, str) and labeled.strip():
        stamp = labeled.strip().lower()
        labels.append(stamp)
        notes.append(f"fixture regime label={stamp}")
    for item in extra_labels or ():
        text = str(item).strip().lower()
        if text and text not in labels and text != "n/a":
            labels.append(text)
    if extra_labels:
        notes.append(f"detected regime labels={list(extra_labels)}")

    return ExposureIdentity(
        market_id=market.market_id,
        category=cat,
        underlying=underlying,
        window=window,
        tags=tags,
        city=city,
        station=station,
        game=game,
        match=match,
        regime_label=labels[0] if labels else None,
        regime_labels=tuple(labels),
        source_notes=tuple(notes),
    )


def _field_for_key(identity: ExposureIdentity, key: str | None) -> str | None:
    if key == "city":
        return identity.city or identity.station
    if key == "game":
        return identity.game
    if key == "match":
        return identity.match
    if key == "underlying":
        return identity.underlying
    return None


def group_buckets(identity: ExposureIdentity, groups: list[CorrelationGroupConfig]) -> list[tuple[str, str]]:
    """Return (group_id, bucket) pairs this identity joins. Missing keys → no join."""
    joined: list[tuple[str, str]] = []
    for group in groups:
        if group.category and identity.category != group.category:
            continue
        if group.windows and (identity.window is None or identity.window not in group.windows):
            continue
        if group.underlyings:
            if identity.underlying is None or identity.underlying not in group.underlyings:
                continue
        if group.tags_any:
            wanted = {item.lower() for item in group.tags_any}
            if not (identity.tags & wanted):
                continue
        instance = _field_for_key(identity, group.key)
        if group.key and instance is None:
            continue
        bucket = f"{group.id}:{instance}" if instance else group.id
        joined.append((group.id, bucket))
    return joined


def tag_overlap(
    left: ExposureIdentity,
    right: ExposureIdentity,
    *,
    generic: list[str],
    minimum: int,
) -> frozenset[str]:
    shared = left.specific_tags(generic) & right.specific_tags(generic)
    if len(shared) >= minimum:
        return shared
    return frozenset()


def correlation_hits(
    left: ExposureIdentity,
    right: ExposureIdentity,
    config: PortfolioConfig,
) -> list[CorrelationHit]:
    if left.market_id == right.market_id:
        return []
    rules: PortfolioRulesConfig = config.rules
    hits: list[CorrelationHit] = []
    if rules.same_underlying and left.underlying and left.underlying == right.underlying:
        hits.append(
            CorrelationHit(
                rule="same_underlying",
                bucket=f"underlying:{left.underlying}",
                assumption=f"Same parsed underlying {left.underlying}.",
            )
        )
    if (
        rules.same_category_window
        and left.category
        and left.category == right.category
        and left.window
        and left.window == right.window
    ):
        hits.append(
            CorrelationHit(
                rule="same_category_window",
                bucket=f"category_window:{left.category}:{left.window}",
                assumption=f"Same category {left.category} and parsed window {left.window}.",
            )
        )
    if rules.tag_overlap:
        shared = tag_overlap(left, right, generic=config.generic_tags, minimum=config.tag_overlap_min)
        if shared:
            hits.append(
                CorrelationHit(
                    rule="tag_overlap",
                    bucket="tag_overlap:" + "|".join(sorted(shared)),
                    assumption=f"Tag overlap {sorted(shared)} (min {config.tag_overlap_min}, generics ignored).",
                )
            )
    if rules.yaml_groups:
        left_groups = dict(group_buckets(left, config.groups))
        right_map = {gid: bucket for gid, bucket in group_buckets(right, config.groups)}
        for group in config.groups:
            if group.id not in left_groups or group.id not in right_map:
                continue
            if left_groups[group.id] != right_map[group.id]:
                continue
            hits.append(
                CorrelationHit(
                    rule="yaml_group",
                    bucket=left_groups[group.id],
                    assumption=group.assumption.strip(),
                )
            )
    return hits


def are_correlated(left: ExposureIdentity, right: ExposureIdentity, config: PortfolioConfig) -> bool:
    return bool(correlation_hits(left, right, config))


class ExposureBook:
    """In-memory open exposures with identity. Not a venue position source."""

    def __init__(self) -> None:
        self.by_market: dict[str, OpenExposure] = {}

    def upsert(self, identity: ExposureIdentity, notional: float, *, category: str | None = None) -> None:
        if notional <= 1e-12:
            self.by_market.pop(identity.market_id, None)
            return
        self.by_market[identity.market_id] = OpenExposure(
            market_id=identity.market_id,
            category=category or identity.category,
            notional=notional,
            identity=identity,
        )

    def add_notional(self, identity: ExposureIdentity, delta: float, *, category: str | None = None) -> None:
        current = self.by_market.get(identity.market_id)
        base = current.notional if current is not None else 0.0
        self.upsert(identity, base + delta, category=category)

    def snapshot(self) -> list[OpenExposure]:
        return list(self.by_market.values())

    def clear(self) -> None:
        self.by_market.clear()
