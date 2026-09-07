"""Absolute kill switches: block new orders, cancel when safe, keep logs."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime

from hotflow.types import KillSwitchReason


@dataclass
class KillEvent:
    reason: KillSwitchReason
    detail: str
    ts: datetime = field(default_factory=lambda: datetime.now(UTC))
    recovered: bool = False


class KillSwitchBoard:
    def __init__(
        self,
        on_trip: Callable[[KillEvent], None] | None = None,
        on_reset: Callable[[], None] | None = None,
    ) -> None:
        self._active: KillEvent | None = None
        self.history: list[KillEvent] = []
        self._on_trip = on_trip
        self._on_reset = on_reset

    @property
    def tripped(self) -> bool:
        return self._active is not None and not self._active.recovered

    @property
    def reason(self) -> KillSwitchReason | None:
        return self._active.reason if self.tripped and self._active else None

    def trip(self, reason: KillSwitchReason, detail: str = "") -> KillEvent:
        event = KillEvent(reason=reason, detail=detail)
        self._active = event
        self.history.append(event)
        if self._on_trip is not None:
            self._on_trip(event)
        return event

    def reset(self, *, acknowledge: str) -> None:
        if not acknowledge.strip():
            raise ValueError("explicit recovery acknowledgement required")
        if self._active:
            self._active.recovered = True
        self._active = None
        if self._on_reset is not None:
            self._on_reset()
