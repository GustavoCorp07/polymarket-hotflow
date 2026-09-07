from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from typing import Any

_SECRET_KEYS = frozenset(
    {
        "api_key",
        "secret",
        "passphrase",
        "private_key",
        "poly_api_key",
        "poly_api_secret",
        "moonshot_api_key",
        "kimi_api_key",
        "authorization",
    }
)


def _scrub(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: "[REDACTED]" if str(key).lower() in _SECRET_KEYS else _scrub(val)
            for key, val in value.items()
        }
    if isinstance(value, list):
        return [_scrub(item) for item in value]
    return value


class JsonLogger:
    def __init__(self, name: str = "hotflow") -> None:
        self.logger = logging.getLogger(name)

    def emit(self, event: str, **fields: Any) -> None:
        record = {"ts": datetime.now(UTC).isoformat(), "event": event, **_scrub(fields)}
        self.logger.info(json.dumps(record, default=str))
