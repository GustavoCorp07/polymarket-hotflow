"""Public CLOB HTTP. Paths from docs.polymarket.com only."""

from __future__ import annotations

from typing import Any

import httpx

from hotflow.official import CLOB_BASE, CLOB_BOOK, CLOB_FEE_RATE, CLOB_MARKET, CLOB_TICK_SIZE
from hotflow.types import BookLevel, FeeSchedule, OrderBook


def _num(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _levels(rows: Any, *, reverse: bool) -> list[BookLevel]:
    out: list[BookLevel] = []
    if not isinstance(rows, list):
        return out
    for row in rows:
        if isinstance(row, dict):
            price = _num(row.get("price"))
            size = _num(row.get("size") or row.get("quantity"))
        elif isinstance(row, (list, tuple)) and len(row) >= 2:
            price = _num(row[0])
            size = _num(row[1])
        else:
            continue
        if price is None or size is None:
            continue
        out.append(BookLevel(price=price, size=size))
    out.sort(key=lambda level: level.price, reverse=reverse)
    return out


class ClobPublicClient:
    def __init__(self, base_url: str = CLOB_BASE, client: httpx.AsyncClient | None = None) -> None:
        self.base_url = base_url.rstrip("/")
        self._client = client
        self._owns = client is None

    async def __aenter__(self) -> ClobPublicClient:
        if self._client is None:
            self._client = httpx.AsyncClient(base_url=self.base_url, timeout=20.0)
        return self

    async def __aexit__(self, *exc: object) -> None:
        if self._owns and self._client is not None:
            await self._client.aclose()

    @property
    def client(self) -> httpx.AsyncClient:
        if self._client is None:
            raise RuntimeError("ClobPublicClient must be used as an async context manager")
        return self._client

    async def get_book(self, token_id: str, condition_id: str | None = None) -> OrderBook:
        response = await self.client.get(CLOB_BOOK, params={"token_id": token_id})
        response.raise_for_status()
        data = response.json()
        ts = data.get("timestamp")
        try:
            timestamp_ms = int(float(ts)) if ts is not None else None
        except (TypeError, ValueError):
            timestamp_ms = None
        return OrderBook(
            token_id=str(data.get("asset_id") or token_id),
            condition_id=data.get("market") or condition_id,
            bids=_levels(data.get("bids"), reverse=True),
            asks=_levels(data.get("asks"), reverse=False),
            min_order_size=_num(data.get("min_order_size")),
            tick_size=_num(data.get("tick_size")),
            timestamp_ms=timestamp_ms,
            source="clob_book",
        )

    async def get_tick_size(self, token_id: str) -> float | None:
        response = await self.client.get(CLOB_TICK_SIZE, params={"token_id": token_id})
        response.raise_for_status()
        data = response.json()
        return _num(data.get("minimum_tick_size"))

    async def get_fee_rate(self, token_id: str) -> int | None:
        """Official GET /fee-rate → base_fee in basis points."""
        response = await self.client.get(CLOB_FEE_RATE, params={"token_id": token_id})
        if response.status_code == 404:
            return None
        response.raise_for_status()
        data = response.json()
        raw = data.get("base_fee")
        return int(raw) if raw is not None else None

    async def get_clob_market(self, condition_id: str) -> dict[str, Any]:
        path = CLOB_MARKET.format(condition_id=condition_id)
        response = await self.client.get(path)
        response.raise_for_status()
        data = response.json()
        if not isinstance(data, dict):
            raise ValueError("Unexpected CLOB market payload")
        return data

    def fee_from_clob_market(self, payload: dict[str, Any]) -> FeeSchedule:
        details = payload.get("fd") or {}
        rate = _num(details.get("r")) if isinstance(details, dict) else None
        exponent = _num(details.get("e")) if isinstance(details, dict) else None
        taker_only = details.get("to") if isinstance(details, dict) else None
        enabled = rate is not None and rate > 0
        return FeeSchedule(
            enabled=enabled,
            rate=rate,
            exponent=exponent,
            taker_only=bool(taker_only) if taker_only is not None else True,
            maker_base_fee_bp=payload.get("mbf"),
            taker_base_fee_bp=payload.get("tbf"),
            source="clob_markets",
        )
