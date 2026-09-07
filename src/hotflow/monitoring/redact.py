"""Secret redaction for logs, alerts, and health payloads.

Never treat public CLOB identifiers (`token_id`, `market_id`, …) as secrets.
Wallet *addresses* stay visible; private keys, seeds, and API material do not.
"""

from __future__ import annotations

import re
from typing import Any

REDACTED = "[REDACTED]"

# Exact keys after lowercasing and replacing '-' with '_'.
SECRET_KEYS = frozenset(
    {
        "api_key",
        "apikey",
        "api_secret",
        "secret",
        "passphrase",
        "password",
        "passwd",
        "private_key",
        "privatekey",
        "signing_key",
        "poly_api_key",
        "poly_api_secret",
        "poly_passphrase",
        "poly_secret",
        "moonshot_api_key",
        "kimi_api_key",
        "authorization",
        "auth",
        "bearer",
        "access_token",
        "refresh_token",
        "id_token",
        "auth_token",
        "api_token",
        "mnemonic",
        "seed",
        "seed_phrase",
        "wallet_key",
        "wallet_secret",
        "wallet_private_key",
        "l2_passphrase",
        "clob_api_key",
        "clob_secret",
        "chainlink_client_secret",
        "chainlink_client_id",
        "polymarket_private_key",
    }
)

# Public venue identifiers — never redact on key name alone.
SAFE_ID_KEYS = frozenset(
    {
        "token_id",
        "tokenid",
        "token_ids",
        "tokenids",
        "market_id",
        "condition_id",
        "client_order_id",
        "venue_order_id",
        "session_id",
        "request_id",
        "signal_id",
        "trade_id",
        "game_id",
        "backtest_id",
    }
)

_SECRET_FRAGMENTS = (
    "private_key",
    "api_secret",
    "api_key",
    "passphrase",
    "password",
    "mnemonic",
    "seed_phrase",
    "authorization",
    "signing_key",
)

_PEM_RE = re.compile(r"-----BEGIN ([A-Z0-9]+ )?PRIVATE KEY-----")
_BEARER_RE = re.compile(r"(?i)\bbearer\s+\S+")


def normalize_key(key: Any) -> str:
    return str(key).lower().replace("-", "_")


def is_secret_key(key: Any) -> bool:
    norm = normalize_key(key)
    if norm in SAFE_ID_KEYS:
        return False
    if norm in SECRET_KEYS:
        return True
    if norm.endswith("_id") or norm.endswith("_ids"):
        return False
    return any(fragment in norm for fragment in _SECRET_FRAGMENTS)


def looks_secret_value(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    text = value.strip()
    if not text:
        return False
    if _PEM_RE.search(text):
        return True
    if _BEARER_RE.search(text):
        return True
    return False


def redact_string(value: str) -> str:
    if looks_secret_value(value):
        return REDACTED
    return value


def redact(value: Any, *, key: Any | None = None) -> Any:
    """Recursively replace secret keys and PEM/bearer material."""
    if key is not None and is_secret_key(key):
        return REDACTED
    if isinstance(value, dict):
        return {k: redact(v, key=k) for k, v in value.items()}
    if isinstance(value, list):
        return [redact(item) for item in value]
    if isinstance(value, tuple):
        return tuple(redact(item) for item in value)
    if isinstance(value, str):
        return redact_string(value)
    return value
