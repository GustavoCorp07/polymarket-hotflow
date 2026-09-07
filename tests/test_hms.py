from hotflow.config import HotMarketConfig
from hotflow.hotmarket.score import score_hot_market, tier_for
from hotflow.pipeline import demo_market
from hotflow.types import ResourceTier


def test_hms_hot_vs_cold() -> None:
    cfg = HotMarketConfig()
    hot = score_hot_market(demo_market(hot=True), cfg)
    cold = score_hot_market(demo_market(hot=False), cfg)
    assert 0 <= cold.score <= 100
    assert 0 <= hot.score <= 100
    assert hot.score > cold.score
    assert hot.tier in {ResourceTier.HOT, ResourceTier.ULTRA_HOT, ResourceTier.WARM}


def test_tiers_thresholds() -> None:
    cfg = HotMarketConfig()
    assert tier_for(10, cfg) is ResourceTier.COLD
    assert tier_for(30, cfg) is ResourceTier.WARM
    assert tier_for(55, cfg) is ResourceTier.HOT
    assert tier_for(80, cfg) is ResourceTier.ULTRA_HOT


def test_closed_book_penalizes_score() -> None:
    cfg = HotMarketConfig()
    market = demo_market(hot=True)
    market.accepting_orders = False
    market.enable_order_book = False
    closed = score_hot_market(market, cfg)
    open_m = score_hot_market(demo_market(hot=True), cfg)
    assert closed.score < open_m.score
    assert closed.components["book_open"] == 0.0
