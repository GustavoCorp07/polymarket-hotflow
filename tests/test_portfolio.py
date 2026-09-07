"""Parte 24 — portfolio allocation and explicit correlation rules."""

from pathlib import Path

from hotflow.backtest.shadow import run_shadow
from hotflow.config import PortfolioConfig, RiskConfig, load_config
from hotflow.execution.live_gate import live_gates_open
from hotflow.pipeline import PaperPipeline, demo_crypto_window_market, demo_market, demo_weather_market
from hotflow.portfolio.allocator import AllocationCandidate, PortfolioAllocator
from hotflow.portfolio.correlation import are_correlated, extract_identity, parse_window_label
from hotflow.reason_codes import ReasonCode


def _candidate(market, *, notional: float, score: float = 0.5, velocity: float = 1.0) -> AllocationCandidate:
    identity = extract_identity(market)
    return AllocationCandidate(
        market_id=market.market_id,
        category=identity.category,
        intended_notional=notional,
        opportunity_score=score,
        pnl_velocity=velocity,
        net_edge=0.05,
        liquidity=float(market.liquidity or 0.0),
        identity=identity,
    )


def test_default_yaml_portfolio_and_live_frozen() -> None:
    cfg = load_config(Path("configs/default.yaml"))
    assert cfg.trading.mode == "paper"
    assert cfg.portfolio.enabled is True
    assert live_gates_open(cfg) is False
    ids = {group.id for group in cfg.portfolio.groups}
    assert {"crypto_short_window", "weather_city", "sports_game", "esports_match"} <= ids


def test_window_parser_does_not_eat_millimeters() -> None:
    assert parse_window_label("less than 75mm of precipitation") is None
    assert parse_window_label("Bitcoin Up or Down 5m") == "5m"
    assert parse_window_label("official 60-second TWAP") == "60s"


def test_explicit_rules_do_not_invent_btc_eth_link() -> None:
    btc = demo_crypto_window_market(symbol="btc/usd", window="5m", market_id="rule-btc")
    eth = demo_crypto_window_market(symbol="eth/usd", window="5m", market_id="rule-eth")
    left = extract_identity(btc)
    right = extract_identity(eth)
    assert left.underlying == "btc/usd"
    assert right.underlying == "eth/usd"
    narrow = PortfolioConfig(
        rules={
            "same_underlying": True,
            "same_category_window": False,
            "tag_overlap": False,
            "yaml_groups": False,
        }
    )
    assert are_correlated(left, right, narrow) is False
    full = PortfolioConfig()
    assert are_correlated(left, right, full) is True


def test_allocator_correlated_crypto_one_skip() -> None:
    btc = demo_crypto_window_market(symbol="btc/usd", window="5m", market_id="alloc-btc")
    eth = demo_crypto_window_market(symbol="eth/usd", window="5m", market_id="alloc-eth")
    allocator = PortfolioAllocator(PortfolioConfig(), RiskConfig())
    decisions = allocator.allocate(
        [
            _candidate(btc, notional=200, score=0.9, velocity=2.0),
            _candidate(eth, notional=200, score=0.4, velocity=0.5),
        ]
    )
    by_id = {row.market_id: row for row in decisions}
    assert by_id["alloc-btc"].action == "TAKE"
    assert by_id["alloc-eth"].action == "SKIP"
    assert by_id["alloc-eth"].reason == ReasonCode.CORRELATED_EXPOSURE
    assert any("crypto_short_window" in item for item in by_id["alloc-eth"].hits + by_id["alloc-eth"].groups)


def test_allocator_uncorrelated_pair_both_take() -> None:
    btc = demo_crypto_window_market(symbol="btc/usd", window="5m", market_id="pair-btc")
    weather = demo_weather_market(hot=True)
    allocator = PortfolioAllocator(PortfolioConfig(), RiskConfig())
    decisions = allocator.allocate(
        [_candidate(btc, notional=200, score=0.6), _candidate(weather, notional=200, score=0.6)]
    )
    assert [row.action for row in decisions] == ["TAKE", "TAKE"]


