"""In-memory + optional on-disk cache of official Sports WS game updates.

Never invents a score, league, or game id. Undocumented leagues are refused.
Sports data is informational (may be delayed or wrong) per Polymarket docs.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from hotflow.official import SPORTS_DOCUMENTED_LEAGUES, canonicalize_sports_league
from hotflow.types import SportsGameState, SportsResolutionSpec

Freshness = Literal["fresh", "stale", "missing"]

CACHE_DISCLAIMER = (
    "Sports data is provided for informational purposes only. It may be delayed, "
    "contain errors, or omit recent events. Polymarket does not provide trading "
    "or investment advice, and this data should not be used as the basis for a "
    "trading decision. Source: docs.polymarket.com/market-data/realtime-data"
)


def game_state_age_ms(state: SportsGameState, now: datetime | None = None) -> float:
    current = now or datetime.now(UTC)
    observed = state.last_update
    if observed.tzinfo is None:
        observed = observed.replace(tzinfo=UTC)
    return max(0.0, (current - observed).total_seconds() * 1000.0)


def game_state_status(
    state: SportsGameState | None,
    *,
    max_age_ms: int,
    now: datetime | None = None,
) -> Freshness:
    if state is None:
        return "missing"
    if game_state_age_ms(state, now) > max_age_ms:
        return "stale"
    return "fresh"


class SportsGameCache:
    """Latest official-shape game per gameId. Implements SportsStateSource."""

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
        self._rows: dict[int, SportsGameState] = {}

    def put(self, state: SportsGameState) -> bool:
        if state.game_id is None:
            return False
        game_id = state.game_id
        league = canonicalize_sports_league(state.league_abbreviation)
        if not league or league not in SPORTS_DOCUMENTED_LEAGUES:
            return False
        if league != state.league_abbreviation:
            state = state.model_copy(update={"league_abbreviation": league})
        self._rows[game_id] = state
        if self.persist:
            self.save()
        return True

    def latest(self, spec: SportsResolutionSpec) -> SportsGameState | None:
        for row in reversed(list(self._rows.values())):
            if spec.league and row.league_abbreviation and spec.league != row.league_abbreviation:
                continue
            if spec.home_team and row.home_team and spec.home_team.lower() not in row.home_team.lower():
                if row.home_team.lower() not in spec.home_team.lower():
                    continue
            return row
        return None

    def latest_by_id(self, game_id: int) -> SportsGameState | None:
        return self._rows.get(game_id)

    def status(self, spec: SportsResolutionSpec, *, now: datetime | None = None) -> Freshness:
        return game_state_status(self.latest(spec), max_age_ms=self.max_age_ms, now=now)

    def snapshot(self) -> dict[str, Any]:
        return {
            "source": "sports_ws_cache",
            "informational": True,
            "disclaimer": CACHE_DISCLAIMER,
            "max_age_ms": self.max_age_ms,
            "games": [row.model_dump(mode="json") for row in self._rows.values()],
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
        rows = raw.get("games") if isinstance(raw, dict) else raw
        if not isinstance(rows, list):
            return 0
        loaded = 0
        for item in rows:
            if not isinstance(item, dict):
                continue
            state = SportsGameState.model_validate(item)
            if self.put(state):
                loaded += 1
        return loaded

    @classmethod
    def from_path(cls, path: Path | str, *, max_age_ms: int) -> SportsGameCache:
        cache = cls(max_age_ms=max_age_ms, path=path, persist=False)
        cache.load()
        return cache
