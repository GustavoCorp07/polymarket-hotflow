from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path

from hotflow.backtest import EventDrivenBacktester
from hotflow.backtest.recorder import (
    book_event_from_clob_json,
    build_synthetic_longer_stream,
    parse_clob_book_payload,
    record_live_stream,
    twap_event_from_rtds_message,
)
from hotflow.config import load_config
from hotflow.official import RTDS_TWAP_60
from hotflow.types import BookLevel, OrderBook

LONGER = Path(__file__).parent / "fixtures" / "backtest" / "crypto_longer_synthetic.json"
LIVE_SAMPLE = Path(__file__).parent / "fixtures" / "backtest" / "clob_book_live_sample.json"


def test_parse_official_clob_book() -> None:
    raw = {
        "asset_id": "abc",
        "bids": [{"price": "0.40", "size": "90"}, {"price": "0.38", "size": "10"}],
        "asks": [{"price": "0.42", "size": "80"}],
        "timestamp": "1710000000000",
    }
    book = parse_clob_book_payload(raw)
    assert book is not None
    assert book.best_bid == 0.40
    assert book.best_ask == 0.42
    event = book_event_from_clob_json(raw, ts=datetime(2026, 4, 1, tzinfo=UTC))
    assert event is not None
    assert event["kind"] == "book"
    assert event["payload"]["source"] == "clob_book"


def test_parse_clob_book_rejects_empty() -> None:
    assert parse_clob_book_payload({"bids": [], "asks": []}) is None
    assert book_event_from_clob_json({"hello": 1}, ts=datetime.now(UTC)) is None


def test_parse_rtds_official_and_reject_invented() -> None:
    ts = datetime(2026, 4, 1, tzinfo=UTC)
    ok = twap_event_from_rtds_message(
        {
            "topic": RTDS_TWAP_60,
            "payload": {"symbol": "btc/usd", "value": 65010.0, "window_s": 60},
        },
        ts=ts,
    )
    assert ok is not None
    assert ok["payload"]["window_seconds"] == 60
    bad_window = twap_event_from_rtds_message(
        {"topic": "crypto_prices_twap_forty", "payload": {"symbol": "btc/usd", "value": 1.0, "window_s": 45}},
        ts=ts,
    )
    assert bad_window is None
    bad_symbol = twap_event_from_rtds_message(
        {"topic": RTDS_TWAP_60, "payload": {"symbol": "doge/usd", "value": 1.0, "window_s": 60}},
        ts=ts,
    )
    assert bad_symbol is None


def test_longer_synthetic_is_labeled_and_backtests() -> None:
    document = json.loads(LONGER.read_text(encoding="utf-8"))
    assert document["origin"] == "synthetic_official_shape"
    assert document["synthetic"] is True
    assert document["event_count"] >= 100
    kinds = {row["kind"] for row in document["events"]}
    assert {"book", "twap", "decision", "resolve"} <= kinds
    assert "clobTokenIds" not in json.dumps(document)
    generated = build_synthetic_longer_stream()
    assert generated["event_count"] == document["event_count"]
    report = EventDrivenBacktester(load_config(Path("configs/default.yaml"))).run_fixture(LONGER)
    assert report["mode"] == "backtest"
    assert report["lookahead"] is False
    assert report["metrics"]["abs_pnl_not_a_selection_metric"] is True
    assert "train" in report["splits"]


def test_record_live_with_injected_client() -> None:
    class _Fake:
        async def get_book(self, token_id: str, condition_id: str | None = None) -> OrderBook:
            return OrderBook(
                token_id="redacted-yes",
                bids=[BookLevel(price=0.40, size=90)],
                asks=[BookLevel(price=0.42, size=80)],
                source="clob_book",
            )

        async def get_fee_rate(self, token_id: str) -> int:
            return 40

    document = asyncio.run(
        record_live_stream(seconds=4, poll_interval_s=2, token_id="ignored", book_client=_Fake())
    )
    assert document["origin"] == "live_public_clob"
    assert document["live"]["token_id"] == "redacted"
    assert document["event_count"] >= 2
    assert "clobTokenIds" not in json.dumps(document)


def test_live_sample_is_redacted_official_shape() -> None:
    document = json.loads(LIVE_SAMPLE.read_text(encoding="utf-8"))
    assert document["origin"] == "live_public_clob"
    assert document["live_collect"] is True
    dumped = json.dumps(document)
    assert "clobTokenIds" not in dumped
    assert document["live"]["token_id"] == "redacted"
    assert document["fees"].get("rate") is None or "as_of" in document["fees"]["source"]


def test_cli_record_stream_mock(tmp_path: Path) -> None:
    from typer.testing import CliRunner

    from hotflow.cli import app

    out = tmp_path / "stream.json"
    completed = CliRunner().invoke(app, ["record-stream", "--mock", "--out", str(out)])
    assert completed.exit_code == 0, completed.output
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["origin"] == "synthetic_official_shape"
    assert payload["event_count"] >= 100
