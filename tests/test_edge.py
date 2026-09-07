from hotflow.config import FairValueConfig
from hotflow.fairvalue.crypto import CryptoFairValue
from hotflow.fairvalue.fees import taker_fee_per_share
from hotflow.pipeline import demo_market
from hotflow.reason_codes import ReasonCode
from hotflow.types import FeeSchedule, Side


def test_official_fee_formula() -> None:
    fees = FeeSchedule(enabled=True, rate=0.04, exponent=1.0, source="test")
    # C=1, p=0.5 → 0.04 * 0.25 = 0.01
    assert taker_fee_per_share(0.5, fees) == 0.01
    fees_off = FeeSchedule(enabled=False, rate=0.99, source="test")
    assert taker_fee_per_share(0.5, fees_off) == 0.0


def test_unknown_fees_skip() -> None:
    market = demo_market(hot=True)
    market.fees = FeeSchedule(source="missing")
    edge = CryptoFairValue().evaluate(
        market,
        side=Side.BUY,
        shares=5,
        min_required_edge=0.01,
        config=FairValueConfig(),
        p_info=0.70,
    )
    assert edge.skip
    assert edge.reason == ReasonCode.UNKNOWN_FEES


def test_net_edge_accounts_for_costs() -> None:
    market = demo_market(hot=True)
    fv = CryptoFairValue()
    edge = fv.evaluate(
        market,
        side=Side.BUY,
        shares=5,
        min_required_edge=0.01,
        config=FairValueConfig(),
        p_info=0.70,
    )
    assert edge.fee_per_share > 0
    assert edge.spread_cost > 0
    expected = (
        edge.raw_edge
        - edge.fee_per_share
        - edge.spread_cost
        - edge.slippage
        - edge.latency_haircut
        - edge.adverse_selection
        - edge.fill_penalty
    )
    assert abs(edge.net_expected_edge - expected) < 1e-9
    assert edge.raw_edge > edge.net_expected_edge


def test_edge_too_small_skips() -> None:
    market = demo_market(hot=True)
    edge = CryptoFairValue().evaluate(
        market,
        side=Side.BUY,
        shares=5,
        min_required_edge=0.50,
        config=FairValueConfig(),
        p_info=0.45,
    )
    assert edge.skip
    assert edge.reason == ReasonCode.EDGE_TOO_SMALL
