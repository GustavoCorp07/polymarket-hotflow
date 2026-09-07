"""PAPER Sports WS cache/subscriber. pytest never opens the live socket."""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from hotflow.config import HotflowConfig, SportsWsFeedConfig, load_config
from hotflow.marketdata.rtds_subscriber import InjectedFrameTransport
from hotflow.marketdata.sports_cache import SportsGameCache, game_state_status
from hotflow.marketdata.sports_fixtures import (
    OFFICIAL_DOCS_NBA_RAW,
    OFFICIAL_DOCS_NBA_SDK,
    default_sports_cache_fixtures,
    official_docs_nba_state,
    paper_nba_lal_bos_state,
)
from hotflow.marketdata.sports_subscriber import PublicSportsSubscriber
from hotflow.official import SPORTS_CLIENT_PONG, SPORTS_SERVER_PING, SPORTS_WS
from hotflow.pipeline import PaperPipeline, demo_sports_nba_market
from hotflow.reason_codes import ReasonCode
from hotflow.types import SportsGameState


def test_cache_accepts_official_and_rejects_invented() -> None:
    cache = SportsGameCache(max_age_ms=15_000)
    assert cache.put(official_docs_nba_state()) is True
    assert cache.latest_by_id(5127839) is not None
    invented = SportsGameState(
        game_id=1,
        league_abbreviation="EPL",
        home_team="A",
        away_team="B",
        score="1-0",
        source="fixture",
    )
    missing_id = official_docs_nba_state().model_copy(update={"game_id": None})
    assert cache.put(invented) is False
    assert cache.put(missing_id) is False
    assert cache.latest_by_id(1) is None


def test_cache_persist_and_load(tmp_path: Path) -> None:
    path = tmp_path / "sports.json"
    cache = SportsGameCache(max_age_ms=15_000, path=path, persist=True)
    cache.put(paper_nba_lal_bos_state())
    assert path.exists()
    loaded = SportsGameCache.from_path(path, max_age_ms=15_000)
    row = loaded.latest_by_id(5127839)
    assert row is not None
    assert row.score == "110-90"
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["informational"] is True
    assert "delayed" in payload["disclaimer"]


def test_freshness_missing_and_stale() -> None:
    assert game_state_status(None, max_age_ms=1000) == "missing"
    stale = official_docs_nba_state().model_copy(
        update={"last_update": datetime.now(UTC) - timedelta(seconds=30)}
    )
    assert game_state_status(stale, max_age_ms=1000) == "stale"
    assert game_state_status(official_docs_nba_state(), max_age_ms=15_000) == "fresh"


def test_cache_hit_feeds_sports_fair_value() -> None:
    cache = SportsGameCache(max_age_ms=15_000)
    cache.put(paper_nba_lal_bos_state())
    pipe = PaperPipeline(HotflowConfig(), sports_source=cache)
    result = pipe.evaluate_market(demo_sports_nba_market(hot=True))
    assert result["accepted"] is True
    assert result["sports_state"]["score"] == "110-90"
    assert result["sports_model"] == "basketball"


def test_stale_cache_skips_without_inventing() -> None:
    cache = SportsGameCache(max_age_ms=500)
    old = paper_nba_lal_bos_state().model_copy(
        update={"last_update": datetime.now(UTC) - timedelta(seconds=5)}
    )
    cache.put(old)
    cfg = HotflowConfig()
    cfg.feeds.sports_ws.max_data_age_ms = 500
    pipe = PaperPipeline(cfg, sports_source=cache)
    result = pipe.evaluate_market(demo_sports_nba_market(hot=True))
    assert result["accepted"] is False
    assert result["reason"] == ReasonCode.SPORTS_STATE_STALE


def test_missing_cache_skips() -> None:
    pipe = PaperPipeline(HotflowConfig(), sports_source=SportsGameCache(max_age_ms=15_000))
    result = pipe.evaluate_market(demo_sports_nba_market(hot=True))
    assert result["accepted"] is False
    assert result["reason"] == ReasonCode.SPORTS_STATE_MISSING


