"""Per-title esports adapters. Refuse rather than share one live model.

Official Sports WS documents Esports statuses and a CS2 example score string.
It does not publish map/economy/round math. AsyncAPI sports score examples
are soccer-style 'N-M' only. Adapters therefore skip unless an injected
official-shape state is ended and uses that documented simple pair.
"""

from __future__ import annotations

from typing import Protocol

from hotflow.fairvalue.sports import parse_score_pair
from hotflow.official import ESPORTS_DOCUMENTED_TITLES
from hotflow.types import EsportsResolutionSpec, SportsGameState


class EsportsModel(Protocol):
    title: str

    def accepts_title(self, title: str) -> bool: ...

    def p_home_win(self, spec: EsportsResolutionSpec, state: SportsGameState) -> float | None: ...


def _ended_simple_pair_p(state: SportsGameState) -> float | None:
    """Only the documented Sports WS 'N-M' score form. Do not parse CS2 '000-000|2-0|Bo3'."""
    if not state.ended:
        return None
    pair = parse_score_pair(state.score)
    if pair is None:
        return None
    home, away = pair
    if home == away:
        return 0.5
    return 0.99 if home > away else 0.01


class _TitleAdapter:
    def __init__(self, title: str) -> None:
        self.title = title

    def accepts_title(self, title: str) -> bool:
        return title == self.title

    def p_home_win(self, spec: EsportsResolutionSpec, state: SportsGameState) -> float | None:
        if spec.game != self.title:
            return None
        return _ended_simple_pair_p(state)


class CS2Adapter(_TitleAdapter):
    def __init__(self) -> None:
        super().__init__("cs2")


class LoLAdapter(_TitleAdapter):
    def __init__(self) -> None:
        super().__init__("lol")


class Dota2Adapter(_TitleAdapter):
    def __init__(self) -> None:
        super().__init__("dota2")


class ValorantAdapter(_TitleAdapter):
    def __init__(self) -> None:
        super().__init__("val")


def esports_adapter_for(title: str | None) -> EsportsModel | None:
    if not title or title not in ESPORTS_DOCUMENTED_TITLES:
        return None
    for model in (CS2Adapter(), LoLAdapter(), Dota2Adapter(), ValorantAdapter()):
        if model.accepts_title(title):
            return model
    return None


class FixtureEsportsSource:
    """Injected official-shape Sports WS rows for paper/pytest. Not live NWS/HLTV."""

    def __init__(self, rows: list[SportsGameState] | None = None) -> None:
        self._rows = list(rows or [])

    def put(self, state: SportsGameState) -> None:
        self._rows.append(state)

    def latest(self, spec: EsportsResolutionSpec) -> SportsGameState | None:
        for row in reversed(self._rows):
            if spec.game and row.league_abbreviation and spec.game != row.league_abbreviation:
                continue
            if spec.home_team and row.home_team:
                if spec.home_team.lower() not in row.home_team.lower():
                    if row.home_team.lower() not in spec.home_team.lower():
                        continue
            return row
        return None
