"""PAPER weather + sports adapters. No paid weather APIs, no live Sports sockets."""

from __future__ import annotations

import json
from pathlib import Path

from hotflow.config import load_config
from hotflow.discovery.resolution import parse_sports_resolution, parse_weather_resolution
from hotflow.fairvalue.sports import NBABasketballModel, SoccerModel, sports_model_for
from hotflow.fairvalue.weather import WeatherFairValue, weather_p_above_threshold
from hotflow.marketdata.sports_ws import (
    PublicSportsWsClient,
    parse_official_sports_message,
)
from hotflow.marketdata.weather_fixtures import FixtureWeatherSource, default_weather_forecast
from hotflow.official import SPORTS_CLIENT_PONG, SPORTS_DOCUMENTED_LEAGUES, SPORTS_SERVER_PING, SPORTS_WS
from hotflow.pipeline import (
    PaperPipeline,
    demo_market,
    demo_sports_nba_market,
    demo_sports_soccer_market,
    demo_sports_tennis_market,
    demo_twap_market,
    demo_weather_market,
)
from hotflow.reason_codes import ReasonCode
from hotflow.strategies.esports import EsportsStrategy
from hotflow.strategies.sports import SportsStrategy
from hotflow.strategies.weather import WeatherStrategy
from hotflow.types import SportsGameState, WeatherForecast, WeatherResolutionSpec


def test_weather_parse_complete_demo() -> None:
    spec = parse_weather_resolution(demo_weather_market())
    assert spec.complete
    assert spec.city and "Chicago" in spec.city
    assert spec.station == "KORD"
    assert spec.metric == "high temperature"
    assert spec.unit in {"°F", "Fahrenheit", "fahrenheit"}
    assert spec.timezone == "America/Chicago"
    assert spec.rounding_rule == "nearest_degree"
    assert spec.time_window is not None
    assert spec.threshold == 70.0
    assert spec.source
    assert spec.parse_confidence >= 0.5
    assert spec.skip_reason is None


def test_weather_parse_missing_source_skips() -> None:
    market = demo_weather_market()
    market.resolution.source = None
    market.raw_gamma = {"description": "high temperature in Chicago above 70 °F", "line": 70}
    spec = parse_weather_resolution(market)
    assert spec.complete is False
    assert spec.skip_reason == ReasonCode.WEATHER_RULES_UNKNOWN


def test_weather_forecast_is_feature_not_resolver() -> None:
    spec = parse_weather_resolution(demo_weather_market())
    forecast = default_weather_forecast()
    assert forecast.source == "fixture"
    p_labeled = WeatherFairValue().p_info(spec, forecast)
    assert p_labeled == 0.92
    dist = WeatherForecast(mean=78.0, std=2.5, source="fixture")
    p_dist = weather_p_above_threshold(spec, dist)
    assert p_dist is not None and p_dist > 0.9


def test_weather_pipeline_accepts_fixture() -> None:
    cfg = load_config(Path("configs/default.yaml"))
    pipe = PaperPipeline(cfg, use_twap_fixtures=True)
    result = pipe.evaluate_market(demo_weather_market(hot=True))
    assert result["accepted"] is True
    assert result["reason"] == ReasonCode.OK
    assert result["weather_spec"]["complete"] is True
    assert result["weather_forecast"]["source"] == "fixture"
    assert result.get("twap") is None


def test_weather_missing_forecast_skips() -> None:
    cfg = load_config(Path("configs/default.yaml"))
    pipe = PaperPipeline(cfg, weather_source=FixtureWeatherSource())
    result = pipe.evaluate_market(demo_weather_market(hot=True))
    assert result["accepted"] is False
    assert result["reason"] == ReasonCode.WEATHER_FORECAST_MISSING


def test_weather_disabled_skips() -> None:
    cfg = load_config(Path("configs/default.yaml"))
    cfg.weather.enabled = False
    pipe = PaperPipeline(cfg, use_twap_fixtures=True)
    result = pipe.evaluate_market(demo_weather_market(hot=True))
    assert result["accepted"] is False
    assert result["reason"] == ReasonCode.CATEGORY_DISABLED


