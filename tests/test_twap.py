from __future__ import annotations

import json
from pathlib import Path

from hotflow.config import FairValueConfig, HotflowConfig, TwapFairValueConfig, load_config
from hotflow.discovery.resolution import parse_twap_resolution
from hotflow.fairvalue.crypto import CryptoFairValue
from hotflow.fairvalue.twap import compute_twap_snapshot, digital_prob_above
from hotflow.marketdata.rtds_twap import FixtureTwapSource, PublicRtdsTwapClient, parse_official_rtds_twap_event
from hotflow.marketdata.twap_fixtures import OFFICIAL_DOCS_EXAMPLE_THIRTY, PAPER_MOCK_BTC_USD_60
from hotflow.official import RTDS_TWAP_60, RTDS_TWAP_WINDOWS, rtds_twap_filter, rtds_twap_subscribe_payload
from hotflow.pipeline import PaperPipeline, demo_market, demo_twap_market
from hotflow.reason_codes import ReasonCode
from hotflow.types import OfficialTwapObservation, Side


def test_twap_math_known_values() -> None:
    p_mid = digital_prob_above(spot=100.0, strike=100.0, time_remaining_s=3600.0, annualized_vol=0.8)
    assert abs(p_mid - 0.5) < 0.02
    p_up = digital_prob_above(spot=110.0, strike=100.0, time_remaining_s=120.0, annualized_vol=0.8)
    assert p_up > 0.99
    p_down = digital_prob_above(spot=90.0, strike=100.0, time_remaining_s=120.0, annualized_vol=0.8)
    assert p_down < 0.01
    expired_up = digital_prob_above(spot=101.0, strike=100.0, time_remaining_s=0.0, annualized_vol=0.8)
    assert expired_up == 1.0
    expired_down = digital_prob_above(spot=99.0, strike=100.0, time_remaining_s=0.0, annualized_vol=0.8)
    assert expired_down == 0.0


def test_resolution_parser_official_windows_only() -> None:
    market_60 = demo_twap_market(window_seconds=60, strike=65000.0)
    spec_60 = parse_twap_resolution(market_60)
    assert spec_60.complete
    assert spec_60.window_seconds == 60
    assert spec_60.symbol == "btc/usd"
    assert spec_60.feed == RTDS_TWAP_60
    assert spec_60.strike == 65000.0
    assert spec_60.opening_reference == 65000.0
    assert spec_60.official_settlement_formula_published is False

    market_30 = demo_twap_market(window_seconds=30, strike=64000.0)
    spec_30 = parse_twap_resolution(market_30)
    assert spec_30.window_seconds == 30
    assert spec_30.complete

    unknown = demo_market(hot=True)
    unknown.question = "Will BTC be up in the next 5-minute crypto window?"
    unknown.raw_gamma = {"description": "Settles on TWAP. No official lookback stated."}
    spec_unknown = parse_twap_resolution(unknown)
    assert spec_unknown.is_twap_market
    assert spec_unknown.window_seconds is None
    assert spec_unknown.complete is False
    assert spec_unknown.skip_reason == ReasonCode.TWAP_WINDOW_UNKNOWN

    both = demo_market(hot=True)
    both.question = "Chainlink 30-second and 60-second TWAP mentioned together for btc/usd above 1"
    spec_both = parse_twap_resolution(both)
    assert spec_both.window_seconds is None
    assert spec_both.skip_reason == ReasonCode.TWAP_WINDOW_UNKNOWN

    no_twap = demo_market(hot=True)
    assert parse_twap_resolution(no_twap).is_twap_market is False


def test_snapshot_from_official_observation() -> None:
    market = demo_twap_market(window_seconds=60, strike=65000.0)
    spec = parse_twap_resolution(market)
    obs = OfficialTwapObservation(symbol="btc/usd", window_seconds=60, value=68000.0, source="fixture")
    snap = compute_twap_snapshot(spec, obs, time_remaining_s=90.0, config=TwapFairValueConfig())
    assert snap.current_twap == 68000.0
    assert snap.projected_twap == 68000.0
    assert snap.distance_to_strike == 3000.0
    assert snap.required_future_price == 65000.0
    assert snap.time_remaining_s == 90.0
    assert snap.probability_of_finish_above > 0.99
    assert snap.probability_of_finish_below < 0.01


