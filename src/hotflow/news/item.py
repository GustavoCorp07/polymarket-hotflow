"""Structured news / event objects. Impact features only — never orders."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field

from hotflow.reason_codes import ReasonCode


class NewsClass(StrEnum):
    OFFICIAL = "official"
    WIRE = "wire"
    BREAKING = "breaking"
    COMMENTARY = "commentary"
    RUMOR = "rumor"
    UNKNOWN = "unknown"


class NewsItem(BaseModel):
    """Labeled or injected item. The hot path never invents headlines or p-shifts."""

    news_id: str
    headline: str
    body: str = ""
    source_id: str
    source_name: str = ""
    published_at: datetime
    ingested_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    market_id: str | None = None
    resolution_terms: list[str] = Field(default_factory=list)
    event_key: str | None = None
    classification_label: NewsClass | None = None
    claimed_p_shift: float | None = None
    claimed_p_after: float | None = None
    pre_event_mid: float | None = None
    labels: dict[str, Any] = Field(default_factory=dict)
    origin: str = "fixture"


class NewsImpact(BaseModel):
    apply: bool = False
    reason: ReasonCode | None = None
    detail: str = ""
    news_id: str | None = None
    classification: NewsClass = NewsClass.UNKNOWN
    source_authority: float = 0.0
    relevance: float = 0.0
    confidence: float = 0.0
    p_shift: float = 0.0
    p_info_adjusted: float | None = None
    p_base: float | None = None
    duplicate: bool = False
    already_repriced: bool = False
    origin: str = "fixture"
    fingerprint: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="json")
