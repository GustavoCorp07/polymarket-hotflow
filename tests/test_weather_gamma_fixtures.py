from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from hotflow.config import load_config
from hotflow.discovery.resolution import parse_weather_resolution
from hotflow.discovery.weather_gamma import (
    WEATHER_EVENT_TAG_SLUG,
    load_weather_fixture_bundle,
    redact_market,
    write_weather_fixtures,
)
from hotflow.fairvalue.weather import weather_p_yes
from hotflow.marketdata.weather_fixtures import FixtureWeatherSource, labeled_gamma_weather_forecasts
from hotflow.pipeline import (
    PaperPipeline,
    demo_weather_market,
    gamma_weather_demo_markets,
    weather_market_from_gamma_fixture,
)
from hotflow.reason_codes import ReasonCode
from hotflow.types import WeatherForecast

FIXTURE_BUNDLE = Path(__file__).parent / "fixtures" / "weather" / "gamma_weather_markets.json"


def _bundle() -> dict:
    return json.loads(FIXTURE_BUNDLE.read_text(encoding="utf-8"))


def _by_id(market_id: str) -> dict:
    for row in _bundle()["markets"]:
        if row["id"] == market_id:
            return row
    raise AssertionError(f"missing fixture {market_id}")


def _spec_for(market_id: str):
    return parse_weather_resolution(weather_market_from_gamma_fixture(_by_id(market_id)))


def test_weather_fixture_bundle_is_public_gamma_shape() -> None:
    bundle = _bundle()
    assert bundle["source"] == "gamma_public"
    assert bundle["tag_slug"] == WEATHER_EVENT_TAG_SLUG
    assert bundle["query"]["endpoint"].endswith("/events")
    assert bundle["query"]["params"]["tag_slug"] == "weather"
    ids = {row["id"] for row in bundle["markets"]}
    assert {"2290078", "4238333", "4027989", "678686"} <= ids
    dumped = json.dumps(bundle)
    assert "clobTokenIds" not in dumped
    assert "makerBaseFee" not in dumped
    assert "takerBaseFee" not in dumped
    for row in bundle["markets"]:
        assert row["question"]
        assert row["description"]
        assert "clobTokenIds" not in row


def test_redact_market_drops_non_public_fields() -> None:
    redacted = redact_market(
        {
            "id": "1",
            "question": "q",
            "description": "d",
            "clobTokenIds": ["secret"],
            "makerBaseFee": "0.01",
            "outcomes": '["Yes","No"]',
        },
        event={"id": "e1", "slug": "weather", "title": "Weather", "tags": [{"label": "Weather"}]},
    )
    assert "clobTokenIds" not in redacted
    assert "makerBaseFee" not in redacted
    assert redacted["event_slug"] == "weather"
    assert redacted["outcomes"] == ["Yes", "No"]


def test_jinan_highest_temp_or_below_from_real_gamma_text() -> None:
    spec = _spec_for("2290078")
    assert spec.complete is True
    assert spec.city == "Jinan"
    assert spec.station == "ZSJN"
    assert spec.metric == "highest temperature"
    assert spec.unit and ("C" in spec.unit or "celsius" in spec.unit.lower())
    assert spec.threshold == 15.0
    assert spec.comparison == "at_or_below"
    assert spec.source and "wunderground" in spec.source.lower()
    assert spec.time_window
    assert spec.rounding_rule == "nearest_degree"
    assert spec.timezone is None  # official text has no IANA zone; do not invent one


def test_london_lowest_temp_or_below_from_real_gamma_text() -> None:
    spec = _spec_for("4238333")
    assert spec.complete is True
    assert spec.city == "London"
    assert spec.station == "EGLC"
    assert spec.metric == "lowest temperature"
    assert spec.unit and ("C" in spec.unit or "celsius" in spec.unit.lower())
    assert spec.threshold == 13.0
    assert spec.comparison == "at_or_below"
    assert spec.source and ("weather.gov" in spec.source.lower() or "noaa" in spec.source.lower())
    assert spec.time_window
    assert spec.timezone is None


def test_seoul_precip_less_than_from_real_gamma_text() -> None:
    spec = _spec_for("4027989")
    assert spec.complete is True
    assert spec.city == "Seoul"
    assert spec.metric and "precip" in spec.metric
    assert spec.unit and spec.unit.lower() == "mm"
    assert spec.threshold == 75.0
    assert spec.comparison == "less_than"
    assert spec.source and "korea meteorological administration" in spec.source.lower()
    assert spec.time_window
    assert spec.rounding_rule == "1_decimal"


def test_hottest_year_rules_unknown_from_real_gamma_text() -> None:
    spec = _spec_for("678686")
    assert spec.complete is False
    assert spec.city is None
    assert spec.station is None
    assert spec.threshold is None
    assert spec.skip_reason == ReasonCode.WEATHER_RULES_UNKNOWN


