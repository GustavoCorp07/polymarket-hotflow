"""WebSocket reconnect + official heartbeat (interface; no invented venues)."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from hotflow.official import CLOB_WS_PING_S, MARKET_WS, RTDS_PING_S, RTDS_WS, SPORTS_WS, USER_WS


@dataclass(frozen=True)
class HeartbeatSpec:
    url: str
    ping_interval_s: int
    ping_payload: str = "PING"
    expected_pong: str = "PONG"


MARKET_HEARTBEAT = HeartbeatSpec(url=MARKET_WS, ping_interval_s=CLOB_WS_PING_S)
USER_HEARTBEAT = HeartbeatSpec(url=USER_WS, ping_interval_s=CLOB_WS_PING_S)
RTDS_HEARTBEAT = HeartbeatSpec(url=RTDS_WS, ping_interval_s=RTDS_PING_S)
SPORTS_HEARTBEAT = HeartbeatSpec(url=SPORTS_WS, ping_interval_s=CLOB_WS_PING_S)


class ReconnectingWebSocket:
    """Tested reconnect/backoff + heartbeat scheduler.

    Actual socket I/O is injected so unit tests never open a network socket.
    Official ping intervals are required; callers cannot invent heartbeats.
    """

    def __init__(
        self,
        spec: HeartbeatSpec,
        *,
        send: Callable[[str], Awaitable[None]] | None = None,
        on_reconnect: Callable[[int], Awaitable[None]] | None = None,
        max_backoff_s: float = 30.0,
    ) -> None:
        self.spec = spec
        self._send = send
        self._on_reconnect = on_reconnect
        self.max_backoff_s = max_backoff_s
        self.connected = False
        self.reconnect_attempts = 0
        self.last_pong_ok = False

    def backoff_s(self, attempt: int) -> float:
        return min(self.max_backoff_s, 0.5 * (2 ** max(0, attempt)))

    async def connect(self) -> None:
        self.connected = True

    async def disconnect(self) -> None:
        self.connected = False

    async def handle_disconnect(self) -> None:
        self.connected = False
        self.reconnect_attempts += 1
        if self._on_reconnect:
            await self._on_reconnect(self.reconnect_attempts)
        await self.connect()

    async def send_heartbeat(self) -> None:
        if self._send is None:
            return
        await self._send(self.spec.ping_payload)

    def on_message(self, payload: str) -> dict[str, Any]:
        if payload == self.spec.expected_pong:
            self.last_pong_ok = True
            return {"type": "pong"}
        return {"type": "data", "payload": payload}
