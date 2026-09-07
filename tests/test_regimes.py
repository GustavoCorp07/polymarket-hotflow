"""Parte 25 — first-class regime detectors. Missing features → N/A."""

from datetime import UTC, datetime, timedelta
from pathlib import Path

from hotflow.analytics.regimes import (
    Regime,
    classify_crypto,
    detect_crypto,
    detect_regime,
    detect_sports,
    detect_weather,
    strategy_blocked,
)
from hotflow.config import RegimeConfig, RegimeStrategyConfig, load_config
from hotflow.execution.live_gate import live_gates_open
from hotflow.news.engine import NewsEngine
from hotflow.news.item import NewsClass, NewsItem
from hotflow.pipeline import (
    PaperPipeline,
    demo_crypto_window_market,
    demo_market,
    demo_weather_market,
)
from hotflow.reason_codes import ReasonCode
from hotflow.types import SportsGameState, WeatherForecast


def test_default_regimes_config_and_live_frozen() -> None:
    cfg = load_config(Path("configs/default.yaml"))
    assert cfg.trading.mode == "paper"
    assert cfg.regimes.enabled is True
    assert live_gates_open(cfg) is False
    ids = {item.id for item in cfg.portfolio.regimes}
    assert "news_shock" in ids
    assert "near_resolution" in ids


def test_classify_crypto_ttr_still_near_resolution() -> None:
    assert classify_crypto(demo_market(hot=True), ttr_seconds=60) is Regime.NEAR_RESOLUTION


def test_crypto_missing_features_is_na_not_invented() -> None:
    market = demo_market(hot=True)
    market.spread = None
    market.liquidity = None
    market.last_trade_price = None
    market.book = None
    market.resolution.end_date = None
    report = detect_crypto(market)
    assert report.primary is Regime.NOT_AVAILABLE
    assert "spread" in report.missing
    assert report.as_dict()["invented"] is False


def test_crypto_news_shock_from_validated_impact() -> None:
    market = demo_crypto_window_market(symbol="btc/usd", window="5m", market_id="shock-btc")
    report = detect_crypto(
        market,
        ttr_seconds=10_000,
        news={"apply": True, "classification": "official", "relevance": 0.8},
    )
    assert Regime.NEWS_SHOCK in report.labels
    assert report.primary is Regime.NEWS_SHOCK


def test_sports_phases_from_official_period() -> None:
    assert detect_sports(SportsGameState(live=False, ended=False, period=None)).primary is Regime.PRE_GAME
    assert detect_sports(SportsGameState(live=True, period="Q1")).primary is Regime.EARLY_LIVE
    assert detect_sports(SportsGameState(live=True, period="HT")).primary is Regime.MID_GAME
    assert detect_sports(SportsGameState(live=True, period="Q4")).primary is Regime.LATE_GAME
    assert detect_sports(SportsGameState(live=True, period="OT")).primary is Regime.OVERTIME
    missing = detect_sports(SportsGameState(live=True, period=None))
    assert missing.primary is Regime.NOT_AVAILABLE
    assert "period" in missing.missing


def test_weather_near_resolution_and_missing_na() -> None:
    market = demo_weather_market(hot=True)
    near = detect_weather(
        market,
        forecast=WeatherForecast(mean=78.0, std=2.5, source="fixture"),
        ttr_seconds=1_200,
    )
    assert near.primary is Regime.NEAR_RESOLUTION
    blank_market = demo_weather_market(hot=True)
    blank_market.resolution.end_date = None
    report = detect_weather(blank_market, forecast=None, ttr_seconds=None)
    assert report.primary is Regime.NOT_AVAILABLE
    assert "ttr_seconds" in report.missing
    assert "forecast" in report.missing


