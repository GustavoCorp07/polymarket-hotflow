"""Parte 42 — structured resolution object. Unknown rules => DO_NOT_TRADE."""

from __future__ import annotations

from typing import Any

from hotflow.types import ResolutionMeta


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
