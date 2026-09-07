"""PAPER-only public RTDS subscriber that fills TwapPrintCache.

Unauthenticated per https://docs.polymarket.com/market-data/chainlink-twap
Heartbeat: text PING every 5 seconds. After disconnect: reconnect + resubscribe
(no snapshot/replay). pytest must inject a transport — never open a live socket.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable
from typing import Any, Protocol

from hotflow.config import RtdsFeedConfig
from hotflow.marketdata.rtds_twap import PublicRtdsTwapClient, parse_official_rtds_twap_event
from hotflow.marketdata.twap_cache import TwapPrintCache
from hotflow.marketdata.websocket import RTDS_HEARTBEAT, ReconnectingWebSocket
from hotflow.official import (
    RTDS_CHAINLINK_SYMBOLS,
    RTDS_PING_S,
    RTDS_TWAP_WINDOWS,
    RTDS_WS,
    rtds_twap_subscribe_documented,
)
from hotflow.types import OfficialTwapObservation


class FrameTransport(Protocol):
    async def connect(self) -> None: ...
    async def send(self, payload: str) -> None: ...
    async def recv(self) -> str: ...
    async def close(self) -> None: ...


class InjectedFrameTransport:
    """Deterministic WS double for pytest. Does not open a network socket."""

    def __init__(self, frames: list[str] | None = None) -> None:
        self._queue: asyncio.Queue[str | None] = asyncio.Queue()
        for frame in frames or []:
            self._queue.put_nowait(frame)
        self.sent: list[str] = []
        self.connected = False
        self.closed = False

    def push(self, frame: str) -> None:
        self._queue.put_nowait(frame)

    def push_disconnect(self) -> None:
        self._queue.put_nowait(None)

    async def connect(self) -> None:
        self.connected = True

    async def send(self, payload: str) -> None:
        self.sent.append(payload)

    async def recv(self) -> str:
        item = await self._queue.get()
        if item is None:
            raise ConnectionError("injected disconnect")
        return item

    async def close(self) -> None:
        self.closed = True
        self.connected = False


class LivePublicRtdsTransport:
    """OPTIONAL live I/O to wss://ws-live-data.polymarket.com. Not used by pytest."""

    optional_live_public = True
    url = RTDS_WS

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


class PublicRtdsSubscriber:
    """Background/brief public RTDS reader that caches official 30s/60s prints.

    PAPER data only. Never places orders. Off unless the caller constructs it.
    """

    url = RTDS_WS
    optional_live_public = True

    def __init__(
        self,
        cache: TwapPrintCache,
        *,
        config: RtdsFeedConfig | None = None,
        transport: FrameTransport | None = None,
        send: Callable[[str], Awaitable[None]] | None = None,
        on_observation: Callable[[OfficialTwapObservation], None] | None = None,
    ) -> None:
        self.cache = cache
        self.config = config or RtdsFeedConfig(max_data_age_ms=10_000, ping_interval_s=RTDS_PING_S)
        self.transport = transport
        self.client = PublicRtdsTwapClient(send=send)
        self.on_observation = on_observation
        self.ws = ReconnectingWebSocket(
            RTDS_HEARTBEAT,
            send=send or (transport.send if transport is not None else None),
            max_backoff_s=self.config.reconnect_max_backoff_s,
        )
        self.prints_accepted = 0
        self.reconnects = 0
        self._stop = asyncio.Event()

    @property
    def ping_interval_s(self) -> float:
        return float(self.config.ping_interval_s or RTDS_PING_S)

    def subscribe_frame(self) -> dict[str, Any]:
        windows = [item for item in self.config.subscribe_windows if item in RTDS_TWAP_WINDOWS]
        symbols = [item for item in self.config.subscribe_symbols if item in RTDS_CHAINLINK_SYMBOLS]
        return rtds_twap_subscribe_documented(windows=windows or None, symbols=symbols or None)

    def ingest(self, raw: str | dict[str, Any]) -> OfficialTwapObservation | None:
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
        if parsed is None:
            return None
        if self.cache.put(parsed):
            self.prints_accepted += 1
            self.client._latest[(parsed.symbol, parsed.window_seconds)] = parsed  # noqa: SLF001
            if self.on_observation is not None:
                self.on_observation(parsed)
            return parsed
        return None

    async def _send_json(self, payload: dict[str, Any]) -> None:
        blob = json.dumps(payload, separators=(",", ":"))
        if self.transport is not None:
            await self.transport.send(blob)
        elif self.ws._send is not None:  # noqa: SLF001
            await self.ws._send(blob)

    async def subscribe(self) -> None:
        await self._send_json(self.subscribe_frame())

    async def heartbeat(self) -> None:
        if self.transport is not None:
            await self.transport.send(RTDS_HEARTBEAT.ping_payload)
        else:
            await self.ws.send_heartbeat()

    async def reconnect(self) -> None:
        self.reconnects += 1
        await self.ws.handle_disconnect()
        if self.transport is not None:
            await self.transport.connect()
        delay = self.ws.backoff_s(self.reconnects)
        if delay > 0:
            await asyncio.sleep(delay)
        await self.subscribe()

    def request_stop(self) -> None:
        self._stop.set()

    async def run(
        self,
        *,
        duration_s: float | None = None,
        max_prints: int | None = None,
    ) -> int:
        if self.transport is None:
            raise RuntimeError(
                "PublicRtdsSubscriber.run requires an injected transport in tests; "
                "use LivePublicRtdsTransport only for explicit operator --rtds-live"
            )
        await self.transport.connect()
        await self.ws.connect()
        await self.subscribe()
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
                await self.heartbeat()
                continue
            except ConnectionError:
                await self.reconnect()
                continue
            self.ingest(raw)
        if self.transport is not None:
            await self.transport.close()
        return self.prints_accepted


async def run_live_public_collect(cache: TwapPrintCache, config: RtdsFeedConfig) -> int:
    """OPTIONAL unauthenticated collect. Not imported by pytest."""
    transport = LivePublicRtdsTransport()
    subscriber = PublicRtdsSubscriber(cache, config=config, transport=transport)
    return await subscriber.run(duration_s=config.collect_seconds)
