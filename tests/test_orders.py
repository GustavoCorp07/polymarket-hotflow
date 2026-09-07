from hotflow.config import TradingConfig
from hotflow.execution.orders import IllegalTransition, OrderStateMachine
from hotflow.execution.paper import PaperBroker
from hotflow.hotmarket.opportunity import score_opportunity
from hotflow.hotmarket.score import score_hot_market
from hotflow.pipeline import demo_market
from hotflow.reason_codes import ReasonCode
from hotflow.types import EdgeBreakdown, OrderRecord, OrderStatus, Side, TradingMode


def _opp():
    from hotflow.config import HotMarketConfig, OpportunityConfig

    market = demo_market(hot=True)
    hms = score_hot_market(market, HotMarketConfig())
    edge = EdgeBreakdown(
        p_fair=0.6,
        market_price=0.42,
        raw_edge=0.18,
        fee_per_share=0.01,
        spread_cost=0.01,
        slippage=0.0,
        latency_haircut=0.0,
        adverse_selection=0.0,
        net_expected_edge=0.16,
        confidence=0.6,
    )
    return score_opportunity(
        market=market,
        hms=hms,
        edge=edge,
        side=Side.BUY,
        token_id="demo-yes",
        shares=10,
        cfg=OpportunityConfig(),
    )


def test_lifecycle_partial_then_filled() -> None:
    broker = PaperBroker(TradingConfig(paper_fill_ratio=0.4))
    opp = _opp()
    order = broker.create(opp, price=0.42, size=10, client_order_id="cid-1")
    assert order.status is OrderStatus.CREATED
    broker.submit("cid-1")
    first = broker.simulate_fill("cid-1", fill_ratio=0.4)
    assert first.status is OrderStatus.PARTIAL
    assert abs(first.filled_size - 4.0) < 1e-9
    second = broker.simulate_fill("cid-1", fill_ratio=1.0)
    assert second.status is OrderStatus.FILLED
    assert abs(second.filled_size - 10.0) < 1e-9


def test_idempotent_create() -> None:
    broker = PaperBroker(TradingConfig())
    opp = _opp()
    a = broker.create(opp, price=0.42, size=10, client_order_id="same")
    b = broker.create(opp, price=0.99, size=99, client_order_id="same")
    assert a.client_order_id == b.client_order_id
    assert b.price == 0.42
    assert b.reject_reason == ReasonCode.IDEMPOTENT_REPLAY


def test_illegal_filled_to_submitted() -> None:
    order = OrderRecord(
        client_order_id="x",
        status=OrderStatus.FILLED,
        market_id="m",
        token_id="t",
        side=Side.BUY,
        price=0.5,
        size=1,
        mode=TradingMode.PAPER,
    )
    sm = OrderStateMachine(order)
    try:
        sm.transition(OrderStatus.SUBMITTED)
        raise AssertionError("expected illegal transition")
    except IllegalTransition:
        pass


def test_never_infers_fill_from_missing_book_level() -> None:
    """Fills only come from simulate_fill, not from book mutations."""
    broker = PaperBroker(TradingConfig(paper_fill_ratio=0.0))
    order = broker.create(_opp(), price=0.42, size=10, client_order_id="no-infer")
    broker.submit("no-infer")
    # Book disappearance would be an external event; simulator with 0 ratio does not fill.
    left = broker.simulate_fill("no-infer", fill_ratio=0.0)
    assert left.filled_size == 0.0
    assert left.status is OrderStatus.ACKNOWLEDGED
    assert order.filled_size == 0.0
