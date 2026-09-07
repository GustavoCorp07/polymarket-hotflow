from hotflow.config import HotflowConfig, HotMarketConfig, OpportunityConfig, RiskConfig
from hotflow.hotmarket.opportunity import score_opportunity
from hotflow.hotmarket.score import score_hot_market
from hotflow.pipeline import PaperPipeline, demo_market
from hotflow.reason_codes import ReasonCode
from hotflow.risk.engine import RiskEngine
from hotflow.risk.kill_switch import KillSwitchBoard
from hotflow.types import EdgeBreakdown, KillSwitchReason, OrderStatus, Side


def _opp(notional: float = 100.0):
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
    return score_opportunity(
        market=market,
        hms=hms,
        edge=edge,
        side=Side.BUY,
        token_id="demo-yes",
        shares=notional / 0.4,
        cfg=OpportunityConfig(),
    )


def test_trip_blocks_new_orders() -> None:
    kills = KillSwitchBoard()
    engine = RiskEngine(RiskConfig(), kills)
    kills.trip(KillSwitchReason.AUTH_FAIL, "test")
    decision = engine.decide(_opp(10), category="crypto", spread=0.02, data_age_ms=1, latency_ms=1)
    assert decision.veto
    assert decision.reason == ReasonCode.KILL_SWITCH


def test_explicit_recovery_required() -> None:
    board = KillSwitchBoard()
    board.trip(KillSwitchReason.MANUAL, "halt")
    try:
        board.reset(acknowledge="")
        raise AssertionError("blank ack must fail")
    except ValueError:
        assert board.tripped
    board.reset(acknowledge="operator confirmed recover")
    assert not board.tripped


def test_stale_kills_and_cancels_open() -> None:
    from datetime import UTC, datetime, timedelta

    cfg = HotflowConfig()
    pipe = PaperPipeline(cfg)
    market = demo_market(hot=True)
    # Seed an open paper order first
    first = pipe.evaluate_market(market, p_info=0.70)
    assert first["accepted"] is True
    open_before = [o for o in pipe.broker.orders.values() if o.status is not OrderStatus.CANCELLED]
    assert open_before
    # Age the critical book feed
    pipe.clock.touch("clob_book", observed_at=datetime.now(UTC) - timedelta(seconds=90))
    aged = market.model_copy(deep=True)
    aged.book.fetched_at = datetime.now(UTC) - timedelta(seconds=90)  # type: ignore[union-attr]
    result = pipe.evaluate_market(aged, p_info=0.70)
    assert result["reason"] == ReasonCode.STALE_DATA
    assert pipe.kills.tripped
    assert pipe.kills.reason is KillSwitchReason.STALE_CRITICAL_DATA
    for order in pipe.broker.orders.values():
        assert order.status in {OrderStatus.CANCELLED, OrderStatus.FILLED, OrderStatus.PARTIAL}


def test_runaway_rejects_trip() -> None:
    engine = RiskEngine(RiskConfig(runaway_reject_count=3))
    engine.note_reject()
    engine.note_reject()
    assert not engine.kills.tripped
    engine.note_reject()
    assert engine.kills.reason is KillSwitchReason.RUNAWAY_REJECTS
