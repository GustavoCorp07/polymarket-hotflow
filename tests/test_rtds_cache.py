from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from pydantic import ValidationError

from hotflow.config import HotflowConfig, RtdsFeedConfig, load_config
from hotflow.marketdata.rtds_subscriber import InjectedFrameTransport, PublicRtdsSubscriber
from hotflow.marketdata.twap_cache import TwapPrintCache, observation_status
from hotflow.marketdata.twap_fixtures import PAPER_MOCK_BTC_USD_60, default_paper_fixtures
from hotflow.official import RTDS_TWAP_30, RTDS_TWAP_60, rtds_twap_subscribe_documented, rtds_twap_subscribe_payload
from hotflow.pipeline import PaperPipeline, demo_twap_market
from hotflow.reason_codes import ReasonCode
from hotflow.types import OfficialTwapObservation


def _live_frame(*, value: float = 68000.0, window: int = 60) -> dict:
    now_ms = int(datetime.now(UTC).timestamp() * 1000)
    topic = RTDS_TWAP_60 if window == 60 else RTDS_TWAP_30
    return {
        "topic": topic,
        "type": "update",
        "timestamp": now_ms,
        "payload": {
            "symbol": "btc/usd",
            "value": value,
            "full_accuracy_value": str(int(value * (10**18))),
            "timestamp": now_ms,
            "window_s": window,
        },
    }


def _fresh_btc_60(*, value: float = 68000.0) -> OfficialTwapObservation:
    return OfficialTwapObservation(
        symbol="btc/usd",
        window_seconds=60,
        value=value,
        source="fixture",
        observed_at=datetime.now(UTC),
        topic=RTDS_TWAP_60,
    )


def test_cache_accepts_official_and_rejects_invented() -> None:
    cache = TwapPrintCache(max_age_ms=10_000)
    assert cache.put(_fresh_btc_60()) is True
    assert cache.latest("btc/usd", 60) is not None
    invented_window = OfficialTwapObservation(symbol="btc/usd", window_seconds=45, value=1.0, source="fixture")
    invented_symbol = OfficialTwapObservation(symbol="doge/usd", window_seconds=60, value=1.0, source="fixture")
    assert cache.put(invented_window) is False
    assert cache.put(invented_symbol) is False
    assert cache.latest("doge/usd", 60) is None


def test_cache_persist_and_load(tmp_path: Path) -> None:
    path = tmp_path / "cache.json"
    cache = TwapPrintCache(max_age_ms=10_000, path=path, persist=True)
    cache.put(_fresh_btc_60())
    assert path.exists()
    loaded = TwapPrintCache.from_path(path, max_age_ms=10_000)
    assert loaded.latest("btc/usd", 60) is not None
    assert loaded.latest("btc/usd", 60).value == 68000.0


def test_freshness_missing_and_stale() -> None:
    assert observation_status(None, max_age_ms=1000) == "missing"
    stale = _fresh_btc_60().model_copy(update={"observed_at": datetime.now(UTC) - timedelta(seconds=30)})
    assert observation_status(stale, max_age_ms=1000) == "stale"
    assert observation_status(_fresh_btc_60(), max_age_ms=10_000) == "fresh"


def test_cache_hit_feeds_fair_value() -> None:
    cache = TwapPrintCache(max_age_ms=10_000)
    cache.put(_fresh_btc_60())
    pipe = PaperPipeline(HotflowConfig(), twap_source=cache)
    result = pipe.evaluate_market(demo_twap_market(hot=True))
    assert result["accepted"] is True
    assert result["twap"]["current_twap"] == 68000.0
    assert result["twap"]["source"] == "fixture"


def test_stale_cache_skips_without_inventing() -> None:
    cache = TwapPrintCache(max_age_ms=500)
    old = _fresh_btc_60().model_copy(update={"observed_at": datetime.now(UTC) - timedelta(seconds=5)})
    cache.put(old)
    pipe = PaperPipeline(HotflowConfig(), twap_source=cache)
    # Pipeline uses config.feeds.rtds.max_data_age_ms (10000 default) — override config.
    pipe.config.feeds.rtds.max_data_age_ms = 500
    result = pipe.evaluate_market(demo_twap_market(hot=True))
    assert result["accepted"] is False
    assert result["reason"] == ReasonCode.TWAP_OBSERVATION_STALE


def test_missing_cache_skips() -> None:
    pipe = PaperPipeline(HotflowConfig(), twap_source=TwapPrintCache(max_age_ms=10_000))
    result = pipe.evaluate_market(demo_twap_market(hot=True))
    assert result["accepted"] is False
    assert result["reason"] == ReasonCode.TWAP_OBSERVATION_MISSING


def test_subscriber_ingests_mocked_frames_no_network() -> None:
    cache = TwapPrintCache(max_age_ms=10_000)
    transport = InjectedFrameTransport([json.dumps(PAPER_MOCK_BTC_USD_60)])
    cfg = RtdsFeedConfig(max_data_age_ms=10_000, ping_interval_s=5, collect_seconds=1.0)
    sub = PublicRtdsSubscriber(cache, config=cfg, transport=transport)

    async def _run() -> int:
        return await sub.run(max_prints=1, duration_s=1.0)

    prints = asyncio.run(_run())
    assert prints == 1
    assert cache.latest("btc/usd", 60) is not None
    assert any("crypto_prices_twap" in item for item in transport.sent)
    assert sub.optional_live_public is True


