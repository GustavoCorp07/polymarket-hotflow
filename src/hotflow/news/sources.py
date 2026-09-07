"""Fixture source-authority table. Not a live news crawl."""

from __future__ import annotations

# Authority in [0, 1]. Unknown ids score 0 and fail validation.
SOURCE_AUTHORITY: dict[str, float] = {
    "sec.gov": 0.95,
    "federal_reserve": 0.95,
    "cftc": 0.90,
    "treasury.gov": 0.90,
    "reuters": 0.80,
    "ap": 0.80,
    "bloomberg": 0.78,
    "fixture_official": 0.92,
    "fixture_wire": 0.75,
    "fixture_commentary": 0.62,
    "fixture_rumor": 0.20,
    "anon_blog": 0.10,
}

CLASS_WEIGHT: dict[str, float] = {
    "official": 1.00,
    "wire": 0.85,
    "breaking": 0.70,
    "commentary": 0.40,
    "rumor": 0.25,
    "unknown": 0.15,
}


def source_authority(source_id: str) -> float:
    return float(SOURCE_AUTHORITY.get(source_id.strip().lower(), 0.0))
