from __future__ import annotations

from datetime import UTC, datetime

from pydantic import BaseModel, Field


class ExperimentRecord(BaseModel):
    experiment_id: str
    strategy: str
    category: str
    notes: str = ""
    params: dict[str, str] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    paper_only: bool = True
