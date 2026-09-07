"""Deterministic official-shape RTDS TWAP fixtures for paper-run --mock and pytest.

Payload keys match https://docs.polymarket.com/market-data/chainlink-twap
(raw RTDS example). Values that differ from the docs example are labeled
source=fixture and are not live prints.
"""

from __future__ import annotations

from datetime import UTC, datetime

from hotflow.official import RTDS_TWAP_30, RTDS_TWAP_60
from hotflow.types import OfficialTwapObservation

# Copied shape from official docs example (window 30, value 65000.5).
OFFICIAL_DOCS_EXAMPLE_THIRTY: dict = {
    "topic": RTDS_TWAP_30,
    "type": "update",
    "timestamp": 1785178800123,
    "payload": {
        "symbol": "btc/usd",
        "value": 65000.5,
        "full_accuracy_value": "65000500000000000000000",
        "timestamp": 1785178800000,
        "window_s": 30,
    },
}

OFFICIAL_DOCS_EXAMPLE_SIXTY: dict = {
    "topic": RTDS_TWAP_60,
    "type": "update",
    "timestamp": 1785178800123,
    "payload": {
        "symbol": "btc/usd",
        "value": 65000.5,
        "full_accuracy_value": "65000500000000000000000",
        "timestamp": 1785178800000,
        "window_s": 60,
    },
}

# Paper-run mock: official payload shape, fixture value far enough from strike
# for NET edge to be testable. Not a live Chainlink print.
PAPER_MOCK_BTC_USD_60: dict = {
    "topic": RTDS_TWAP_60,
    "type": "update",
    "timestamp": 1785178800123,
    "payload": {
        "symbol": "btc/usd",
        "value": 68000.0,
        "full_accuracy_value": "68000000000000000000000",
        "timestamp": 1785178800000,
        "window_s": 60,
    },
}


def observation_from_official_payload(
    message: dict,
    *,
    source: str,
    now: datetime | None = None,
) -> OfficialTwapObservation:
    payload = message["payload"]
    return OfficialTwapObservation(
        symbol=str(payload["symbol"]).lower(),
        window_seconds=int(payload.get("window_s") or payload.get("window_seconds")),
        value=float(payload["value"]),
        full_accuracy_value=(
            str(payload["full_accuracy_value"]) if payload.get("full_accuracy_value") is not None else None
        ),
        payload_timestamp_ms=int(payload["timestamp"]) if payload.get("timestamp") is not None else None,
        observed_at=now or datetime.now(UTC),
        source=source,
        topic=str(message.get("topic")),
    )


def default_paper_fixtures(*, now: datetime | None = None) -> dict[tuple[str, int], OfficialTwapObservation]:
    observed = now or datetime.now(UTC)
    sixty = observation_from_official_payload(PAPER_MOCK_BTC_USD_60, source="fixture", now=observed)
    thirty = observation_from_official_payload(OFFICIAL_DOCS_EXAMPLE_THIRTY, source="fixture", now=observed)
    return {
        (sixty.symbol, sixty.window_seconds): sixty,
        (thirty.symbol, thirty.window_seconds): thirty,
    }
