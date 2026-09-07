"""Official-shape Sports WS fixtures. Not live observations.

Field names and the NBA example object follow
https://docs.polymarket.com/market-data/realtime-data
"""

from __future__ import annotations

from datetime import UTC, datetime

from hotflow.types import SportsGameState

# Documented raw WS example (no envelope). Score is a combined "-" string.
OFFICIAL_DOCS_NBA_RAW: dict = {
    "gameId": 5127839,
    "leagueAbbreviation": "NBA",
    "homeTeam": "Los Angeles Lakers",
    "awayTeam": "Boston Celtics",
    "status": "InProgress",
    "live": True,
    "ended": False,
    "score": "98-94",
    "period": "Q4",
    "elapsed": "05:12",
}

OFFICIAL_DOCS_NBA_SDK: dict = {
    "topic": "sports",
    "type": "sport_result",
    "payload": dict(OFFICIAL_DOCS_NBA_RAW),
}


def _now() -> datetime:
    return datetime.now(UTC)


def official_docs_nba_state(*, source: str = "fixture") -> SportsGameState:
    raw = OFFICIAL_DOCS_NBA_RAW
    return SportsGameState(
        game_id=int(raw["gameId"]),
        league_abbreviation=str(raw["leagueAbbreviation"]),
        home_team=str(raw["homeTeam"]),
        away_team=str(raw["awayTeam"]),
        status=str(raw["status"]),
        live=bool(raw["live"]),
        ended=bool(raw["ended"]),
        score=str(raw["score"]),
        period=str(raw["period"]),
        elapsed=str(raw["elapsed"]),
        last_update=_now(),
        source=source,
    )


def paper_nba_lal_bos_state() -> SportsGameState:
    """Labeled paper fixture using official field names (not a live print)."""
    return SportsGameState(
        game_id=5127839,
        league_abbreviation="NBA",
        home_team="Los Angeles Lakers",
        away_team="Boston Celtics",
        status="InProgress",
        live=True,
        ended=False,
        score="110-90",
        period="Q4",
        elapsed="05:12",
        last_update=_now(),
        source="fixture",
    )


def paper_soccer_state() -> SportsGameState:
    return SportsGameState(
        game_id=9001,
        league_abbreviation="Soccer",
        home_team="Arsenal",
        away_team="Chelsea",
        status="InProgress",
        live=True,
        ended=False,
        score="2-0",
        period="2H",
        elapsed="75:00",
        last_update=_now(),
        source="fixture",
    )


def default_sports_cache_fixtures() -> list[SportsGameState]:
    """Official-shape rows for `hotflow sports-cache --mock`."""
    return [official_docs_nba_state(), paper_nba_lal_bos_state(), paper_soccer_state()]
