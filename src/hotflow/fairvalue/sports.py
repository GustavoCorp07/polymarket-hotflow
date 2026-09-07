"""Per-sport paper models. Do not reuse one probabilistic model across sports."""

from __future__ import annotations

from typing import Protocol

from hotflow.types import SportsGameState, SportsResolutionSpec


def parse_score_pair(score: str | None) -> tuple[int, int] | None:
    """Official Sports WS score is a combined '-' string."""
    if not score or "-" not in score:
        return None
    left, right = score.split("-", 1)
    try:
        return int(left.strip()), int(right.strip())
    except ValueError:
        return None


class SportsModel(Protocol):
    sport: str

    def accepts_league(self, league: str) -> bool: ...

    def p_home_win(self, spec: SportsResolutionSpec, state: SportsGameState) -> float | None: ...


class NBABasketballModel:
    """NBA/CBB paper heuristic using quarters. Not a soccer/tennis model."""

    sport = "basketball"
    leagues = frozenset({"NBA", "CBB"})

    def accepts_league(self, league: str) -> bool:
        return league.upper() in self.leagues

    def p_home_win(self, spec: SportsResolutionSpec, state: SportsGameState) -> float | None:
        pair = parse_score_pair(state.score)
        if pair is None:
            return None
        home, away = pair
        # Official NBA/CBB statuses only (docs.polymarket.com realtime-data).
        if state.ended or (state.status or "") in {"Final", "F/OT", "Forfeit"}:
            if home == away:
                return 0.5
            return 0.99 if home > away else 0.01
        # Remaining regulation quarters — official 1Q–4Q plus example Q1–Q4 / HT.
        period = (state.period or "").upper().replace(" ", "")
        remaining_q = {
            "1Q": 3.4,
            "Q1": 3.4,
            "2Q": 2.4,
            "Q2": 2.4,
            "HT": 2.0,
            "3Q": 1.4,
            "Q3": 1.4,
            "4Q": 0.4,
            "Q4": 0.4,
        }
        left = remaining_q.get(period)
        if left is None:
            return None
        margin = home - away
        # ~28 pts expected per remaining quarter in this paper basketball model.
        pace = 28.0 * left
        z = margin / max(8.0, pace**0.5 * 4.0)
        return max(0.02, min(0.98, 0.5 + 0.45 * (z / (1.0 + abs(z)))))


class SoccerModel:
    """Soccer paper heuristic using halves and official Soccer statuses. Not NBA."""

    sport = "soccer"
    leagues = frozenset({"Soccer"})

    def accepts_league(self, league: str) -> bool:
        return league == "Soccer"

    def p_home_win(self, spec: SportsResolutionSpec, state: SportsGameState) -> float | None:
        pair = parse_score_pair(state.score)
        if pair is None:
            return None
        home, away = pair
        if state.ended or (state.status or "") in {"Final", "Awarded"}:
            if home == away:
                return 0.5
            return 0.99 if home > away else 0.01
        # Remaining minutes of 90 — soccer periods only (1H/2H/HT).
        period = (state.period or "").upper()
        remaining_min = {"1H": 70.0, "HT": 45.0, "2H": 20.0, "BREAK": 45.0}.get(period)
        if remaining_min is None:
            return None
        # Low-scoring: ~1.2 expected remaining goals per 45 minutes (paper only).
        expected_remain = 1.2 * (remaining_min / 45.0)
        margin = float(home - away)
        z = (margin + 0.15) / max(0.55, expected_remain**0.5)
        return max(0.05, min(0.95, 0.5 + 0.40 * (z / (1.0 + abs(z)))))


def sports_model_for(league: str | None) -> SportsModel | None:
    if not league:
        return None
    for model in (NBABasketballModel(), SoccerModel()):
        if model.accepts_league(league):
            return model
    return None
