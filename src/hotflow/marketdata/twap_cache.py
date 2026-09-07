"""In-memory + optional on-disk cache of official Chainlink/RTDS TWAP prints.

Never invents a print. Unofficial windows or symbols are refused.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from hotflow.official import RTDS_CHAINLINK_SYMBOLS, RTDS_TWAP_WINDOWS
from hotflow.types import OfficialTwapObservation

Freshness = Literal["fresh", "stale", "missing"]


def observation_age_ms(observation: OfficialTwapObservation, now: datetime | None = None) -> float:
    current = now or datetime.now(UTC)
    # Fixtures keep the docs example payload.timestamp; freshness is ingest time.
    # Live prints use Chainlink observation time when present.
    if observation.source != "fixture" and observation.payload_timestamp_ms is not None:
        chainlink = datetime.fromtimestamp(observation.payload_timestamp_ms / 1000.0, tz=UTC)
        return max(0.0, (current - chainlink).total_seconds() * 1000.0)
    observed = observation.observed_at
    if observed.tzinfo is None:
        observed = observed.replace(tzinfo=UTC)
    return max(0.0, (current - observed).total_seconds() * 1000.0)


def observation_status(
    observation: OfficialTwapObservation | None,
    *,
    max_age_ms: int,
    now: datetime | None = None,
) -> Freshness:
    if observation is None:
        return "missing"
    if observation_age_ms(observation, now) > max_age_ms:
        return "stale"
    return "fresh"


class TwapPrintCache:
    """Latest official print per (symbol, window). Implements TwapObservationSource."""

    def __init__(
        self,
        *,
        max_age_ms: int,
        path: Path | str | None = None,
        persist: bool = False,
    ) -> None:
        self.max_age_ms = max_age_ms
        self.path = Path(path) if path else None
        self.persist = persist
        self._rows: dict[tuple[str, int], OfficialTwapObservation] = {}

    def put(self, observation: OfficialTwapObservation) -> bool:
        symbol = observation.symbol.lower()
        window = observation.window_seconds
        if window not in RTDS_TWAP_WINDOWS:
            return False
        if symbol not in RTDS_CHAINLINK_SYMBOLS:
            return False
        stored = observation.model_copy(update={"symbol": symbol})
        self._rows[(symbol, window)] = stored
        if self.persist:
            self.save()
        return True

    def latest(self, symbol: str, window_seconds: int) -> OfficialTwapObservation | None:
        return self._rows.get((symbol.lower(), window_seconds))

    def status(self, symbol: str, window_seconds: int, *, now: datetime | None = None) -> Freshness:
        return observation_status(self.latest(symbol, window_seconds), max_age_ms=self.max_age_ms, now=now)

    def snapshot(self) -> dict[str, Any]:
        return {
            "source": "rtds_twap_cache",
            "max_age_ms": self.max_age_ms,
            "prints": [row.model_dump(mode="json") for row in self._rows.values()],
        }

    def save(self, path: Path | str | None = None) -> Path:
        target = Path(path) if path else self.path
        if target is None:
            raise ValueError("no cache path configured")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(self.snapshot(), indent=2, default=str), encoding="utf-8")
        return target

    def load(self, path: Path | str | None = None) -> int:
        target = Path(path) if path else self.path
        if target is None or not target.exists():
            return 0
        raw = json.loads(target.read_text(encoding="utf-8"))
        rows = raw.get("prints") if isinstance(raw, dict) else raw
        if not isinstance(rows, list):
            return 0
        loaded = 0
        for item in rows:
            if not isinstance(item, dict):
                continue
            obs = OfficialTwapObservation.model_validate(item)
            if self.put(obs):
                loaded += 1
        return loaded

    @classmethod
    def from_path(cls, path: Path | str, *, max_age_ms: int) -> TwapPrintCache:
        cache = cls(max_age_ms=max_age_ms, path=path, persist=False)
        cache.load()
        return cache
