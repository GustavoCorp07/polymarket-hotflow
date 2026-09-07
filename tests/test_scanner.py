from hotflow.config import ScannerConfig
from hotflow.discovery.scanner import infer_category, is_eligible, market_from_gamma
from hotflow.pipeline import demo_market


def test_market_from_gamma_parses_official_fields() -> None:
    raw = {
        "id": "703257",
        "conditionId": "0xabc",
        "slug": "example",
        "question": "Will X happen?",
        "clobTokenIds": '["111","222"]',
        "outcomes": '["Yes","No"]',
        "active": True,
        "closed": False,
        "enableOrderBook": True,
        "acceptingOrders": True,
        "liquidityNum": 1500.0,
        "volume24hr": 200.0,
        "bestBid": 0.4,
        "bestAsk": 0.42,
        "spread": 0.02,
        "feesEnabled": True,
        "feeSchedule": {"rate": 0.04, "exponent": 1, "takerOnly": True, "rebateRate": 0.25},
        "orderMinSize": 5,
        "orderPriceMinTickSize": 0.01,
        "resolutionSource": "https://example.invalid",
        "tags": [{"label": "Crypto"}],
        "category": "Crypto",
    }
    market = market_from_gamma(raw)
    assert market.market_id == "703257"
    assert market.token_ids == ["111", "222"]
    assert market.fees.enabled is True
    assert market.fees.rate == 0.04
    assert market.accepting_orders is True
    assert infer_category(market.tags, market.category) == "crypto"
    assert is_eligible(market, ScannerConfig())


def test_ineligible_when_not_accepting() -> None:
    market = demo_market(hot=True)
    market.accepting_orders = False
    assert is_eligible(market, ScannerConfig(require_accepting_orders=True)) is False


def test_dynamic_not_whitelist() -> None:
    cfg = ScannerConfig(include_tags=[])
    weather = demo_market(hot=True)
    weather.tags = ["weather"]
    weather.category = "weather"
    assert is_eligible(weather, cfg)
