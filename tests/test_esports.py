from __future__ import annotations

import json
from pathlib import Path

from hotflow.config import load_config
from hotflow.discovery.esports_gamma import load_esports_fixture_bundle, redact_market
from hotflow.discovery.resolution import parse_esports_resolution
from hotflow.fairvalue.esports import (
    CS2Adapter,
    Dota2Adapter,
    FixtureEsportsSource,
    LoLAdapter,
    ValorantAdapter,
    esports_adapter_for,
)
from hotflow.official import ESPORTS_DOCUMENTED_TITLES, canonicalize_esports_title
from hotflow.pipeline import (
    PaperPipeline,
    esports_market_from_gamma_fixture,
    gamma_esports_demo_markets,
)
from hotflow.reason_codes import ReasonCode
from hotflow.strategies.esports import EsportsStrategy
from hotflow.types import SportsGameState

FIXTURE_BUNDLE = Path(__file__).parent / "fixtures" / "esports" / "gamma_esports_markets.json"
CS2_DOCS = Path(__file__).parent / "fixtures" / "esports" / "sports_ws_cs2_docs_example.json"


def _by_id(market_id: str) -> dict:
    for row in json.loads(FIXTURE_BUNDLE.read_text(encoding="utf-8"))["markets"]:
        if row["id"] == market_id:
            return row
    raise AssertionError(f"missing {market_id}")


def _spec(market_id: str):
    return parse_esports_resolution(esports_market_from_gamma_fixture(_by_id(market_id)))


def test_official_titles_are_gamma_sports_ids() -> None:
    assert ESPORTS_DOCUMENTED_TITLES == {"cs2", "lol", "dota2", "val"}
    assert canonicalize_esports_title("Valorant") == "val"
    assert canonicalize_esports_title("spl") is None
    assert canonicalize_esports_title("challenger") is None


def test_per_title_adapters_refuse_other_games() -> None:
    assert esports_adapter_for("cs2").title == "cs2"
    assert isinstance(esports_adapter_for("lol"), LoLAdapter)
    assert isinstance(esports_adapter_for("dota2"), Dota2Adapter)
    assert isinstance(esports_adapter_for("val"), ValorantAdapter)
    assert esports_adapter_for("lol-wild-rift") is None
    assert CS2Adapter().accepts_title("lol") is False


def test_bundle_is_public_gamma_shape() -> None:
    bundle = json.loads(FIXTURE_BUNDLE.read_text(encoding="utf-8"))
    assert bundle["source"] == "gamma_public"
    dumped = json.dumps(bundle)
    assert "clobTokenIds" not in dumped
    assert "makerBaseFee" not in dumped
    ids = {row["id"] for row in bundle["markets"]}
    assert {"1923406", "2268716", "2308640", "536506", "693580"} <= ids


def test_redact_drops_tokens() -> None:
    row = redact_market({"id": "1", "question": "q", "clobTokenIds": ["x"], "outcomes": '["A","B"]'})
    assert "clobTokenIds" not in row
    assert row["outcomes"] == ["A", "B"]


def test_dota2_moneyline_from_real_gamma_text() -> None:
    spec = _spec("1923406")
    assert spec.complete is True
    assert spec.game == "dota2"
    assert spec.home_team == "Shizageddon"
    assert spec.away_team == "Nemiga Gaming"
    assert spec.best_of == 3
    assert spec.match_format == "BO3"
    assert spec.source and "dotabuff" in spec.source.lower()
    assert spec.tournament


def test_lol_and_valorant_from_real_gamma_text() -> None:
    lol = _spec("2268716")
    assert lol.complete is True
    assert lol.game == "lol"
    assert lol.home_team == "T1"
    assert lol.away_team == "Kiwoom DRX"
    assert lol.best_of == 3
    assert lol.source and "gol.gg" in lol.source.lower()
    val = _spec("2308640")
    assert val.complete is True
    assert val.game == "val"
    assert val.best_of == 5
    assert val.source and "vlr.gg" in val.source.lower()


def test_cs2_match_source_from_description() -> None:
    spec = _spec("536506")
    assert spec.complete is True
    assert spec.game == "cs2"
    assert spec.home_team == "Falcons"
    assert spec.away_team == "FaZe"
    assert spec.source and "pglesports.com" in spec.source.lower()


def test_lck_season_winner_rules_unknown() -> None:
    spec = _spec("693580")
    assert spec.complete is False
    assert spec.away_team is None
    assert spec.skip_reason == ReasonCode.ESPORTS_RULES_UNKNOWN


def test_paper_skips_complete_match_without_state() -> None:
    cfg = load_config(Path("configs/default.yaml"))
    pipe = PaperPipeline(cfg)
    result = pipe.evaluate_market(esports_market_from_gamma_fixture(_by_id("1923406")))
    assert result["accepted"] is False
    assert result["reason"] == ReasonCode.ESPORTS_STATE_MISSING
    assert result["esports_adapter"] == "dota2"


def test_official_cs2_docs_score_is_not_parsed() -> None:
    raw = json.loads(CS2_DOCS.read_text(encoding="utf-8"))["game"]
    state = SportsGameState(
        game_id=raw["gameId"],
        league_abbreviation=raw["leagueAbbreviation"],
        home_team=raw["homeTeam"],
        away_team=raw["awayTeam"],
        status=raw["status"],
        live=raw["live"],
        ended=raw["ended"],
        score=raw["score"],
        period=raw["period"],
        slug=raw["slug"],
        finished_at=raw["finished_timestamp"],
        source="fixture",
    )
    assert CS2Adapter().p_home_win(
        parse_esports_resolution(esports_market_from_gamma_fixture(_by_id("536506"))),
        state,
    ) is None
    cfg = load_config(Path("configs/default.yaml"))
    src = FixtureEsportsSource([state])
    pipe = PaperPipeline(cfg, esports_source=src)
    market = esports_market_from_gamma_fixture(_by_id("536506"))
    # Teams do not match the docs example; still prove the score string is refused.
    state_matched = state.model_copy(update={"home_team": "Falcons", "away_team": "FaZe"})
    pipe.esports_source = FixtureEsportsSource([state_matched])
    result = pipe.evaluate_market(market)
    assert result["accepted"] is False
    assert result["reason"] == ReasonCode.UNSUPPORTED_STRUCTURE


def test_ended_simple_pair_is_only_documented_score_path() -> None:
    spec = _spec("1923406")
    state = SportsGameState(
        league_abbreviation="dota2",
        home_team="Shizageddon",
        away_team="Nemiga Gaming",
        ended=True,
        live=False,
        status="finished",
        score="2-0",
        source="fixture",
    )
    assert Dota2Adapter().p_home_win(spec, state) == 0.99
    live = state.model_copy(update={"ended": False, "live": True, "status": "running"})
    assert Dota2Adapter().p_home_win(spec, live) is None


def test_gamma_demo_markets_and_strategy() -> None:
    markets = gamma_esports_demo_markets()
    assert any("Dota 2" in m.question for m in markets)
    assert any("Valorant" in m.question for m in markets)
    stub = EsportsStrategy()
    assert stub.experiment_fields()["status"] == "skip_heavy"
    assert stub.experiment_fields()["live_model"] == "none"


def test_load_bundle() -> None:
    assert len(load_esports_fixture_bundle()) >= 4


def test_esports_disabled() -> None:
    cfg = load_config(Path("configs/default.yaml"))
    cfg.esports.enabled = False
    pipe = PaperPipeline(cfg)
    result = pipe.evaluate_market(esports_market_from_gamma_fixture(_by_id("1923406")))
    assert result["reason"] == ReasonCode.CATEGORY_DISABLED
