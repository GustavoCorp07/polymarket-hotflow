"""PAPER-only public Sports WS subscriber that fills SportsGameCache.

Unauthenticated per https://docs.polymarket.com/market-data/realtime-data
URL: wss://sports-api.polymarket.com/ws — no subscribe frame.
Server sends text `ping` every 5s; reply `pong` within 10s.
After disconnect: reconnect only (no snapshot/replay, no subscribe).
pytest must inject a transport — never open a live socket.

Sports data is informational and may be delayed or wrong.
"""

from __future__ import annotations

from typing import Any

from hotflow.config import SportsWsFeedConfig
from hotflow.marketdata.rtds_subscriber import FrameTransport, InjectedFrameTransport
from hotflow.marketdata.sports_cache import SportsGameCache
from hotflow.marketdata.sports_ws import parse_official_sports_message
from hotflow.marketdata.websocket import SPORTS_HEARTBEAT, ReconnectingWebSocket
from hotflow.official import SPORTS_CLIENT_PONG, SPORTS_PING_S, SPORTS_SERVER_PING, SPORTS_WS
from hotflow.types import SportsGameState

__all__ = [
    "FrameTransport",
    "InjectedFrameTransport",
    "LivePublicSportsTransport",
    "PublicSportsSubscriber",
    "run_live_public_sports_collect",
]


class LivePublicSportsTransport:
    """OPTIONAL live I/O to wss://sports-api.polymarket.com/ws. Not used by pytest."""

    optional_live_public = True
    url = SPORTS_WS

    def __init__(self) -> None:
        self._socket: Any = None

    async def connect(self) -> None:  # pragma: no cover — live only
        import websockets

        self._socket = await websockets.connect(self.url)

    async def send(self, payload: str) -> None:  # pragma: no cover
        if self._socket is None:
            raise ConnectionError("not connected")
        await self._socket.send(payload)

    async def recv(self) -> str:  # pragma: no cover
        if self._socket is None:
            raise ConnectionError("not connected")
        raw = await self._socket.recv()
        if isinstance(raw, bytes):
            return raw.decode("utf-8")
        return str(raw)

    async def close(self) -> None:  # pragma: no cover
        if self._socket is not None:
            await self._socket.close()
            self._socket = None


class PublicSportsSubscriber:
    """Brief public Sports WS reader that caches official-shape game updates.

    PAPER data only. Never places orders. Off unless the caller constructs it.
    """

    url = SPORTS_WS
    optional_live_public = True
    informational = True

    def __init__(
        self,
        cache: SportsGameCache,
        *,
        config: SportsWsFeedConfig | None = None,
        transport: FrameTransport | None = None,
    ) -> None:
        self.cache = cache
        self.config = config or SportsWsFeedConfig(max_data_age_ms=15_000, ping_interval_s=SPORTS_PING_S)
        self.transport = transport
        self.ws = ReconnectingWebSocket(
            SPORTS_HEARTBEAT,
            send=transport.send if transport is not None else None,
            max_backoff_s=self.config.reconnect_max_backoff_s,
        )
        self.prints_accepted = 0
        self.frames_seen = 0
        self.reconnects = 0
        self.pongs_sent = 0

    @property
    def ping_interval_s(self) -> float:
        return float(self.config.ping_interval_s or SPORTS_PING_S)

    def ingest(self, raw: str | dict[str, Any]) -> SportsGameState | None:
        if isinstance(raw, str):
            handled = self.ws.on_message(raw)
            if handled.get("type") == "pong":
                return None
        parsed = parse_official_sports_message(raw)
        if parsed is None:
            return None
        parsed = parsed.model_copy(update={"source": "live_sports_ws"})
        if self.cache.put(parsed):
            self.prints_accepted += 1
            return parsed
        return None

    async def reply_pong(self) -> None:
        if self.transport is not None:
            await self.transport.send(SPORTS_CLIENT_PONG)
        elif self.ws._send is not None:  # noqa: SLF001
            await self.ws._send(SPORTS_CLIENT_PONG)
        self.pongs_sent += 1
        self.ws.last_pong_ok = True

    async def reconnect(self) -> None:
        """Official: no snapshot after disconnect — reconnect; no subscribe frame."""
        import asyncio

        self.reconnects += 1
        await self.ws.handle_disconnect()
        if self.transport is not None:
            await self.transport.connect()
        delay = self.ws.backoff_s(self.reconnects)
        if delay > 0:
            await asyncio.sleep(delay)

    def request_stop(self) -> None:
        import asyncio

        if not hasattr(self, "_stop"):
            self._stop = asyncio.Event()
        self._stop.set()

    async def run(
        self,
        *,
        duration_s: float | None = None,
        max_prints: int | None = None,
    ) -> int:
        import asyncio

        if self.transport is None:
            raise RuntimeError(
                "PublicSportsSubscriber.run requires an injected transport in tests; "
                "use LivePublicSportsTransport only for explicit operator --sports-live"
            )
        self._stop = asyncio.Event()
        await self.transport.connect()
        await self.ws.connect()
        loop = asyncio.get_running_loop()
        deadline = None if duration_s is None else (loop.time() + duration_s)
        while not self._stop.is_set():
            if max_prints is not None and self.prints_accepted >= max_prints:
                break
            if deadline is not None and loop.time() >= deadline:
                break
            timeout = self.ping_interval_s
            if deadline is not None:
                timeout = max(0.01, min(timeout, deadline - loop.time()))
            try:
                raw = await asyncio.wait_for(self.transport.recv(), timeout=timeout)
            except TimeoutError:
                # Server-initiated heartbeat: do not send unsolicited pong.
                continue
            except ConnectionError:
                await self.reconnect()
                continue
            if raw == SPORTS_SERVER_PING:
                await self.reply_pong()
                continue
            self.frames_seen += 1
            self.ingest(raw)
        if self.transport is not None:
            await self.transport.close()
        return self.prints_accepted


async def run_live_public_sports_collect(cache: SportsGameCache, config: SportsWsFeedConfig) -> int:
    """OPTIONAL unauthenticated collect. Not imported by pytest."""
    transport = LivePublicSportsTransport()
    subscriber = PublicSportsSubscriber(cache, config=config, transport=transport)
    return await subscriber.run(duration_s=config.collect_seconds)
