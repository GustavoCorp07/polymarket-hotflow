from hotflow.config import HotflowConfig, RiskConfig
from hotflow.monitoring.observer import Observability
from hotflow.portfolio.ledger import PaperLedger, replay_events
from hotflow.portfolio.session import PaperSession, mock_markets, run_kill_recovery_drill
from hotflow.reason_codes import ReasonCode
from hotflow.types import KillSwitchReason, Side


def test_buy_sell_realized_and_replay() -> None:
    led = PaperLedger(starting_cash=1_000.0, session_id="t1")
    buy = led.apply_fill(
        token_id="yes",
        market_id="m1",
        side=Side.BUY,
        size=10,
        price=0.40,
        fee=0.10,
        note="open",
    )
    assert buy.closed is False
    assert abs(led.cash - (1_000.0 - 4.0 - 0.10)) < 1e-9
    led.mark("yes", 0.50, market_id="m1")
    assert abs(led.unrealized_pnl() - 1.0) < 1e-9
    sell = led.apply_fill(
        token_id="yes",
        market_id="m1",
        side=Side.SELL,
        size=10,
        price=0.50,
        fee=0.05,
        note="close",
    )
    assert sell.closed is True
    assert abs(sell.realized_delta - (1.0 - 0.05)) < 1e-9
    snap = led.snapshot()
    assert abs(snap.realized_pnl - 0.95) < 1e-9
    assert abs(snap.unrealized_pnl) < 1e-9
    assert snap.closed_count == 1
    assert snap.win_rate == 1.0
    assert not snap.positions
    replayed = replay_events(led.events, starting_cash=1_000.0, session_id="replay")
    got = replayed.snapshot()
    assert abs(got.cash - snap.cash) < 1e-9
    assert abs(got.realized_pnl - snap.realized_pnl) < 1e-9
    assert abs(got.equity - snap.equity) < 1e-9


def test_flatten_refuses_missing_mark() -> None:
    led = PaperLedger(starting_cash=100.0)
    led.apply_fill(token_id="t", market_id="m", side="BUY", size=2, price=0.5, fee=0.0)
    try:
        led.flatten({})
        raise AssertionError("missing mark must refuse")
    except ValueError as exc:
        assert "invented" in str(exc)


def test_flatten_closed_trade_win_rate() -> None:
    led = PaperLedger(starting_cash=100.0)
    led.apply_fill(token_id="a", market_id="m", side="BUY", size=4, price=0.25, fee=0.0)
    led.apply_fill(token_id="b", market_id="m", side="BUY", size=4, price=0.25, fee=0.0)
    led.flatten({"a": 0.40, "b": 0.10})
    snap = led.snapshot()
    assert snap.closed_count == 2
    assert abs(snap.win_rate - 0.5) < 1e-9
    assert abs(snap.expectancy - ((0.15 * 4) + (-0.15 * 4)) / 2) < 1e-9


def test_multi_cycle_shared_ledger() -> None:
    cfg = HotflowConfig()
    cfg.risk.cooldown_ms = 0
    cfg.risk.cooldown_after_losses_ms = 0
    session = PaperSession(cfg, use_twap_fixtures=True)
    first = session.run_markets(mock_markets()[:1])
    cash_after_first = session.ledger.cash
    second = session.run_markets(mock_markets()[:1])
    assert first["accepted"] >= 0
    assert second["ok"] is True
    assert session.ledger.cash <= cash_after_first + 1e-9
    assert session.ledger.snapshot().event_count >= 1
    assert session.ledger.starting_cash == cfg.trading.paper_starting_cash


def test_kill_drill_blocks_then_explicit_recover() -> None:
    cfg = HotflowConfig()
    cfg.risk = RiskConfig(max_daily_loss=100.0, max_session_loss=100.0, max_drawdown=0.99)
    cfg.risk.cooldown_ms = 0
    cfg.risk.cooldown_after_losses_ms = 0
    session = PaperSession(cfg, use_twap_fixtures=True)
    drill = run_kill_recovery_drill(
        session,
        acknowledge="operator confirmed recover",
        size=1_000.0,
        open_price=0.5,
        close_price=0.2,
    )
    assert drill["tripped"] is True
    assert drill["kill_reason"] == KillSwitchReason.DAILY_LOSS_EXCEEDED.value
    assert drill["blocked_accepted"] is False
    assert drill["blocked_reason"] == ReasonCode.KILL_SWITCH
    assert drill["blank_ack_rejected"] is True
    assert drill["recovered"] is True
    assert session.pipe.kills.tripped is False


def test_observer_win_rate_from_closed_trades() -> None:
    cfg = HotflowConfig()
    obs = Observability.from_config(cfg)
    session = PaperSession(cfg, obs=obs, use_twap_fixtures=True)
    session.ledger.apply_fill(token_id="x", market_id="m", side="BUY", size=5, price=0.4, fee=0.0)
    events = session.ledger.flatten({"x": 0.5})
    for event in events:
        if event.closed:
            obs.metrics.note_closed_trade(event.realized_delta)
    obs.publish_ledger(session.ledger.snapshot())
    assert session.ledger.snapshot().win_rate == 1.0
    assert obs.metrics._closed == 1
    assert obs.metrics._wins == 1