def test_pipeline_detected_news_shock_scales_crypto_group() -> None:
    cfg = load_config(Path("configs/default.yaml"))
    cfg.risk.cooldown_ms = 0
    cfg.risk.cooldown_after_losses_ms = 0
    for group in cfg.portfolio.groups:
        if group.id == "crypto_short_window":
            group.max_markets = 2
            group.max_exposure = 400.0
    now = datetime.now(UTC)
    engine = NewsEngine(cfg.news)
    for market_id in ("det-btc", "det-eth"):
        engine.ingest(
            NewsItem(
                news_id=f"shock-{market_id}",
                headline="SEC filing names BTC ETH 5m up/down window",
                source_id="sec.gov",
                published_at=now - timedelta(minutes=5),
                market_id=market_id,
                resolution_terms=["btc", "eth", "5m"],
                classification_label=NewsClass.OFFICIAL,
                claimed_p_shift=0.08,
                pre_event_mid=0.41,
                origin="fixture",
            )
        )
    pipe = PaperPipeline(cfg, news_engine=engine)
    btc = demo_crypto_window_market(symbol="btc/usd", window="5m", market_id="det-btc")
    eth = demo_crypto_window_market(symbol="eth/usd", window="5m", market_id="det-eth")
    results = pipe.evaluate_markets([btc, eth], p_info=0.70, now=now)
    assert any(row.get("regime", {}).get("primary") == "news_shock" for row in results)
    skipped = [row for row in results if not row.get("accepted")]
    taken = sum(float((row.get("portfolio") or {}).get("allocated_notional") or 0.0) for row in results)
    assert skipped
    assert skipped[0]["reason"] == ReasonCode.CORRELATED_EXPOSURE
    assert taken <= 200.0 + 1e-6


def test_pipeline_weather_near_resolution_label() -> None:
    cfg = load_config(Path("configs/default.yaml"))
    pipe = PaperPipeline(cfg, use_twap_fixtures=True)
    market = demo_weather_market(hot=True)
    close = (datetime.now(UTC) + timedelta(minutes=20)).strftime("%Y-%m-%dT%H:%M:%SZ")
    market.resolution.end_date = close
    result = pipe.evaluate_market(market)
    assert result.get("regime", {}).get("primary") == "near_resolution"
    assert "near_resolution" in (result.get("regime", {}).get("labels") or [])


def test_regime_disabled_blocks_strategy_not_risk() -> None:
    cfg = load_config(Path("configs/default.yaml"))
    cfg.regimes.strategies["crypto"] = RegimeStrategyConfig(disabled_regimes=["near_resolution"])
    pipe = PaperPipeline(cfg, use_twap_fixtures=True)
    result = pipe.evaluate_market(demo_market(hot=True), p_info=0.70)
    # demo_market TTR is year 2099 — not near_resolution; should still trade
    assert result["accepted"] is True
    cfg.regimes.strategies["crypto"] = RegimeStrategyConfig(disabled_regimes=["normal"])
    pipe2 = PaperPipeline(cfg)
    blocked = pipe2.evaluate_market(demo_market(hot=True), p_info=0.70)
    assert blocked["accepted"] is False
    assert blocked["reason"] == ReasonCode.REGIME_DISABLED
    assert pipe2.broker.orders == {}


def test_regime_overlay_does_not_leak_across_groups() -> None:
    from hotflow.config import PortfolioConfig, RiskConfig
    from hotflow.portfolio.allocator import AllocationCandidate, PortfolioAllocator
    from hotflow.portfolio.correlation import extract_identity

    cfg = PortfolioConfig()
    btc = demo_crypto_window_market(symbol="btc/usd", window="5m", market_id="leak-btc")
    weather = demo_weather_market(hot=True)
    btc_id = extract_identity(btc, extra_labels=("near_resolution",))
    weather_id = extract_identity(weather, extra_labels=("forecast_converging",))
    allocator = PortfolioAllocator(cfg, RiskConfig())
    decisions = allocator.allocate(
        [
            AllocationCandidate(
                market_id=btc.market_id,
                category="crypto",
                intended_notional=200,
                opportunity_score=0.5,
                pnl_velocity=1.0,
                net_edge=0.05,
                liquidity=1000,
                identity=btc_id,
            ),
            AllocationCandidate(
                market_id=weather.market_id,
                category="weather",
                intended_notional=200,
                opportunity_score=0.5,
                pnl_velocity=1.0,
                net_edge=0.05,
                liquidity=1000,
                identity=weather_id,
            ),
        ]
    )
    by_id = {row.market_id: row for row in decisions}
    assert by_id[weather.market_id].action == "TAKE"
    assert by_id[weather.market_id].allocated_notional == 200
    assert "scale=0.5" not in " ".join(by_id[weather.market_id].assumptions)


def test_strategy_blocked_helper() -> None:
    report = detect_regime(demo_market(hot=True), category="crypto", ttr_seconds=60)
    cfg = RegimeConfig()
    cfg.strategies["crypto"] = RegimeStrategyConfig(disabled_regimes=["near_resolution"])
    assert strategy_blocked("crypto", report, cfg)
    assert strategy_blocked("weather", report, cfg) is None
