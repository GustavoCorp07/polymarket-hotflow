"""Official Sports WebSocket interface.

wss://sports-api.polymarket.com/ws — public, no subscribe frame.
Server sends text `ping` every 5s; reply `pong` within 10s.
https://docs.polymarket.com/market-data/realtime-data

pytest injects frames. Optional live client is default-off.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any, Protocol

from hotflow.marketdata.websocket import SPORTS_HEARTBEAT
from hotflow.official import SPORTS_CLIENT_PONG, SPORTS_SERVER_PING, SPORTS_WS, canonicalize_sports_league
from hotflow.types import SportsGameState, SportsResolutionSpec


def parse_official_sports_message(raw: str | dict[str, Any]) -> SportsGameState | None:
    """Accept raw WS objects (no envelope) or SDK `{topic,type,payload}`."""
    if isinstance(raw, str):
        if raw == SPORTS_SERVER_PING:
            return None
        try:
            message = json.loads(raw)
        except json.JSONDecodeError:
            return None
    else:
        message = raw
    if not isinstance(message, dict):
        return None
    payload = message.get("payload") if message.get("type") == "sport_result" else message
    if not isinstance(payload, dict):
        return None
    if payload.get("gameId") is None and payload.get("game_id") is None:
        return None
    game_id = payload.get("gameId", payload.get("game_id"))
    return SportsGameState(
        game_id=int(game_id) if game_id is not None else None,
        league_abbreviation=canonicalize_sports_league(
            payload.get("leagueAbbreviation") or payload.get("league_abbreviation")
        ),
        home_team=payload.get("homeTeam") or payload.get("home_team"),
        away_team=payload.get("awayTeam") or payload.get("away_team"),
        status=payload.get("status"),
        live=payload.get("live"),
        ended=payload.get("ended"),
        score=payload.get("score"),
        period=payload.get("period"),
        elapsed=payload.get("elapsed"),
        slug=payload.get("slug"),
        turn=payload.get("turn"),
        finished_at=payload.get("finishedAt") or payload.get("finished_at") or payload.get("finished_timestamp"),
        last_update=datetime.now(UTC),
        source="live_sports_ws" if message.get("type") == "sport_result" or "gameId" in payload else "fixture",
    )


class SportsStateSource(Protocol):
    def latest(self, spec: SportsResolutionSpec) -> SportsGameState | None: ...


def game_state_from_metadata(spec: SportsResolutionSpec) -> SportsGameState | None:
    """Use official-named fields already present on the market. Never invent a score."""
    if spec.score is None and spec.period is None and spec.live is None and spec.ended is None:
        return None
    return SportsGameState(
        league_abbreviation=spec.league,
        home_team=spec.home_team,
        away_team=spec.away_team,
        live=spec.live,
        ended=spec.ended,
        score=spec.score,
        period=spec.period,
        source="gamma_metadata",
    )


class FixtureSportsSource:
    def __init__(self, rows: list[SportsGameState] | None = None) -> None:
        self._rows = list(rows or [])

    def put(self, state: SportsGameState) -> None:
        self._rows.append(state)

    def latest(self, spec: SportsResolutionSpec) -> SportsGameState | None:
        for row in reversed(self._rows):
            if spec.league and row.league_abbreviation and spec.league != row.league_abbreviation:
                continue
            if spec.home_team and row.home_team and spec.home_team.lower() not in row.home_team.lower():
                if row.home_team.lower() not in spec.home_team.lower():
                    continue
            return row
        return None


class PublicSportsWsClient:
    """OPTIONAL unauthenticated Sports WS reader. pytest never opens this socket."""

    url = SPORTS_WS
    optional_live_public = True
    heartbeat = SPORTS_HEARTBEAT

    def __init__(self) -> None:
        self._latest: dict[int, SportsGameState] = {}
        self.last_ping_seen = False

    def handle_payload(self, raw: str | dict[str, Any]) -> str | SportsGameState | None:
        if raw == SPORTS_SERVER_PING:
            self.last_ping_seen = True
            return SPORTS_CLIENT_PONG
        parsed = parse_official_sports_message(raw)
        if parsed is not None and parsed.game_id is not None:
            game_id = parsed.game_id
            parsed = parsed.model_copy(update={"source": "live_sports_ws"})
            self._latest[game_id] = parsed
        return parsed

    def latest_by_id(self, game_id: int) -> SportsGameState | None:
        return self._latest.get(game_id)
