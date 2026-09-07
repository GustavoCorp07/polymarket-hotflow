from __future__ import annotations

import json
from pathlib import Path

from hotflow.backtest import (
    EventDrivenBacktester,
    NullBacktester,
    rank_reports,
    refuse_max_abs_pnl_selection,
    run_shadow,
)
from hotflow.backtest.events import FixtureEventSource, candle_only
from hotflow.config import load_config
from hotflow.pipeline import PaperPipeline, demo_market
from hotflow.reason_codes import ReasonCode

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "backtest"
CRYPTO = FIXTURE_DIR / "crypto_book_trade.json"
CANDLES = FIXTURE_DIR / "candle_only.json"
GAP = FIXTURE_DIR / "data_gap.json"


def _cfg():
    return load_config(Path("configs/default.yaml"))


def test_default_mode_stays_paper() -> None:
    cfg = _cfg()
    assert cfg.trading.mode == "paper"
    assert cfg.backtest.refuse_candle_only is True


def test_candle_only_refused() -> None:
    assert candle_only(FixtureEventSource(CANDLES).events()) is True
    report = EventDrivenBacktester(_cfg()).run_fixture(CANDLES)
    assert report["reason"] == ReasonCode.CANDLE_ONLY_REFUSED
    assert report["trades"] == []


def test_replay_uses_book_not_future_book() -> None:
    report = EventDrivenBacktester(_cfg()).run_fixture(CRYPTO)
    assert report["lookahead"] is False
    assert "book" in report["kinds"]
    assert "trade" in report["kinds"]
    first = report["decisions"][0]
    assert first["expected_price"] == 0.42
    assert first["book_ask"] == 0.42
    assert first["accepted"] is True
    fill = first["fill"]
    assert fill["filled"] is True
    # Fill uses the latency-window book (0.41/0.43), not the later 0.11 leak.
    assert fill["price"] is not None
    assert 0.41 <= float(fill["price"]) < 0.43
    assert float(fill["price"]) != 0.11
    assert report["metrics"]["trade_count"] >= 1
    assert "expectancy" in report["metrics"]
    assert "max_drawdown" in report["metrics"]
    assert report["metrics"]["abs_pnl_not_a_selection_metric"] is True
    assert report["splits"]["train"]["trade_count"] >= 1
    assert report["splits"]["validation"]["trade_count"] >= 1
    assert report["splits"]["oos"]["trade_count"] >= 1
    assert report["walk_forward"]["status"] == "stub"
    assert report["assumptions"]["fees"]["marked"] is True


def test_data_gap_skips() -> None:
    report = EventDrivenBacktester(_cfg()).run_fixture(GAP)
    reasons = [row["reason"] for row in report["decisions"]]
    assert ReasonCode.DATA_GAP in reasons
    assert report["decisions"][-1]["accepted"] is False


def test_refuse_max_abs_pnl_selection() -> None:
    blocked = refuse_max_abs_pnl_selection("abs_pnl")
    assert blocked is not None
    assert blocked["reason"] == ReasonCode.MAX_ABS_PNL_SELECTION_REFUSED
    ranked = rank_reports(
        [
            {
                "backtest_id": "a",
                "metrics": {"expectancy": 0.01, "max_drawdown": 0.2, "trade_count": 10, "abs_pnl": 999},
            },
            {
                "backtest_id": "b",
                "metrics": {"expectancy": 0.05, "max_drawdown": 0.1, "trade_count": 8, "abs_pnl": 1},
            },
        ],
        metric="expectancy",
    )
    assert ranked["refused"] is False
    assert ranked["selected"] == "b"
    assert rank_reports([{"metrics": {"abs_pnl": 9}}], metric="pnl")["refused"] is True


def test_null_backtester_empty() -> None:
    class _Empty:
        def events(self):
            return iter(())

    smoke = NullBacktester().run(_Empty())
    assert smoke["events"] == 0
    assert smoke["mode"] == "offline"


def test_shadow_does_not_send_orders() -> None:
    cfg = _cfg()
    pipe = PaperPipeline(cfg)
    rows = run_shadow(
        cfg,
        [demo_market(hot=True)],
        p_info=0.70,
        next_prices={"demo-btc-updown": 0.43},
        pipeline=pipe,
    )
    assert rows
    assert rows[0]["reason"] == ReasonCode.SHADOW_MODE
    assert rows[0]["would_buy"] is True
    assert rows[0]["would_sell"] is False
    assert rows[0]["expected_price"] is not None
    assert rows[0]["actual_price_after_signal"] == 0.43
    assert rows[0]["simulated_fill"]["sent"] is False
    assert pipe.broker.orders == {}


def test_cli_backtest_and_shadow(tmp_path) -> None:
    from typer.testing import CliRunner

    from hotflow.cli import app

    out = tmp_path / "bt.json"
    completed = CliRunner().invoke(
        app, ["backtest", "--fixture", str(CRYPTO), "--out", str(out)]
    )
    assert completed.exit_code == 0, completed.output
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["mode"] == "backtest"
    assert payload["metrics"]["trade_count"] >= 1

    shadow_out = tmp_path / "shadow.json"
    shadow = CliRunner().invoke(app, ["shadow", "--mock", "--out", str(shadow_out)])
    assert shadow.exit_code == 0, shadow.output
    body = json.loads(shadow_out.read_text(encoding="utf-8"))
    assert body["sent_orders"] is False
    assert body["mode"] == "shadow"
