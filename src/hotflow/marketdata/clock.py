"""Parte 40 — UTC event time + monotonic clocks for latency."""

from __future__ import annotations

import time
from datetime import UTC, datetime


def utc_now() -> datetime:
    return datetime.now(UTC)


def monotonic_ms() -> float:
    return time.monotonic() * 1000.0


class LatencyProbe:
    def __init__(self) -> None:
        self._marks: dict[str, float] = {}
        self.samples: dict[str, list[float]] = {}

    def start(self, name: str) -> None:
        self._marks[name] = monotonic_ms()

    def stop(self, name: str) -> float:
        start = self._marks.get(name)
        if start is None:
            return 0.0
        elapsed = monotonic_ms() - start
        self.samples.setdefault(name, []).append(elapsed)
        return elapsed

    def percentile(self, name: str, q: float) -> float | None:
        rows = sorted(self.samples.get(name, []))
        if not rows:
            return None
        idx = min(len(rows) - 1, max(0, int(round((q / 100.0) * (len(rows) - 1)))))
        return rows[idx]
