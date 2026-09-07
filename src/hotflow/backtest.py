"""Event-driven backtester interfaces (scaffold)."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol


@dataclass(frozen=True)
class MarketEvent:
    ts: datetime
    kind: str
    payload: dict[str, Any]


class EventSource(Protocol):
    def events(self) -> Iterable[MarketEvent]: ...


class BacktestEngine(Protocol):
    def run(self, source: EventSource) -> dict[str, Any]: ...


class NullBacktester:
    def run(self, source: EventSource) -> dict[str, Any]:
        count = sum(1 for _ in source.events())
        return {"events": count, "status": "stub", "mode": "offline"}
