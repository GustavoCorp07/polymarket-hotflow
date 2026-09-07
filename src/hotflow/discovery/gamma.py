"""Gamma public HTTP client. Paths from docs.polymarket.com only."""

from __future__ import annotations

import json
from typing import Any

import httpx

from hotflow.official import GAMMA_BASE, GAMMA_EVENTS, GAMMA_MARKETS


def _as_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _as_bool(value: Any) -> bool | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"true", "1", "yes"}:
            return True
        if lowered in {"false", "0", "no"}:
            return False
    return bool(value)


def _parse_json_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item) for item in value]
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return []
        try:
            parsed = json.loads(text)
            if isinstance(parsed, list):
                return [str(item) for item in parsed]
        except json.JSONDecodeError:
            return [part.strip() for part in text.split(",") if part.strip()]
    return []


def tag_labels(raw: Any) -> list[str]:
    labels: list[str] = []
    if not raw:
        return labels
    if isinstance(raw, list):
        for item in raw:
            if isinstance(item, str):
                labels.append(item)
            elif isinstance(item, dict):
                label = item.get("label") or item.get("slug") or item.get("name")
                if label:
                    labels.append(str(label))
    return labels


class GammaClient:
    def __init__(self, base_url: str = GAMMA_BASE, client: httpx.AsyncClient | None = None) -> None:
        self.base_url = base_url.rstrip("/")
        self._client = client
        self._owns = client is None

    async def __aenter__(self) -> GammaClient:
        if self._client is None:
            self._client = httpx.AsyncClient(base_url=self.base_url, timeout=20.0)
        return self

    async def __aexit__(self, *exc: object) -> None:
        if self._owns and self._client is not None:
            await self._client.aclose()

    @property
    def client(self) -> httpx.AsyncClient:
        if self._client is None:
            raise RuntimeError("GammaClient must be used as an async context manager")
        return self._client

    async def list_markets(
        self,
        *,
        closed: bool = False,
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        response = await self.client.get(
            GAMMA_MARKETS,
            params={"closed": str(closed).lower(), "limit": limit, "offset": offset},
        )
        response.raise_for_status()
        return _gamma_list(response.json(), "Unexpected Gamma /markets payload shape")

    async def list_events(
        self,
        *,
        closed: bool | None = False,
        limit: int = 50,
        offset: int = 0,
        tag_slug: str | None = None,
    ) -> list[dict[str, Any]]:
        """Official GET /events. tag_slug is documented on list-events."""
        params: dict[str, Any] = {"limit": limit, "offset": offset}
        if closed is not None:
            params["closed"] = str(closed).lower()
        if tag_slug:
            params["tag_slug"] = tag_slug
        response = await self.client.get(GAMMA_EVENTS, params=params)
        response.raise_for_status()
        return _gamma_list(response.json(), "Unexpected Gamma /events payload shape")

    async def get_event(self, event_id: str) -> dict[str, Any]:
        response = await self.client.get(f"{GAMMA_EVENTS}/{event_id}")
        response.raise_for_status()
        data = response.json()
        if not isinstance(data, dict):
            raise ValueError("Unexpected Gamma /events payload")
        return data

    async def get_event_by_slug(self, slug: str) -> dict[str, Any]:
        """Official GET /events/slug/{slug}."""
        response = await self.client.get(f"{GAMMA_EVENTS}/slug/{slug}")
        response.raise_for_status()
        data = response.json()
        if not isinstance(data, dict):
            raise ValueError("Unexpected Gamma /events/slug payload")
        return data

    async def get_market(self, market_id: str) -> dict[str, Any]:
        """Public GET /markets/{id} — same host and fields as list-markets."""
        response = await self.client.get(f"{GAMMA_MARKETS}/{market_id}")
        response.raise_for_status()
        data = response.json()
        if not isinstance(data, dict):
            raise ValueError("Unexpected Gamma /markets/{id} payload")
        return data


def _gamma_list(payload: Any, error: str) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        for key in ("data", "markets", "items", "events"):
            maybe = payload.get(key)
            if isinstance(maybe, list):
                return maybe
    raise ValueError(error)


# Re-export parsers for the scanner
as_float = _as_float
as_bool = _as_bool
parse_json_list = _parse_json_list
