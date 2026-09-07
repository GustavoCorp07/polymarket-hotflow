"""Official Polymarket and Kimi endpoints only.

Values here are copied from docs retrieved 2026-09-07:
https://docs.polymarket.com/getting-started/api
https://docs.polymarket.com/market-data/realtime-data
https://docs.polymarket.com/market-data/chainlink-twap
https://platform.kimi.ai/docs/guide/kimi-k3-quickstart.md
"""

from __future__ import annotations

import os

GAMMA_BASE = os.environ.get("HOTFLOW_GAMMA_BASE", "https://gamma-api.polymarket.com")
CLOB_BASE = os.environ.get("HOTFLOW_CLOB_BASE", "https://clob.polymarket.com")
DATA_API_BASE = "https://data-api.polymarket.com"

# REST
GAMMA_MARKETS = "/markets"
GAMMA_EVENTS = "/events"
CLOB_BOOK = "/book"
CLOB_TICK_SIZE = "/tick-size"
CLOB_FEE_RATE = "/fee-rate"
CLOB_MARKET = "/clob-markets/{condition_id}"

# WebSockets
MARKET_WS = "wss://ws-subscriptions-clob.polymarket.com/ws/market"
USER_WS = "wss://ws-subscriptions-clob.polymarket.com/ws/user"
RTDS_WS = "wss://ws-live-data.polymarket.com"
SPORTS_WS = "wss://sports-api.polymarket.com/ws"

# Official heartbeats
CLOB_WS_PING_S = 10
RTDS_PING_S = 5
# Sports WS: server sends ping every 5s; client replies pong within 10s.
# https://docs.polymarket.com/market-data/realtime-data
SPORTS_PING_S = 5
SPORTS_PONG_DEADLINE_S = 10
SPORTS_SERVER_PING = "ping"
SPORTS_CLIENT_PONG = "pong"

# Leagues that appear in the official Sports WS status table (do not invent).
SPORTS_DOCUMENTED_LEAGUES = frozenset(
    {"NFL", "NHL", "MLB", "NBA", "CBB", "CFB", "Soccer", "Esports", "Tennis"}
)

# Official RTDS TWAP topics (not a homemade TWAP)
# https://docs.polymarket.com/market-data/chainlink-twap
RTDS_TWAP_30 = "crypto_prices_twap_thirty"
RTDS_TWAP_60 = "crypto_prices_twap_sixty"
RTDS_TWAP_SDK_TOPIC = "prices.crypto.chainlink.twap"
RTDS_TWAP_WINDOWS = frozenset({30, 60})

# Chainlink symbol form documented on
# https://docs.polymarket.com/market-data/realtime-data — do not invent extras.
RTDS_CHAINLINK_SYMBOLS = frozenset({"btc/usd", "eth/usd", "sol/usd", "xrp/usd"})
RTDS_CHAINLINK_SYMBOL_ALIASES = {
    "btc": "btc/usd",
    "bitcoin": "btc/usd",
    "eth": "eth/usd",
    "ethereum": "eth/usd",
    "sol": "sol/usd",
    "solana": "sol/usd",
    "xrp": "xrp/usd",
}

KIMI_BASE_URL = "https://api.moonshot.ai/v1"
KIMI_MODEL = "kimi-k3"
KIMI_REASONING = frozenset({"low", "high", "max"})


def rtds_twap_topic(window_seconds: int) -> str:
    """Map an official lookback window to the raw RTDS topic. Raises on anything else."""
    if window_seconds == 30:
        return RTDS_TWAP_30
    if window_seconds == 60:
        return RTDS_TWAP_60
    raise ValueError(
        f"window_seconds must be one of {sorted(RTDS_TWAP_WINDOWS)} "
        "(official Chainlink/RTDS lookbacks only)"
    )


def rtds_twap_filter(symbol: str) -> str:
    """Exact compact JSON filter from official docs — no spaces."""
    return f'{{"symbol":"{symbol.lower()}"}}'


def rtds_twap_subscribe_payload(*, window_seconds: int, symbol: str | None = None) -> dict:
    """Official RTDS subscribe frame for one Chainlink TWAP window."""
    if symbol and symbol.lower() not in RTDS_CHAINLINK_SYMBOLS:
        raise ValueError(f"symbol {symbol!r} is not in the documented Chainlink set")
    subscription: dict = {"topic": rtds_twap_topic(window_seconds), "type": "update"}
    if symbol:
        subscription["filters"] = rtds_twap_filter(symbol)
    return {"action": "subscribe", "subscriptions": [subscription]}


def rtds_twap_subscribe_documented(
    *,
    windows: list[int] | None = None,
    symbols: list[str] | None = None,
) -> dict:
    """Subscribe to official 30s/60s topics. Omit filters when symbols is empty
    (official: receive every pair, then filter in-process to documented symbols).
    """
    chosen_windows = list(windows) if windows else sorted(RTDS_TWAP_WINDOWS)
    subscriptions: list[dict] = []
    if symbols:
        for symbol in symbols:
            if symbol.lower() not in RTDS_CHAINLINK_SYMBOLS:
                raise ValueError(f"symbol {symbol!r} is not in the documented Chainlink set")
            for window in chosen_windows:
                sub = rtds_twap_subscribe_payload(window_seconds=window, symbol=symbol.lower())
                subscriptions.extend(sub["subscriptions"])
    else:
        for window in chosen_windows:
            subscriptions.extend(rtds_twap_subscribe_payload(window_seconds=window)["subscriptions"])
    return {"action": "subscribe", "subscriptions": subscriptions}
