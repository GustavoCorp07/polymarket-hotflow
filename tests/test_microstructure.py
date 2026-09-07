"""Parte 45 — L2 microstructure from existing book fixtures. No invented prints."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from hotflow.analytics.signal_quality import signal_quality
from hotflow.backtest.events import FixtureEventSource, order_book_from_payload
from hotflow.config import MicrostructureConfig, ScannerConfig, load_config
from hotflow.discovery.filters import basic_filter_reason
from hotflow.execution.live_gate import live_gates_open
from hotflow.features.microstructure import (
    book_slope,
    compact_microstructure,
    depth_convexity,
    imbalance,
    intensity_from_events,
    microstructure_features,
    price_impact,
    spread_regime,
    weighted_imbalance,
)
from hotflow.hotmarket.opportunity import score_opportunity
from hotflow.hotmarket.score import score_hot_market
from hotflow.pipeline import PaperPipeline, demo_market
from hotflow.reason_codes import ReasonCode
from hotflow.risk.engine import RiskEngine
from hotflow.types import BookLevel, EdgeBreakdown, MarketRecord, OrderBook, Side

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "backtest"
CRYPTO = FIXTURE_DIR / "crypto_book_trade.json"
LIVE = FIXTURE_DIR / "clob_book_live_sample.json"
SYNTH = FIXTURE_DIR / "crypto_longer_synthetic.json"


def _book_from_fixture(path: Path, index: int = 0) -> OrderBook:
    events = [row for row in FixtureEventSource(path).events() if row.kind == "book"]
    assert events, f"no book events in {path}"
    event = events[index]
    return order_book_from_payload(event.payload, token_id="fixture-yes", ts=event.ts)


def _market_with_book(book: OrderBook, *, market_id: str = "micro-fix") -> MarketRecord:
    market = demo_market(hot=True)
    market.market_id = market_id
    market.book = book
    market.best_bid = book.best_bid
    market.best_ask = book.best_ask
    market.spread = book.spread
    market.tick_size = book.tick_size or market.tick_size
    return market


def test_yaml_defaults_and_live_gates_frozen() -> None:
    cfg = load_config(Path("configs/default.yaml"))
    assert cfg.trading.mode == "paper"
    assert live_gates_open(cfg) is False
    assert cfg.microstructure.depth_levels == 5
    assert cfg.microstructure.min_top_depth == 0.0
    assert cfg.microstructure.max_impact is None


def test_demo_hot_book_core_and_weighted() -> None:
    market = demo_market(hot=True)
    feats = microstructure_features(market)
    assert feats["mid"] == 0.41
    assert feats["spread"] == 0.02
    assert feats["microprice"] is not None
    assert feats["imbalance"] is not None
    assert feats["weighted_imbalance"] is not None
    assert feats["bid_depth"] == 190.0
    assert feats["ask_depth"] == 200.0
    assert feats["invented"] is False
    # Same two-level sizes: L1 imbalance equals decaying weighted.
    assert abs(float(feats["imbalance"]) - float(feats["weighted_imbalance"])) < 1e-9
    assert feats["spread_regime"]["label"] == "normal"
    assert feats["spread_regime"]["vs"] == "config"
    assert feats["spread_regime"]["invented"] is False
    assert feats["intensity"]["quote_intensity"] is None
    assert "order_flow_imbalance" in feats["not_available"]
    assert "trade_intensity" in feats["not_available"]


def test_weighted_imbalance_uses_deeper_size() -> None:
    book = OrderBook(
        token_id="w",
        bids=[BookLevel(price=0.50, size=10.0), BookLevel(price=0.49, size=200.0)],
        asks=[BookLevel(price=0.51, size=10.0), BookLevel(price=0.52, size=10.0)],
    )
    l1 = imbalance(book)
    deep = weighted_imbalance(book, levels=2, decay=0.70)
    assert l1 is not None and abs(l1) < 1e-9
    assert deep is not None and deep > 0.4


def test_slope_and_convexity_definitions() -> None:
    # Bids: 100 at 0.40, 20 at 0.30 — size piled at touch, large price walk.
    book = OrderBook(
        token_id="s",
        bids=[BookLevel(price=0.40, size=100.0), BookLevel(price=0.30, size=20.0)],
        asks=[BookLevel(price=0.42, size=20.0), BookLevel(price=0.52, size=100.0)],
        tick_size=0.01,
    )
    bid_s, ask_s = book_slope(book, levels=2)
    assert bid_s is not None and ask_s is not None
    mid = 0.41
    assert abs(bid_s - (120.0 / (mid - 0.30))) < 1e-9
    assert abs(ask_s - (120.0 / (0.52 - mid))) < 1e-9
    bid_c, ask_c = depth_convexity(book, levels=2)
    assert bid_c is not None and bid_c < 0  # more size near
    assert ask_c is not None and ask_c > 0  # more size far
    one = OrderBook(token_id="one", bids=[BookLevel(price=0.4, size=1.0)], asks=[BookLevel(price=0.5, size=1.0)])
    assert book_slope(one, levels=5) == (None, None)
    assert depth_convexity(one, levels=5) == (None, None)


def test_gaps_on_live_clob_sample() -> None:
    book = _book_from_fixture(LIVE, 0)
    assert len(book.bids) >= 10
    market = _market_with_book(book, market_id="live-clob")
    market.tick_size = 0.001
    feats = microstructure_features(market, MicrostructureConfig(gap_multiple=2.0))
    assert feats["tick"] in {0.001, book.tick_size}
    assert feats["bid_depth"] is not None and feats["bid_depth"] > 0
    assert feats["ask_depth"] is not None and feats["ask_depth"] > 0
    assert feats["max_bid_gap"] is not None and feats["max_bid_gap"] >= 0.002
    assert int(feats["bid_gap_count"] or 0) >= 1
    assert feats["impact_buy"] is not None
    assert feats["spread_regime"]["invented"] is False


def test_crypto_book_trade_and_synthetic_books() -> None:
    crypto_book = _book_from_fixture(CRYPTO, 0)
    synth_book = _book_from_fixture(SYNTH, 0)
    crypto = microstructure_features(_market_with_book(crypto_book, market_id="bt-crypto-book-trade"))
    synth = microstructure_features(_market_with_book(synth_book, market_id="bt-crypto-longer-synthetic"))
    assert crypto["microprice"] is not None
    assert synth["microprice"] is not None
    assert crypto["bid_slope"] is not None
    assert synth["weighted_imbalance"] is not None


def test_vwap_impact_walk_and_exhaustion() -> None:
    market = demo_market(hot=True)
    assert market.book is not None
    small = price_impact(market.book, notional=20.0)
    assert small["exhausted_buy"] is False
    assert small["impact_buy"] is not None and small["impact_buy"] >= 0
    huge = price_impact(market.book, notional=10_000.0)
    assert huge["exhausted_buy"] is True
    assert huge["buy_vwap"] is not None


def test_spread_regime_config_vs_recent_never_invented() -> None:
    cfg = MicrostructureConfig(spread_tight=0.015, spread_wide=0.06, min_history=3)
    missing = spread_regime(None, cfg)
    assert missing["label"] == "N/A"
    assert missing["invented"] is False
    tight = spread_regime(0.01, cfg)
    assert tight["label"] == "tight" and tight["vs"] == "config"
    wide = spread_regime(0.09, cfg, recent_spreads=[0.02])  # history too short
    assert wide["vs"] == "config" and wide["invented"] is False
    vs_hist = spread_regime(0.04, cfg, recent_spreads=[0.02, 0.02, 0.02])
    assert vs_hist["vs"] == "recent_median"
    assert vs_hist["label"] == "wide"
    assert vs_hist["invented"] is False


def test_intensity_requires_event_stream() -> None:
    empty = intensity_from_events(None)
    assert empty["quote_intensity"] is None
    assert empty["invented"] is False
    src = FixtureEventSource(CRYPTO)
    rows = [{"ts": ev.ts, "kind": ev.kind} for ev in src.events() if ev.kind in {"book", "trade"}]
    now = datetime(2026, 4, 1, 0, 0, 6, tzinfo=UTC)
    windowed = intensity_from_events(rows, now=now, window_s=60.0)
    assert windowed["quote_count"] >= 2
    assert windowed["quote_intensity"] is not None
    assert windowed["trade_count"] == 0
    assert windowed["trade_intensity"] is None
    later = datetime(2026, 4, 1, 0, 0, 13, tzinfo=UTC)
    with_trade = intensity_from_events(rows, now=later, window_s=60.0)
    assert with_trade["trade_count"] >= 1
    assert with_trade["trade_intensity"] is not None


def test_filter_uses_book_spread_when_gamma_missing() -> None:
    market = demo_market(hot=False)
    market.spread = None
    assert market.book is not None
    reason = basic_filter_reason(market, ScannerConfig(min_liquidity=0, min_volume_24h=0, max_spread=0.10))
    assert reason == ReasonCode.SPREAD_TOO_LARGE


def test_optional_depth_impact_risk_veto() -> None:
    from hotflow.config import HotMarketConfig, OpportunityConfig, RiskConfig

    market = demo_market(hot=True)
    hms = score_hot_market(market, HotMarketConfig())
    edge = EdgeBreakdown(
        p_fair=0.6,
        market_price=0.4,
        raw_edge=0.2,
        fee_per_share=0.01,
        spread_cost=0.01,
        slippage=0.0,
        latency_haircut=0.0,
        adverse_selection=0.0,
        net_expected_edge=0.18,
        confidence=0.6,
    )
    opp = score_opportunity(
        market=market,
        hms=hms,
        edge=edge,
        side=Side.BUY,
        token_id="demo-yes",
        shares=10,
        cfg=OpportunityConfig(),
    )
    engine = RiskEngine(RiskConfig())
    ok = engine.decide(opp, category="crypto", spread=0.02, data_age_ms=10, latency_ms=10)
    assert ok.allowed is True
    thin = engine.decide(
        opp,
        category="crypto",
        spread=0.02,
        data_age_ms=10,
        latency_ms=10,
        bid_depth=1.0,
        ask_depth=1.0,
        min_top_depth=50.0,
    )
    assert thin.veto and thin.reason == ReasonCode.LOW_LIQUIDITY
    hit = engine.decide(
        opp,
        category="crypto",
        spread=0.02,
        data_age_ms=10,
        latency_ms=10,
        book_impact=0.05,
        max_book_impact=0.02,
    )
    assert hit.veto and hit.reason == ReasonCode.SLIPPAGE_TOO_HIGH


def test_pipeline_attaches_micro_and_signal_quality() -> None:
    cfg = load_config(Path("configs/default.yaml"))
    pipe = PaperPipeline(cfg)
    result = pipe.evaluate_market(demo_market(hot=True), p_info=0.70)
    assert result["accepted"] is True
    micro = result["microstructure"]
    assert micro["microprice"] is not None
    assert micro["weighted_imbalance"] is not None
    assert micro["spread_regime"]["invented"] is False
    audits = [row for row in pipe.audits if row.accepted]
    assert audits
    quality = audits[-1].extra.get("signal") or {}
    assert quality["decision"] == "TRADE"
    assert "microstructure" in quality
    assert "fair_probability" in quality


def test_pipeline_intensity_from_fixture_events() -> None:
    cfg = load_config(Path("configs/default.yaml"))
    pipe = PaperPipeline(cfg)
    book = _book_from_fixture(CRYPTO, 0)
    market = _market_with_book(book, market_id="bt-crypto-book-trade")
    events = FixtureEventSource(CRYPTO).events()
    rows = [{"ts": ev.ts, "kind": ev.kind} for ev in events if ev.kind in {"book", "trade"}]
    now = datetime(2026, 4, 1, 0, 0, 6, tzinfo=UTC)
    result = pipe.evaluate_market(market, p_info=0.70, now=now, micro_events=rows)
    assert "microstructure" in result
    intensity = result["microstructure"]["intensity"]
    assert intensity["quote_intensity"] is not None
    assert intensity["invented"] is False


def test_compact_audit_omits_full_book() -> None:
    feats = microstructure_features(demo_market(hot=True))
    compact = compact_microstructure(feats)
    blob = json.dumps(compact)
    assert "bids" not in blob
    assert "token_id" not in blob
    assert "spread_regime" in compact


def test_signal_quality_keeps_parte46_keys() -> None:
    from hotflow.config import HotMarketConfig, OpportunityConfig

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
    payload = signal_quality(
        opp,
        decision="SKIP",
        reason_codes=["EDGE_TOO_SMALL"],
        strategy="crypto_updown",
        extras={"microstructure": microstructure_features(market)},
    )
    assert payload["decision"] == "SKIP"
    assert payload["reason_codes"] == ["EDGE_TOO_SMALL"]
    assert payload["microstructure"]["invented"] is False