def test_parse_official_rtds_payload_and_subscribe_frame() -> None:
    fixture_path = Path("tests/fixtures/rtds_twap_official_sixty.json")
    message = json.loads(fixture_path.read_text(encoding="utf-8"))
    parsed = parse_official_rtds_twap_event(message, source="fixture")
    assert parsed is not None
    assert parsed.window_seconds == 60
    assert parsed.symbol == "btc/usd"
    assert parsed.topic == RTDS_TWAP_60
    assert abs(parsed.value - 65000.5) < 1e-9

    parsed_docs = parse_official_rtds_twap_event(OFFICIAL_DOCS_EXAMPLE_THIRTY, source="fixture")
    assert parsed_docs is not None
    assert parsed_docs.window_seconds == 30

    frame = rtds_twap_subscribe_payload(window_seconds=60, symbol="btc/usd")
    assert frame["action"] == "subscribe"
    assert frame["subscriptions"][0]["topic"] == RTDS_TWAP_60
    assert frame["subscriptions"][0]["filters"] == rtds_twap_filter("btc/usd")
    assert " " not in frame["subscriptions"][0]["filters"]
    assert RTDS_TWAP_WINDOWS == frozenset({30, 60})


def test_optional_public_rtds_client_is_injected_only() -> None:
    sent: list[str] = []

    async def _send(payload: str) -> None:
        sent.append(payload)

    client = PublicRtdsTwapClient(send=_send)
    assert client.optional_live_public is True
    assert client.url.startswith("wss://ws-live-data.polymarket.com")
    frame = client.subscribe_payload(window_seconds=60, symbol="btc/usd")
    assert frame["subscriptions"][0]["topic"] == RTDS_TWAP_60
    obs = client.handle_payload(PAPER_MOCK_BTC_USD_60)
    assert obs is not None
    assert client.latest("btc/usd", 60) is not None
    pong = client.handle_payload("PONG")
    assert pong is None
    assert client.ws.last_pong_ok is True


def test_twap_net_edge_skip_when_net_le_min() -> None:
    market = demo_twap_market(window_seconds=60, strike=65000.0)
    spec = parse_twap_resolution(market)
    obs = OfficialTwapObservation(symbol="btc/usd", window_seconds=60, value=64000.0, source="fixture")
    snap = compute_twap_snapshot(spec, obs, time_remaining_s=60.0)
    edge = CryptoFairValue().evaluate(
        market,
        side=Side.BUY,
        shares=5,
        min_required_edge=0.012,
        config=FairValueConfig(),
        p_info=snap.probability_of_finish_above,
        twap=snap,
    )
    assert edge.skip
    assert edge.reason == ReasonCode.EDGE_TOO_SMALL
    assert edge.current_twap == 64000.0
    assert edge.net_expected_edge <= 0.012


def test_paper_run_mock_exercises_twap_path() -> None:
    cfg = load_config(Path("configs/default.yaml"))
    source = FixtureTwapSource()
    pipe = PaperPipeline(cfg, twap_source=source, use_twap_fixtures=True)
    market = demo_twap_market(hot=True, window_seconds=60, strike=65000.0)
    result = pipe.evaluate_market(market)
    assert result["accepted"] is True
    assert result["reason"] == ReasonCode.OK
    twap = result["twap"]
    assert twap is not None
    assert twap["window_seconds"] == 60
    assert twap["symbol"] == "btc/usd"
    assert twap["current_twap"] == 68000.0
    assert twap["projected_twap"] == 68000.0
    assert twap["required_future_price"] == 65000.0
    assert twap["probability_of_finish_above"] > 0.9
    assert result["edge"]["current_twap"] == 68000.0
    assert any(a.accepted and a.extra.get("twap") for a in pipe.audits)


def test_twap_market_without_observation_skips() -> None:
    cfg = HotflowConfig()
    pipe = PaperPipeline(cfg, twap_source=FixtureTwapSource(observations={}))
    result = pipe.evaluate_market(demo_twap_market(hot=True))
    assert result["accepted"] is False
    assert result["reason"] == ReasonCode.TWAP_OBSERVATION_MISSING


def test_cli_paper_run_mock_twap(tmp_path) -> None:
    from typer.testing import CliRunner

    from hotflow.cli import app

    out = tmp_path / "paper.json"
    completed = CliRunner().invoke(app, ["paper-run", "--mock", "--out", str(out)])
    assert completed.exit_code == 0, completed.output
    payload = json.loads(out.read_text(encoding="utf-8"))
    result = payload["cycles"][0]["results"][0]
    assert result["accepted"] is True
    assert result["twap"]["window_seconds"] in {30, 60}
    assert result["twap"]["current_twap"] is not None


def test_default_config_does_not_invent_twap_window() -> None:
    cfg = load_config(Path("configs/default.yaml"))
    assert "twap_window_seconds" not in cfg.fair_value.crypto.model_fields
    assert cfg.fair_value.crypto.twap.require_parsed_window is True
    assert cfg.feeds.rtds.live_public_client is False