def test_allocator_downsizes_when_group_has_partial_room() -> None:
    cfg = PortfolioConfig()
    cfg.min_allocate_fraction = 0.10
    for group in cfg.groups:
        if group.id == "crypto_short_window":
            group.max_markets = 2
            group.max_exposure = 300.0
    btc = demo_crypto_window_market(symbol="btc/usd", window="5m", market_id="down-btc")
    eth = demo_crypto_window_market(symbol="eth/usd", window="5m", market_id="down-eth")
    allocator = PortfolioAllocator(cfg, RiskConfig())
    decisions = allocator.allocate(
        [
            _candidate(btc, notional=200, score=0.9),
            _candidate(eth, notional=200, score=0.4),
        ]
    )
    by_id = {row.market_id: row for row in decisions}
    assert by_id["down-btc"].action == "TAKE"
    assert by_id["down-eth"].action == "DOWNSIZE"
    assert by_id["down-eth"].reason == ReasonCode.PORTFOLIO_DOWNSIZED
    assert 0 < by_id["down-eth"].allocated_notional < 200


def test_pipeline_batch_skips_duplicate_crypto() -> None:
    cfg = load_config(Path("configs/default.yaml"))
    cfg.risk.cooldown_ms = 0
    cfg.risk.cooldown_after_losses_ms = 0
    pipe = PaperPipeline(cfg)
    btc = demo_crypto_window_market(symbol="btc/usd", window="5m", market_id="pipe-btc")
    eth = demo_crypto_window_market(symbol="eth/usd", window="5m", market_id="pipe-eth")
    results = pipe.evaluate_markets([btc, eth], p_info=0.70)
    accepted = [row for row in results if row.get("accepted")]
    skipped = [row for row in results if not row.get("accepted")]
    assert len(accepted) == 1
    assert len(skipped) == 1
    assert skipped[0]["reason"] == ReasonCode.CORRELATED_EXPOSURE
    assert skipped[0]["portfolio"]["action"] == "SKIP"


def test_pipeline_uncorrelated_crypto_and_weather_can_both_pass() -> None:
    cfg = load_config(Path("configs/default.yaml"))
    cfg.risk.cooldown_ms = 0
    cfg.risk.cooldown_after_losses_ms = 0
    pipe = PaperPipeline(cfg, use_twap_fixtures=True)
    btc = demo_crypto_window_market(symbol="btc/usd", window="5m", market_id="mix-btc")
    weather = demo_weather_market(hot=True)
    results = pipe.evaluate_markets([btc, weather], p_info=0.70)
    assert all(row.get("accepted") for row in results)
    assert {row.get("market_id") for row in results} == {"mix-btc", "demo-weather-chicago"}


def test_risk_still_vetoes_after_allocator_take() -> None:
    cfg = load_config(Path("configs/default.yaml"))
    cfg.risk.max_spread = 0.001
    pipe = PaperPipeline(cfg)
    result = pipe.evaluate_market(demo_market(hot=True), p_info=0.70)
    assert result["accepted"] is False
    assert result["reason"] == ReasonCode.SPREAD_TOO_LARGE
    assert result.get("portfolio", {}).get("action") == "TAKE"


def test_shadow_batch_records_correlated_skip() -> None:
    cfg = load_config(Path("configs/default.yaml"))
    cfg.risk.cooldown_ms = 0
    cfg.trading.mode = "shadow"
    cfg.trading.shadow = True
    btc = demo_crypto_window_market(symbol="btc/usd", window="5m", market_id="sh-btc")
    eth = demo_crypto_window_market(symbol="eth/usd", window="5m", market_id="sh-eth")
    rows = run_shadow(cfg, [btc, eth], p_info=0.70)
    intents = [row for row in rows if row.get("would_buy") or row.get("would_sell")]
    skips = [row for row in rows if row.get("reason") == ReasonCode.CORRELATED_EXPOSURE]
    assert len(intents) == 1
    assert len(skips) == 1
    assert all(row.get("simulated_fill", {}).get("sent") is not True for row in rows)


def test_fixture_regime_tightens_documented_cap() -> None:
    cfg = PortfolioConfig()
    for group in cfg.groups:
        if group.id == "crypto_short_window":
            group.max_markets = 2
            group.max_exposure = 400.0
    btc = demo_crypto_window_market(symbol="btc/usd", window="5m", market_id="reg-btc", regime="news_shock")
    eth = demo_crypto_window_market(symbol="eth/usd", window="5m", market_id="reg-eth", regime="news_shock")
    allocator = PortfolioAllocator(cfg, RiskConfig())
    decisions = allocator.allocate(
        [_candidate(btc, notional=250, score=0.9), _candidate(eth, notional=250, score=0.8)]
    )
    taken = sum(row.allocated_notional for row in decisions)
    assert taken <= 200.0 + 1e-9
    assert any(row.action == "SKIP" for row in decisions)
