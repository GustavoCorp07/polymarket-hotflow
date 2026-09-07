"""Parte 41 — time-to-event / time-to-resolution features (UTC)."""

from __future__ import annotations

from datetime import UTC, datetime

from hotflow.types import MarketRecord


def parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    text = value.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def time_to_resolution_seconds(market: MarketRecord, now: datetime | None = None) -> float | None:
    end = parse_iso(market.resolution.end_date)
    if end is None:
        return None
    current = now or datetime.now(UTC)
    return (end - current).total_seconds()


def urgency_score(ttr_seconds: float | None) -> float:
    """Nearer resolution → hotter, but not a guarantee of edge."""
    if ttr_seconds is None or ttr_seconds <= 0:
        return 0.0
    # 5 minutes = 1.0, 7 days ≈ 0
    horizon = 7 * 24 * 3600
    return max(0.0, min(1.0, 1.0 - (ttr_seconds / horizon)))