def test_subscriber_ingests_official_frames_no_network() -> None:
    cache = SportsGameCache(max_age_ms=15_000)
    transport = InjectedFrameTransport([json.dumps(OFFICIAL_DOCS_NBA_RAW)])
    cfg = SportsWsFeedConfig(max_data_age_ms=15_000, ping_interval_s=5, collect_seconds=1.0)
    sub = PublicSportsSubscriber(cache, config=cfg, transport=transport)

    prints = asyncio.run(sub.run(max_prints=1, duration_s=1.0))
    assert prints == 1
    assert sub.frames_seen == 1
    row = cache.latest_by_id(5127839)
    assert row is not None
    assert row.score == "98-94"
    assert row.source == "live_sports_ws"
    assert sub.url == SPORTS_WS
    assert sub.optional_live_public is True
    assert sub.informational is True
    # Official Sports WS: no subscribe frame.
    assert not any("subscribe" in item.lower() for item in transport.sent)


def test_subscriber_sdk_envelope_and_server_ping() -> None:
    cache = SportsGameCache(max_age_ms=15_000)
    transport = InjectedFrameTransport([SPORTS_SERVER_PING, json.dumps(OFFICIAL_DOCS_NBA_SDK)])
    sub = PublicSportsSubscriber(
        cache,
        config=SportsWsFeedConfig(max_data_age_ms=15_000, ping_interval_s=1, collect_seconds=1.0),
        transport=transport,
    )
    asyncio.run(sub.run(max_prints=1, duration_s=1.0))
    assert SPORTS_CLIENT_PONG in transport.sent
    assert sub.pongs_sent >= 1
    assert cache.latest_by_id(5127839) is not None


def test_subscriber_reconnect_no_subscribe() -> None:
    cache = SportsGameCache(max_age_ms=15_000)
    transport = InjectedFrameTransport()
    transport.push_disconnect()
    transport.push(json.dumps(OFFICIAL_DOCS_NBA_RAW))
    sub = PublicSportsSubscriber(
        cache,
        config=SportsWsFeedConfig(
            max_data_age_ms=15_000,
            ping_interval_s=1,
            reconnect_max_backoff_s=0.01,
            collect_seconds=2.0,
        ),
        transport=transport,
    )
    asyncio.run(sub.run(max_prints=1, duration_s=2.0))
    assert sub.reconnects >= 1
    assert cache.latest_by_id(5127839) is not None
    assert not any("subscribe" in item.lower() for item in transport.sent)


def test_subscriber_does_not_send_unsolicited_pong() -> None:
    cache = SportsGameCache(max_age_ms=15_000)
    transport = InjectedFrameTransport()
    sub = PublicSportsSubscriber(
        cache,
        config=SportsWsFeedConfig(max_data_age_ms=15_000, ping_interval_s=0.05, collect_seconds=0.16),
        transport=transport,
    )
    asyncio.run(sub.run(duration_s=0.16))
    assert SPORTS_CLIENT_PONG not in transport.sent


def test_cache_casefolds_documented_league_only() -> None:
    cache = SportsGameCache(max_age_ms=15_000)
    mlb = official_docs_nba_state().model_copy(
        update={"game_id": 10079447, "league_abbreviation": "mlb", "score": "0-0"}
    )
    assert cache.put(mlb) is True
    stored = cache.latest_by_id(10079447)
    assert stored is not None
    assert stored.league_abbreviation == "MLB"
    spl = official_docs_nba_state().model_copy(
        update={"game_id": 99, "league_abbreviation": "spl", "score": "0-0"}
    )
    assert cache.put(spl) is False


def test_subscriber_drops_undocumented_league() -> None:
    cache = SportsGameCache(max_age_ms=15_000)
    bogus = {**OFFICIAL_DOCS_NBA_RAW, "leagueAbbreviation": "EPL", "gameId": 99}
    transport = InjectedFrameTransport([json.dumps(bogus)])
    sub = PublicSportsSubscriber(
        cache,
        config=SportsWsFeedConfig(max_data_age_ms=15_000, ping_interval_s=1, collect_seconds=0.5),
        transport=transport,
    )
    asyncio.run(sub.run(duration_s=0.3, max_prints=1))
    assert cache.latest_by_id(99) is None
    assert sub.prints_accepted == 0