def test_sports_parse_nba_and_soccer() -> None:
    nba = parse_sports_resolution(demo_sports_nba_market())
    assert nba.complete
    assert nba.league == "NBA"
    assert nba.home_team == "Los Angeles Lakers"
    assert nba.away_team == "Boston Celtics"
    soccer = parse_sports_resolution(demo_sports_soccer_market())
    assert soccer.complete
    assert soccer.league == "Soccer"


def test_sports_does_not_map_football_to_soccer() -> None:
    market = demo_sports_soccer_market()
    market.raw_gamma["leagueAbbreviation"] = "football"
    market.tags = ["sports", "football"]
    market.question = "Home vs Away football"
    spec = parse_sports_resolution(market)
    assert spec.league is None
    assert spec.complete is False
    assert spec.skip_reason == ReasonCode.SPORTS_RULES_UNKNOWN


def test_per_sport_models_are_distinct() -> None:
    nba = NBABasketballModel()
    soccer = SoccerModel()
    spec_nba = parse_sports_resolution(demo_sports_nba_market())
    spec_soccer = parse_sports_resolution(demo_sports_soccer_market())
    same_score = SportsGameState(
        league_abbreviation="NBA",
        home_team="A",
        away_team="B",
        status="InProgress",
        live=True,
        ended=False,
        score="2-0",
        period="Q4",
        source="fixture",
    )
    soccer_state = same_score.model_copy(update={"league_abbreviation": "Soccer", "period": "2H"})
    p_nba = nba.p_home_win(spec_nba, same_score)
    p_soccer = soccer.p_home_win(spec_soccer, soccer_state)
    assert p_nba is not None and p_soccer is not None
    assert abs(p_nba - p_soccer) > 0.1
    assert nba.accepts_league("Soccer") is False
    assert soccer.accepts_league("NBA") is False
    assert sports_model_for("Tennis") is None
    assert sports_model_for("NFL") is None
    assert sports_model_for("Esports") is None


def test_sports_pipeline_nba_accepts() -> None:
    cfg = load_config(Path("configs/default.yaml"))
    pipe = PaperPipeline(cfg, use_twap_fixtures=True)
    result = pipe.evaluate_market(demo_sports_nba_market(hot=True))
    assert result["accepted"] is True
    assert result["sports_model"] == "basketball"
    assert result["sports_state"]["score"] == "110-90"
    assert result.get("twap") is None


def test_sports_pipeline_soccer_accepts() -> None:
    cfg = load_config(Path("configs/default.yaml"))
    pipe = PaperPipeline(cfg, use_twap_fixtures=True)
    result = pipe.evaluate_market(demo_sports_soccer_market(hot=True))
    assert result["accepted"] is True
    assert result["sports_model"] == "soccer"


def test_tennis_refuses_shared_model() -> None:
    cfg = load_config(Path("configs/default.yaml"))
    pipe = PaperPipeline(cfg, use_twap_fixtures=True)
    result = pipe.evaluate_market(demo_sports_tennis_market(hot=True))
    assert result["accepted"] is False
    assert result["reason"] == ReasonCode.UNSUPPORTED_SPORT
    assert result["league"] == "Tennis"


def test_sports_state_missing() -> None:
    cfg = load_config(Path("configs/default.yaml"))
    from hotflow.marketdata.sports_ws import FixtureSportsSource

    pipe = PaperPipeline(cfg, sports_source=FixtureSportsSource())
    result = pipe.evaluate_market(demo_sports_nba_market(hot=True))
    assert result["accepted"] is False
    assert result["reason"] == ReasonCode.SPORTS_STATE_MISSING


def test_sports_disabled_skips() -> None:
    cfg = load_config(Path("configs/default.yaml"))
    cfg.sports.enabled = False
    pipe = PaperPipeline(cfg, use_twap_fixtures=True)
    result = pipe.evaluate_market(demo_sports_nba_market(hot=True))
    assert result["accepted"] is False
    assert result["reason"] == ReasonCode.CATEGORY_DISABLED


