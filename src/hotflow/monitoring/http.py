"""Optional localhost HTTP: /  /api/state  /events  /metrics  /health  /ready."""

from __future__ import annotations

import json
import threading
from email.utils import formatdate
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import urlparse
from uuid import uuid4

from prometheus_client import CONTENT_TYPE_LATEST, CollectorRegistry, generate_latest

from hotflow.marketdata.clock import monotonic_ms
from hotflow.monitoring.dashboard import DashboardHub, idle_snapshot, load_dashboard_html
from hotflow.monitoring.health import HealthState
from hotflow.monitoring.json_logs import JsonLogger

_SERVERS: list[ThreadingHTTPServer] = []


def _json_bytes(payload: dict[str, Any]) -> bytes:
    return json.dumps(payload, default=str).encode("utf-8")


def make_handler(
    registry: CollectorRegistry,
    health: HealthState,
    logger: JsonLogger | None = None,
    hub: DashboardHub | None = None,
) -> type[BaseHTTPRequestHandler]:
    log = logger or JsonLogger("hotflow.http")
    board = hub

    class ObservabilityHandler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, fmt: str, *args: object) -> None:
            return

        def _state(self) -> dict[str, Any]:
            if board is not None:
                return board.snapshot()
            return idle_snapshot(health)

        def _write(self, status: int, body: bytes, content_type: str) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("Date", formatdate(usegmt=True))
            self.end_headers()
            self.wfile.write(body)

        def _stream_sse(self) -> int:
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Connection", "keep-alive")
            self.send_header("X-Accel-Buffering", "no")
            self.send_header("Date", formatdate(usegmt=True))
            self.end_headers()
            last = -1
            try:
                while True:
                    if board is not None:
                        snap = board.wait_snapshot(last, timeout=1.0)
                    else:
                        snap = idle_snapshot(health)
                    last = int(snap.get("generation") or 0)
                    chunk = f"id: {last}\ndata: {json.dumps(snap, default=str)}\n\n".encode()
                    self.wfile.write(chunk)
                    self.wfile.flush()
                    if board is None:
                        threading.Event().wait(1.0)
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError, OSError):
                return 200
            return 200

        def do_GET(self) -> None:  # noqa: N802
            started = monotonic_ms()
            path = urlparse(self.path).path
            request_id = self.headers.get("X-Request-Id") or str(uuid4())
            status = 404
            try:
                if path in {"/", "/dashboard", "/index.html"}:
                    body = load_dashboard_html().encode("utf-8")
                    self._write(200, body, "text/html; charset=utf-8")
                    status = 200
                    return
                if path in {"/api/state", "/dashboard.json"}:
                    self._write(200, _json_bytes(self._state()), "application/json")
                    status = 200
                    return
                if path == "/events":
                    status = self._stream_sse()
                    return
                if path == "/metrics":
                    body = generate_latest(registry)
                    self._write(200, body, CONTENT_TYPE_LATEST)
                    status = 200
                    return
                if path == "/health":
                    payload = health.payload()
                    self._write(200, _json_bytes(payload), "application/json")
                    status = 200
                    return
                if path == "/ready":
                    ready = health.ready
                    payload = health.payload(ready=ready)
                    status = 200 if ready else 503
                    self._write(status, _json_bytes(payload), "application/json")
                    return
                self._write(404, b'{"error":"not_found"}', "application/json")
            finally:
                log.request(
                    request_id=request_id,
                    method="GET",
                    path=path,
                    status=status,
                    latency_ms=monotonic_ms() - started,
                    source="local_http",
                )

    return ObservabilityHandler


def start_metrics_server(
    *,
    bind: str = "127.0.0.1",
    port: int = 9108,
    registry: CollectorRegistry,
    health: HealthState | None = None,
    logger: JsonLogger | None = None,
    hub: DashboardHub | None = None,
) -> ThreadingHTTPServer:
    """Bind localhost by default. Port 0 is allowed for tests."""
    state = health or HealthState()
    handler = make_handler(registry, state, logger, hub=hub)
    server = ThreadingHTTPServer((bind, port), handler)
    thread = threading.Thread(target=server.serve_forever, name="hotflow-metrics", daemon=True)
    thread.start()
    _SERVERS.append(server)
    return server


def stop_metrics_server(server: ThreadingHTTPServer | None = None) -> None:
    targets = [server] if server is not None else list(_SERVERS)
    for item in targets:
        try:
            item.shutdown()
            item.server_close()
        except Exception:  # noqa: BLE001
            pass
        if item in _SERVERS:
            _SERVERS.remove(item)
