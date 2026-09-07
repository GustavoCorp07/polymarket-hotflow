"""Parte 42 — structured resolution object. Unknown rules => DO_NOT_TRADE."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Any

from hotflow.official import (
    RTDS_CHAINLINK_SYMBOL_ALIASES,
    RTDS_CHAINLINK_SYMBOLS,
    RTDS_TWAP_WINDOWS,
    rtds_twap_topic,
)
from hotflow.reason_codes import ReasonCode
from hotflow.types import MarketRecord, ResolutionMeta, TwapResolutionSpec

_WINDOW_30 = (
    re.compile(r"\b30[\s_-]*seconds?\b", re.I),
    re.compile(r"\b30s\b", re.I),
    re.compile(r"twap_thirty", re.I),
    re.compile(r"window(?:_s|Seconds|seconds)?\s*[:=]\s*30\b"),
)
_WINDOW_60 = (
    re.compile(r"\b60[\s_-]*seconds?\b", re.I),
    re.compile(r"\b60s\b", re.I),
    re.compile(r"twap_sixty", re.I),
    re.compile(r"window(?:_s|Seconds|windowSeconds)?\s*[:=]\s*60\b"),
)
_SLASH_SYMBOL = re.compile(r"\b([a-z0-9]{2,10})/(usd)\b", re.I)
_OPEN_REF = re.compile(
    r"(?:opening\s+reference|opening\s+price|open\s+price|starting\s+price|reference\s+price)"
    r"\s*(?:of|is|:)?\s*\$?([0-9][0-9,]*(?:\.[0-9]+)?)",
    re.I,
)
_STRIKE = re.compile(
    r"(?:strike|threshold)\s*(?:of|is|:)?\s*\$?([0-9][0-9,]*(?:\.[0-9]+)?)",
    re.I,
)
_ABOVE_BELOW = re.compile(
    r"(?:above|below)\s+(?:the\s+)?(?:open(?:ing)?(?:\s+price|\s+reference)?)?\s*\$?([0-9][0-9,]*(?:\.[0-9]+)?)",
    re.I,
)
_TWAP_HINT = re.compile(r"\b(?:twap|chainlink)\b", re.I)


def parse_resolution(raw: dict[str, Any] | None, existing: ResolutionMeta | None = None) -> ResolutionMeta:
    raw = raw or {}
    source = existing.source if existing else None
    source = raw.get("resolutionSource") or raw.get("resolution_source") or source
    uma = (existing.uma_status if existing else None) or raw.get("umaResolutionStatus")
    end_date = (existing.end_date if existing else None) or raw.get("endDate") or raw.get("endDateIso")
    resolved_by = (existing.resolved_by if existing else None) or raw.get("resolvedBy")
    auto = existing.automatically_resolved if existing else None
    if auto is None:
        auto = raw.get("automaticallyResolved")
    fields = [source, uma, end_date, resolved_by]
    present = sum(1 for item in fields if item)
    confidence = present / 4.0
    return ResolutionMeta(
        source=source,
        uma_status=uma,
        end_date=end_date,
        resolved_by=resolved_by,
        automatically_resolved=bool(auto) if auto is not None else None,
        metric=raw.get("groupItemTitle") or raw.get("sportsMarketType"),
        threshold=str(raw["line"]) if raw.get("line") is not None else None,
        time_window=raw.get("gameStartTime") or raw.get("eventStartTime"),
        timezone="UTC",
        rounding_rule=None,
        special_conditions=[],
        parse_confidence=confidence,
        tradeable=confidence >= 0.25 and bool(source or end_date or uma),
    )


def resolution_tradeable(meta: ResolutionMeta) -> bool:
    return meta.tradeable


def parse_end_date(value: str | None) -> datetime | None:
    if not value:
        return None
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed


def _first_number(match: re.Match[str] | None) -> float | None:
    if match is None:
        return None
    return float(match.group(1).replace(",", ""))


def _parse_official_window(text: str) -> int | None:
    found: set[int] = set()
    if any(pat.search(text) for pat in _WINDOW_30):
        found.add(30)
    if any(pat.search(text) for pat in _WINDOW_60):
        found.add(60)
    if len(found) == 1:
        window = next(iter(found))
        if window in RTDS_TWAP_WINDOWS:
            return window
    return None


def _parse_official_symbol(text: str) -> str | None:
    slash = _SLASH_SYMBOL.search(text)
    if slash:
        symbol = f"{slash.group(1).lower()}/{slash.group(2).lower()}"
        if symbol in RTDS_CHAINLINK_SYMBOLS:
            return symbol
        return None
    blob = text.lower()
    for alias, symbol in RTDS_CHAINLINK_SYMBOL_ALIASES.items():
        if re.search(rf"\b{re.escape(alias)}\b", blob):
            return symbol
    return None


def _joined_resolution_text(market: MarketRecord) -> str:
    raw = market.raw_gamma or {}
    parts = [
        market.question or "",
        market.resolution.source or "",
        market.resolution.metric or "",
        market.resolution.threshold or "",
        market.resolution.time_window or "",
        str(raw.get("description") or ""),
        str(raw.get("resolutionSource") or ""),
        str(raw.get("line") or ""),
        " ".join(market.tags),
        market.category or "",
    ]
    return "\n".join(part for part in parts if part)


def parse_twap_resolution(market: MarketRecord) -> TwapResolutionSpec:
    """Identify official RTDS/Chainlink TWAP identity from market metadata.

    Never invent a 30 vs 60 window, a symbol outside the documented Chainlink
    set, or a strike that is not present in metadata/text.
    """
    text = _joined_resolution_text(market)
    is_twap = bool(_TWAP_HINT.search(text))
    window = _parse_official_window(text)
    if window is not None:
        is_twap = True
    symbol = _parse_official_symbol(text)
    opening = _first_number(_OPEN_REF.search(text))
    strike = _first_number(_STRIKE.search(text)) or _first_number(_ABOVE_BELOW.search(text))
    if strike is None and market.resolution.threshold:
        try:
            strike = float(str(market.resolution.threshold).replace(",", ""))
        except ValueError:
            strike = None
    if opening is None and strike is not None and re.search(r"open(?:ing)?", text, re.I):
        opening = strike
    if strike is None and opening is not None:
        strike = opening

    official_formula = False
    calc_rule = (
        "Official docs (docs.polymarket.com/market-data/chainlink-twap) publish "
        "Chainlink-computed 30s/60s TWAP observations only. They do not publish "
        "the start-vs-end / strike settlement formula for Up/Down markets. "
        "Paper path compares the official TWAP observation to the parsed strike."
    )
    if window is not None:
        feed = rtds_twap_topic(window)
    else:
        feed = None

    skip: str | None = None
    if is_twap and window is None:
        skip = ReasonCode.TWAP_WINDOW_UNKNOWN
    elif is_twap and symbol is None:
        skip = ReasonCode.TWAP_SYMBOL_UNKNOWN
    elif is_twap and strike is None:
        skip = ReasonCode.TWAP_STRIKE_UNKNOWN

    complete = bool(is_twap and window in RTDS_TWAP_WINDOWS and symbol and strike is not None and skip is None)
    return TwapResolutionSpec(
        is_twap_market=is_twap,
        feed=feed,
        window_seconds=window,
        symbol=symbol,
        opening_reference=opening,
        strike=strike,
        final_calculation_rule=calc_rule,
        official_settlement_formula_published=official_formula,
        skip_reason=skip,
        complete=complete,
        source_text=text[:800],
    )
