from datetime import UTC, datetime, timedelta

from hotflow.config import RiskConfig
from hotflow.hotmarket.opportunity import score_opportunity
from hotflow.hotmarket.score import score_hot_market
from hotflow.pipeline import demo_market
from hotflow.reason_codes import ReasonCode
from hotflow.risk.engine import RiskEngine
from hotflow.types import EdgeBreakdown, Side


def _opp(notional: float = 100.0):
    market = demo_market(hot=True)
    from hotflow.config import HotMarketConfig, OpportunityConfig

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
    shares = notional / 0.4
    return score_opportunity(
        market=market,
        hms=hms,
        edge=edge,
        side=Side.BUY,
        token_id="demo-yes",
        shares=shares,
        cfg=OpportunityConfig(),
    )


def test_veto_max_order() -> None:
    engine = RiskEngine(RiskConfig(max_order_notional=50))
    decision = engine.decide(_opp(100), category="crypto", spread=0.02, data_age_ms=10, latency_ms=10)
    assert decision.veto
    assert decision.reason == ReasonCode.RISK_LIMIT


def test_no_trade_is_valid() -> None:
    engine = RiskEngine(RiskConfig())
    # Engine may allow; the pipeline treating no-opportunity as OK is the product rule.
    decision = engine.decide(_opp(10), category="crypto", spread=0.02, data_age_ms=10, latency_ms=10)
    assert decision.allowed is True


def test_martingale_blocked() -> None:
    engine = RiskEngine(RiskConfig(no_martingale=True, max_order_notional=500))
    engine.note_fill(market_id="m1", category="crypto", notional=80.0, pnl_delta=-10.0)
    decision = engine.decide(_opp(120), category="crypto", spread=0.02, data_age_ms=10, latency_ms=10)
    assert decision.veto
    assert decision.reason == ReasonCode.MARTINGALE_BLOCKED


def test_cooldown_veto() -> None:
    engine = RiskEngine(RiskConfig(cooldown_ms=5_000))
    engine.state.last_order_at = datetime.now(UTC)
    now = engine.state.last_order_at + timedelta(milliseconds=100)
    decision = engine.decide(
        _opp(10), category="crypto", spread=0.02, data_age_ms=10, latency_ms=10, now=now
    )
    assert decision.reason == ReasonCode.COOLDOWN