def test_subscriber_heartbeat_and_reconnect() -> None:
    cache = TwapPrintCache(max_age_ms=10_000)
    transport = InjectedFrameTransport()
    transport.push_disconnect()
    transport.push(json.dumps(PAPER_MOCK_BTC_USD_60))
    cfg = RtdsFeedConfig(
        max_data_age_ms=10_000,
        ping_interval_s=1,
        reconnect_max_backoff_s=0.01,
        collect_seconds=2.0,
    )
    sub = PublicRtdsSubscriber(cache, config=cfg, transport=transport)

    async def _run() -> int:
        return await sub.run(max_prints=1, duration_s=2.0)

    asyncio.run(_run())
    assert sub.reconnects >= 1
    assert cache.latest("btc/usd", 60) is not None
    assert any(item == "PING" or "subscribe" in item for item in transport.sent)


def test_subscriber_heartbeat_on_idle() -> None:
    cache = TwapPrintCache(max_age_ms=10_000)
    transport = InjectedFrameTransport()
    cfg = RtdsFeedConfig(max_data_age_ms=10_000, ping_interval_s=0.05, collect_seconds=0.16)
    sub = PublicRtdsSubscriber(cache, config=cfg, transport=transport)

    async def _run() -> int:
        return await sub.run(duration_s=0.16)

    asyncio.run(_run())
    assert transport.sent.count("PING") >= 1


def test_subscriber_drops_undocumented_symbol() -> None:
    cache = TwapPrintCache(max_age_ms=10_000)
    bogus = {
        "topic": RTDS_TWAP_60,
        "type": "update",
        "payload": {"symbol": "doge/usd", "value": 0.1, "window_s": 60, "timestamp": 1},
    }
    transport = InjectedFrameTransport([json.dumps(bogus)])
    sub = PublicRtdsSubscriber(
        cache,
        config=RtdsFeedConfig(max_data_age_ms=10_000, ping_interval_s=1, collect_seconds=0.5),
        transport=transport,
    )
    asyncio.run(sub.run(duration_s=0.3, max_prints=1))
    assert cache.latest("doge/usd", 60) is None
    assert sub.prints_accepted == 0


def test_scan_with_injected_transport_then_fair_value() -> None:
    cache = TwapPrintCache(max_age_ms=10_000)
    transport = InjectedFrameTransport([json.dumps(_live_frame())])
    cfg = HotflowConfig()
    cfg.feeds.rtds.collect_seconds = 1.0
    pipe = PaperPipeline(cfg, twap_source=cache)

    async def _run() -> dict:
        return await pipe.run_scan(
            markets=[demo_twap_market(hot=True)],
            use_network=False,
            attach_subscriber=True,
            subscriber_transport=transport,
        )

    payload = asyncio.run(_run())
    assert payload["accepted"] == 1
    assert payload["results"][0]["twap"]["current_twap"] == 68000.0


def test_cli_rtds_cache_mock(tmp_path: Path) -> None:
    from typer.testing import CliRunner

    from hotflow.cli import app

    out = tmp_path / "cache.json"
    completed = CliRunner().invoke(app, ["rtds-cache", "--mock", "--out", str(out)])
    assert completed.exit_code == 0, completed.output
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["prints"]
    symbols = {(row["symbol"], row["window_seconds"]) for row in payload["prints"]}
    assert ("btc/usd", 60) in symbols

    paper = tmp_path / "paper.json"
    completed = CliRunner().invoke(
        app, ["paper-run", "--mock", "--twap-cache", str(out), "--out", str(paper)]
    )
    assert completed.exit_code == 0, completed.output
    report = json.loads(paper.read_text(encoding="utf-8"))
    assert report["cycles"][0]["accepted"] == 1


def test_subscribe_documented_topics_only() -> None:
    frame = rtds_twap_subscribe_documented()
    topics = {sub["topic"] for sub in frame["subscriptions"]}
    assert topics == {RTDS_TWAP_30, RTDS_TWAP_60}
    with pytest.raises(ValueError):
        rtds_twap_subscribe_payload(window_seconds=60, symbol="doge/usd")
    with pytest.raises(ValueError):
        rtds_twap_subscribe_payload(window_seconds=45)
    with pytest.raises(ValidationError):
        RtdsFeedConfig(subscribe_windows=[45])
    with pytest.raises(ValidationError):
        RtdsFeedConfig(subscribe_symbols=["doge/usd"])


def test_default_rtds_subscriber_is_off() -> None:
    cfg = load_config(Path("configs/default.yaml"))
    assert cfg.feeds.rtds.subscriber_enabled is False
    assert cfg.feeds.rtds.live_public_client is False
    assert cfg.feeds.rtds.subscribe_windows == [30, 60]


def test_default_paper_fixtures_are_official_symbols() -> None:
    rows = default_paper_fixtures()
    assert ("btc/usd", 60) in rows
    assert ("btc/usd", 30) in rows
