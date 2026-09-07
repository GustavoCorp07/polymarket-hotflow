"""Injectable public HTTP failures. No live sockets."""

from __future__ import annotations

import httpx


def injected_async_client(
    *,
    status: int | None = None,
    timeout: bool = False,
    base_url: str = "https://gamma-api.polymarket.com",
) -> httpx.AsyncClient:
    def handler(request: httpx.Request) -> httpx.Response:
        if timeout:
            raise httpx.TimeoutException("injected timeout", request=request)
        code = 500 if status is None else status
        return httpx.Response(code, json={"error": "injected", "status": code})

    return httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url=base_url)
