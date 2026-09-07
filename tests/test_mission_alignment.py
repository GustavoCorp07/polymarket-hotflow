from datetime import UTC, datetime, timedelta

from hotflow.analytics.pnl_velocity import pnl_velocity
from hotflow.analytics.regimes import Regime, classify_crypto
from hotflow.analytics.signal_quality import signal_quality
from hotflow.config import MakerTakerConfig, RiskConfig, ScannerConfig, SizingConfig
from hotflow.discovery.filters import basic_filter_reason
from hotflow.discovery.resolution import parse_resolution
from hotflow.fairvalue.maker_taker import choose_style
from hotflow.features.microstructure import microstructure_features
from hotflow.hotmarket.watchlist import resource_plan
from hotflow.pipeline import demo_market
from hotflow.portfolio.sizing import size_notional
from hotflow.reason_codes import ReasonCode
from hotflow.types import EdgeBreakdown, LiquidityStyle, ResourceTier


def test_resolution_parser_tradeable() -> None:
    meta = parse_resolution({"resolutionSource": "official", "endDate": "2026-12-01T00:00:00Z"})
    assert meta.tradeable
    assert meta.timezone == "UTC"
    unknown = parse_resolution({})
    assert unknown.tradeable is False


def test_basic_filter_low_liquidity() -> None:
    market = demo_market(hot=False)
    reason = basic_filter_reason(market, ScannerConfig(min_liquidity=1000, min_volume_24h=0, max_spread=1.0))
    assert reason == ReasonCode.LOW_LIQUIDITY


def test_microstructure_and_watchlist() -> None:
    market = demo_market(hot=True)
    feats = microstructure_features(market)
    assert feats["mid"] is not None
    assert feats["microprice"] is not None
    assert feats["weighted_imbalance"] is not None
    assert feats["spread_regime"]["invented"] is False
    assert resource_plan(ResourceTier.ULTRA_HOT) == "highest_frequency"
    assert resource_plan(ResourceTier.COLD) == "metadata_only"


def test_capped_kelly_no_martingale_size() -> None:
    edge = EdgeBreakdown(
        p_fair=0.6,
        market_price=0.4,
        raw_edge=0.2,
        fee_per_share=0.01,
        spread_cost=0.01,
        slippage=0.0,
        latency_haircut=0.0,
        adverse_selection=0.0,
        net_expected_edge=0.15,
        confidence=0.7,
    )
    small = size_notional(
        edge, bankroll=10_000, liquidity=1_000, sizing=SizingConfig(), risk=RiskConfig(max_order_notional=250)
    )
    assert 0 < small <= 250
    zero = size_notional(
        edge.model_copy(update={"net_expected_edge": -0.01}),
        bankroll=10_000,
        liquidity=1_000,
        sizing=SizingConfig(),
        risk=RiskConfig(),
    )
    assert zero == 0.0


def test_maker_taker_and_velocity() -> None:
    edge = EdgeBreakdown(
        p_fair=0.7,
        market_price=0.5,
        raw_edge=0.2,
        fee_per_share=0.02,
        spread_cost=0.02,
        slippage=0.01,
        latency_haircut=0.002,
        adverse_selection=0.002,
        fill_penalty=0.001,
        net_expected_edge=0.145,
        confidence=0.6,
    )
    style, ev_m, ev_t = choose_style(edge, MakerTakerConfig())
    assert style in {LiquidityStyle.MAKER, LiquidityStyle.TAKER}
    assert ev_t == edge.net_expected_edge
    assert pnl_velocity(1.0, 2000, 0.25) > 0
    assert classify_crypto(demo_market(hot=True), ttr_seconds=60) is Regime.NEAR_RESOLUTION


def test_signal_quality_shape() -> None:
    from hotflow.config import HotMarketConfig, OpportunityConfig
    from hotflow.hotmarket.opportunity import score_opportunity
    from hotflow.hotmarket.score import score_hot_market
    from hotflow.types import Side

    market = demo_market(hot=True)
    hms = score_hot_market(market, HotMarketConfig())
    edge = EdgeBreakdown(
        p_fair=0.62,
        market_price=0.55,
        raw_edge=0.07,
        fee_per_share=0.01,
        spread_cost=0.01,
        slippage=0.0,
        latency_haircut=0.0,
        adverse_selection=0.0,
        net_expected_edge=0.05,
        confidence=0.6,
    )
    opp = score_opportunity(
        market=market, hms=hms, edge=edge, side=Side.BUY, token_id="t", shares=5, cfg=OpportunityConfig()
    )
    payload = signal_quality(opp, decision="SKIP", reason_codes=["EDGE_TOO_SMALL"], strategy="crypto_updown")
    assert payload["decision"] == "SKIP"
    assert "fair_probability" in payload
    assert payload["reason_codes"] == ["EDGE_TOO_SMALL"]


def test_clock_latency_percentiles() -> None:
    from hotflow.marketdata.clock import LatencyProbe, utc_now

    assert utc_now().tzinfo is not None
    probe = LatencyProbe()
    probe.start("x")
    probe.stop("x")
    probe.start("x")
    probe.stop("x")
    assert probe.percentile("x", 50) is not None
    assert datetime.now(UTC) - timedelta(days=1) < utc_now()