def test_scan_with_injected_sports_transport() -> None:
    cache = SportsGameCache(max_age_ms=15_000)
    # Paper edge: fixture score still official field names.
    frame = {**OFFICIAL_DOCS_NBA_RAW, "score": "110-90"}
    transport = InjectedFrameTransport([json.dumps(frame)])
    cfg = HotflowConfig()
    cfg.feeds.sports_ws.collect_seconds = 1.0
    pipe = PaperPipeline(cfg, sports_source=cache)

    async def _run() -> dict:
        return await pipe.run_scan(
            markets=[demo_sports_nba_market(hot=True)],
            use_network=False,
            attach_sports_subscriber=True,
            sports_subscriber_transport=transport,
        )

    payload = asyncio.run(_run())
    assert payload["accepted"] == 1
    assert payload["results"][0]["sports_state"]["score"] == "110-90"


def test_cli_sports_cache_mock(tmp_path: Path) -> None:
    from typer.testing import CliRunner

    from hotflow.cli import app

    out = tmp_path / "sports.json"
    completed = CliRunner().invoke(app, ["sports-cache", "--mock", "--out", str(out)])
    assert completed.exit_code == 0, completed.output
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["games"]
    leagues = {row["league_abbreviation"] for row in payload["games"]}
    assert "NBA" in leagues
    assert "Soccer" in leagues

    paper = tmp_path / "paper.json"
    completed = CliRunner().invoke(
        app, ["paper-run", "--mock", "--sports-cache", str(out), "--out", str(paper)]
    )
    assert completed.exit_code == 0, completed.output
    report = json.loads(paper.read_text(encoding="utf-8"))
    assert report["cycles"][0]["accepted"] == 3
    sports = report["cycles"][0]["results"][2]
    assert sports["accepted"] is True
    assert sports["sports_model"] == "basketball"


def test_live_sample_is_official_fields_only() -> None:
    from hotflow.marketdata.sports_ws import parse_official_sports_message
    from hotflow.official import SPORTS_DOCUMENTED_LEAGUES

    path = Path("tests/fixtures/sports_ws_live_sample.json")
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["source"] == "live_sports_ws"
    assert payload["informational"] is True
    allowed = {
        "gameId",
        "leagueAbbreviation",
        "homeTeam",
        "awayTeam",
        "status",
        "live",
        "ended",
        "score",
        "period",
        "elapsed",
        "slug",
        "turn",
    }
    game = payload["games"][0]
    assert set(game) <= allowed
    assert game["leagueAbbreviation"] in SPORTS_DOCUMENTED_LEAGUES
    parsed = parse_official_sports_message(game)
    assert parsed is not None
    cache = SportsGameCache(max_age_ms=15_000)
    assert cache.put(parsed) is True


def test_docs_example_fixture_matches_official_schema() -> None:
    path = Path("tests/fixtures/sports_ws_official_docs_example.json")
    raw = json.loads(path.read_text(encoding="utf-8"))
    assert raw == OFFICIAL_DOCS_NBA_RAW
    from hotflow.marketdata.sports_ws import parse_official_sports_message

    parsed = parse_official_sports_message(raw)
    assert parsed is not None
    assert parsed.game_id == 5127839
    assert "-" in (parsed.score or "")


def test_default_sports_subscriber_is_off() -> None:
    cfg = load_config(Path("configs/default.yaml"))
    assert cfg.feeds.sports_ws.subscriber_enabled is False
    assert cfg.feeds.sports_ws.live_public_client is False
    assert cfg.sports.live_public_client is False
    assert cfg.feeds.sports_ws.ping_interval_s == 5.0
    assert cfg.feeds.sports_ws.collect_seconds == 12.0


def test_default_sports_fixtures_documented_leagues_only() -> None:
    from hotflow.official import SPORTS_DOCUMENTED_LEAGUES

    for row in default_sports_cache_fixtures():
        assert row.league_abbreviation in SPORTS_DOCUMENTED_LEAGUES
        assert row.game_id is not None
        assert row.score and "-" in row.score
