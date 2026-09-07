"""Official RTDS Chainlink TWAP interface.

Default paper path uses fixtures. A live public client exists and is clearly
labeled — official docs allow unauthenticated RTDS read at
wss://ws-live-data.polymarket.com. pytest never opens that socket.
"""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, Protocol

from hotflow.marketdata.twap_fixtures import default_paper_fixtures
from hotflow.marketdata.websocket import RTDS_HEARTBEAT, ReconnectingWebSocket
from hotflow.official import (
    RTDS_TWAP_30,
    RTDS_TWAP_60,
    RTDS_TWAP_SDK_TOPIC,
    RTDS_TWAP_WINDOWS,
    RTDS_WS,
    rtds_twap_subscribe_payload,
    rtds_twap_topic,
)
from hotflow.types import OfficialTwapObservation

E18 = Decimal(10) ** 18


class TwapObservationSource(Protocol):
    def latest(self, symbol: str, window_seconds: int) -> OfficialTwapObservation | None: ...


def _e18_to_float(raw: str | int | float) -> float:
    return float(Decimal(str(raw)) / E18)


def parse_official_rtds_twap_event(
    message: dict[str, Any],
    *,
    source: str,
    observed_at: datetime | None = None,
) -> OfficialTwapObservation | None:
    """Parse raw RTDS or SDK-shaped official TWAP updates. Ignore other topics."""
    topic = message.get("topic")
    payload = message.get("payload")
    if not isinstance(payload, dict):
        return None
    window = payload.get("window_s") or payload.get("window_seconds") or payload.get("windowSeconds")
    if topic == RTDS_TWAP_30:
        window = 30
    elif topic == RTDS_TWAP_60:
        window = 60
    elif topic == RTDS_TWAP_SDK_TOPIC and window is not None:
        window = int(window)
    if window not in RTDS_TWAP_WINDOWS:
        return None
    symbol = str(payload.get("symbol") or "").lower()
    if not symbol:
        return None
    full_acc = payload.get("full_accuracy_value")
    if full_acc is not None:
        value = _e18_to_float(full_acc)
        full_acc_str = str(full_acc)
    elif payload.get("value") is not None:
        value = float(payload["value"])
        full_acc_str = None
    else:
        return None
    ts = payload.get("timestamp")
    return OfficialTwapObservation(
        symbol=symbol,
        window_seconds=int(window),
        value=value,
        full_accuracy_value=full_acc_str,
        payload_timestamp_ms=int(ts) if ts is not None else None,
        observed_at=observed_at or datetime.now(UTC),
        source=source,
        topic=str(topic) if topic else rtds_twap_topic(int(window)),
    )


class FixtureTwapSource:
    """In-memory official-shape prints for paper-run --mock and unit tests."""

    def __init__(
        self,
        observations: dict[tuple[str, int], OfficialTwapObservation] | None = None,
    ) -> None:
        self._rows = observations if observations is not None else default_paper_fixtures()

    def put(self, observation: OfficialTwapObservation) -> None:
        self._rows[(observation.symbol.lower(), observation.window_seconds)] = observation

    def latest(self, symbol: str, window_seconds: int) -> OfficialTwapObservation | None:
        return self._rows.get((symbol.lower(), window_seconds))


class PublicRtdsTwapClient:
    """OPTIONAL LIVE PUBLIC RTDS — unauthenticated Chainlink TWAP reader.

    Official (retrieved 2026-09-07): no credentials.
    https://docs.polymarket.com/market-data/chainlink-twap

    Not used by pytest. Not used by `hotflow paper-run --mock`.
    Direct clients must reconnect and resubscribe; there is no snapshot/replay.
    Heartbeat: text PING every 5 seconds (see RTDS_HEARTBEAT).
    """

    url = RTDS_WS
    optional_live_public = True

    def __init__(
        self,
        *,
        send: Callable[[str], Awaitable[None]] | None = None,
        on_reconnect: Callable[[int], Awaitable[None]] | None = None,
    ) -> None:
        self.ws = ReconnectingWebSocket(RTDS_HEARTBEAT, send=send, on_reconnect=on_reconnect)
        self._latest: dict[tuple[str, int], OfficialTwapObservation] = {}
        self._desired: list[tuple[int, str | None]] = []

    def latest(self, symbol: str, window_seconds: int) -> OfficialTwapObservation | None:
        return self._latest.get((symbol.lower(), window_seconds))

    def subscribe_payload(self, *, window_seconds: int, symbol: str | None = None) -> dict[str, Any]:
        self._desired.append((window_seconds, symbol))
        return rtds_twap_subscribe_payload(window_seconds=window_seconds, symbol=symbol)

    def handle_payload(self, raw: str | dict[str, Any]) -> OfficialTwapObservation | None:
        if isinstance(raw, str):
            handled = self.ws.on_message(raw)
            if handled.get("type") == "pong":
                return None
            try:
                message = json.loads(raw)
            except json.JSONDecodeError:
                return None
        else:
            message = raw
        parsed = parse_official_rtds_twap_event(message, source="live_rtds")
        if parsed is not None:
            self._latest[(parsed.symbol, parsed.window_seconds)] = parsed
        return parsed

    async def send_heartbeat(self) -> None:
        await self.ws.send_heartbeat()

    async def handle_disconnect(self) -> None:
        """Official: no snapshot after disconnect — reconnect and resubscribe."""
        await self.ws.handle_disconnect()

    async def resubscribe(self) -> None:
        if self.ws._send is None:  # noqa: SLF001 — injected transport
            return
        for window, symbol in self._desired:
            frame = rtds_twap_subscribe_payload(window_seconds=window, symbol=symbol)
            await self.ws._send(json.dumps(frame, separators=(",", ":")))  # noqa: SLF001

    async def open_public_socket(self, *, windows: list[int], symbol: str | None = None) -> None:
        """OPTIONAL live I/O. Do not call from pytest.

        Opens wss://ws-live-data.polymarket.com, sends official subscribe
        frames, and stores the next updates. Caller owns the receive loop.
        """
        try:
            import websockets
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError("websockets is required for the optional public RTDS client") from exc
        self._desired = [(window, symbol) for window in windows]
        async with websockets.connect(self.url) as socket:  # pragma: no cover — live only

            async def _send(payload: str) -> None:
                await socket.send(payload)

            self.ws = ReconnectingWebSocket(RTDS_HEARTBEAT, send=_send)
            await self.ws.connect()
            await self.resubscribe()
            raw = await socket.recv()
            if isinstance(raw, bytes):
                raw = raw.decode("utf-8")
            self.handle_payload(raw)
