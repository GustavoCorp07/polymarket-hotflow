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

# Official RTDS TWAP topics (not a homemade TWAP)
RTDS_TWAP_30 = "crypto_prices_twap_thirty"
RTDS_TWAP_60 = "crypto_prices_twap_sixty"
RTDS_TWAP_WINDOWS = frozenset({30, 60})

KIMI_BASE_URL = "https://api.moonshot.ai/v1"
KIMI_MODEL = "kimi-k3"
KIMI_REASONING = frozenset({"low", "high", "max"})