def test_sports_ws_official_frames_and_ping() -> None:
    raw = {
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
    parsed = parse_official_sports_message(json.dumps(raw))
    assert parsed is not None
    assert parsed.game_id == 5127839
    assert parsed.score == "98-94"
    sdk = {"topic": "sports", "type": "sport_result", "payload": raw}
    envelope = parse_official_sports_message(sdk)
    assert envelope is not None
    assert envelope.league_abbreviation == "NBA"
    client = PublicSportsWsClient()
    assert client.url == SPORTS_WS
    assert client.optional_live_public is True
    assert client.handle_payload(SPORTS_SERVER_PING) == SPORTS_CLIENT_PONG
    assert client.last_ping_seen is True
    stored = client.handle_payload(raw)
    assert isinstance(stored, SportsGameState)
    assert stored.source == "live_sports_ws"
    assert SPORTS_DOCUMENTED_LEAGUES == {
        "NFL",
        "NHL",
        "MLB",
        "NBA",
        "CBB",
        "CFB",
        "Soccer",
        "Esports",
        "Tennis",
    }


def test_crypto_twap_path_untouched() -> None:
    cfg = load_config(Path("configs/default.yaml"))
    pipe = PaperPipeline(cfg, use_twap_fixtures=True)
    result = pipe.evaluate_market(demo_twap_market(hot=True))
    assert result["accepted"] is True
    assert result["twap"]["window_seconds"] == 60
    assert result["twap"]["current_twap"] == 68000.0


def test_esports_remains_stub() -> None:
    cfg = load_config(Path("configs/default.yaml"))
    pipe = PaperPipeline(cfg, use_twap_fixtures=True)
    market = demo_market(hot=True)
    market.category = "esports"
    market.tags = ["esports"]
    result = pipe.evaluate_market(market)
    assert result["accepted"] is False
    assert result["reason"] == ReasonCode.UNSUPPORTED_STRUCTURE
    stub = EsportsStrategy()
    assert stub.experiment_fields()["status"] == "stub"


def test_strategy_adapters() -> None:
    weather = demo_weather_market()
    sports = demo_sports_nba_market()
    assert WeatherStrategy().accepts(weather)
    assert SportsStrategy().accepts(sports)
    assert SportsStrategy().model_name("NBA") == "basketball"
    assert SportsStrategy().model_name("Soccer") == "soccer"
    assert SportsStrategy().model_name("Tennis") is None
    assert WeatherStrategy().experiment_fields()["forecast_role"] == "feature_only"


def test_cli_paper_run_mock_weather_and_sports(tmp_path) -> None:
    from typer.testing import CliRunner

    from hotflow.cli import app

    out = tmp_path / "paper.json"
    completed = CliRunner().invoke(app, ["paper-run", "--mock", "--out", str(out)])
    assert completed.exit_code == 0, completed.output
    payload = json.loads(out.read_text(encoding="utf-8"))
    results = payload["cycles"][0]["results"]
    assert len(results) == 3
    assert results[0]["accepted"] is True
    assert results[0]["twap"]["window_seconds"] in {30, 60}
    assert results[1]["accepted"] is True
    assert results[1]["weather_spec"]["city"]
    assert results[2]["accepted"] is True
    assert results[2]["sports_model"] == "basketball"


def test_config_toggles_safe_defaults() -> None:
    cfg = load_config(Path("configs/default.yaml"))
    assert cfg.trading.mode == "paper"
    assert cfg.weather.enabled is True
    assert cfg.sports.enabled is True
    assert cfg.sports.live_public_client is False
    assert cfg.feeds.sports_ws.ping_interval_s == 5.0


def test_incomplete_weather_forecast_distribution_skips() -> None:
    spec = WeatherResolutionSpec(
        city="Chicago",
        station="KORD",
        metric="high temperature",
        unit="°F",
        timezone="America/Chicago",
        threshold=70.0,
        source="nws",
        complete=True,
        parse_confidence=0.8,
    )
    assert weather_p_above_threshold(spec, WeatherForecast(mean=72.0, source="fixture")) is None