def test_weather_p_yes_honors_or_below_and_labeled_fixture() -> None:
    spec = _spec_for("2290078")
    inverted = weather_p_yes(spec, WeatherForecast(p_above_threshold=0.20, source="fixture"))
    assert inverted == 0.80
    labeled = weather_p_yes(spec, WeatherForecast(p_yes=0.77, source="fixture"))
    assert labeled == 0.77


def test_labeled_gamma_forecasts_are_fixtures_not_live_nws() -> None:
    rows = labeled_gamma_weather_forecasts()
    assert rows["jinan"].source == "fixture"
    assert rows["london"].source == "fixture"
    assert rows["seoul"].source == "fixture"
    assert all(item.source == "fixture" for item in rows.values())


def test_load_weather_fixture_bundle_helper() -> None:
    rows = load_weather_fixture_bundle(FIXTURE_BUNDLE.parent)
    assert len(rows) >= 4


def test_gamma_weather_demo_markets_use_official_text() -> None:
    markets = gamma_weather_demo_markets()
    questions = {m.question for m in markets}
    assert any("Jinan" in q for q in questions)
    assert any("London" in q for q in questions)
    assert any("Seoul" in q for q in questions)
    assert any("hottest year" in q for q in questions)


def test_paper_weather_accepts_distinct_gamma_fixtures() -> None:
    cfg = load_config(Path("configs/default.yaml"))
    cfg.risk.cooldown_ms = 0
    cfg.risk.cooldown_after_losses_ms = 0
    pipe = PaperPipeline(cfg, use_twap_fixtures=True)
    accepted: dict[str, str] = {}
    skipped: dict[str, str] = {}
    for market in gamma_weather_demo_markets():
        result = pipe.evaluate_market(market)
        if result["accepted"]:
            assert result["weather_spec"]["complete"] is True
            assert result["weather_forecast"]["source"] == "fixture"
            assert result["forecast_role"] == "feature_only"
            accepted[market.market_id] = market.question
        else:
            skipped[market.market_id] = str(result.get("reason") or "")
    assert "2290078" in accepted
    assert "4238333" in accepted
    assert "4027989" in accepted
    assert skipped.get("678686") == ReasonCode.WEATHER_RULES_UNKNOWN


def test_missing_forecast_skips_with_reason() -> None:
    cfg = load_config(Path("configs/default.yaml"))
    pipe = PaperPipeline(cfg, weather_source=FixtureWeatherSource())
    result = pipe.evaluate_market(demo_weather_market(hot=True))
    assert result["accepted"] is False
    assert result["reason"] == ReasonCode.WEATHER_FORECAST_MISSING


def test_cli_weather_fixtures_writes_without_network(tmp_path: Path) -> None:
    rows = load_weather_fixture_bundle()
    path = write_weather_fixtures(rows, tmp_path)
    assert path.is_file()
    copied = json.loads(path.read_text(encoding="utf-8"))
    assert copied["tag_slug"] == "weather"
    assert copied["markets"]


def test_cli_weather_fixtures_command_uses_injected_collect(tmp_path: Path, monkeypatch) -> None:
    from hotflow import cli as cli_mod
    from hotflow.discovery import weather_gamma as wg

    async def _fake_collect(**kwargs):
        dest = kwargs["directory"]
        path = write_weather_fixtures(load_weather_fixture_bundle(), dest)
        return {
            "ok": True,
            "source": "gamma",
            "tag_slug": "weather",
            "scanned": 4,
            "saved": 4,
            "path": str(path),
        }

    monkeypatch.setattr(wg, "collect_weather_fixtures", _fake_collect)
    monkeypatch.setattr("hotflow.discovery.weather_gamma.collect_weather_fixtures", _fake_collect)
    runner = CliRunner()
    result = runner.invoke(cli_mod.app, ["weather-fixtures", "--out", str(tmp_path)])
    assert result.exit_code == 0, result.output
    assert "weather-fixtures" in result.output
    assert (tmp_path / "gamma_weather_markets.json").is_file()


def test_cli_paper_run_mock_includes_gamma_weather_fixtures(tmp_path: Path) -> None:
    from hotflow.cli import app

    runner = CliRunner()
    out = tmp_path / "paper.json"
    result = runner.invoke(app, ["paper-run", "--mock", "--out", str(out)])
    assert result.exit_code == 0, result.output
    payload = json.loads(out.read_text(encoding="utf-8"))
    results = payload["cycles"][0]["results"]
    questions = [row.get("question") or "" for row in results]
    assert any("Jinan" in q for q in questions)
    assert any("London" in q for q in questions)
    assert any("Seoul" in q for q in questions)
    weather_ok = [
        row
        for row in results
        if row.get("accepted") and row.get("weather_forecast")
    ]
    assert len(weather_ok) >= 3
    assert all(row["weather_forecast"]["source"] == "fixture" for row in weather_ok)
    assert all(row.get("forecast_role") == "feature_only" for row in weather_ok)
    hottest = next(row for row in results if "hottest year" in (row.get("question") or ""))
    assert hottest["accepted"] is False
    assert hottest["reason"] == ReasonCode.WEATHER_RULES_UNKNOWN
