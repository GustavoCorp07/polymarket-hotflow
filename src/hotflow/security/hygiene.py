"""Committed-secret guards. Values never belong in git or reports."""

from __future__ import annotations

from pathlib import Path

PLACEHOLDER_ENV_KEYS = (
    "KIMI_API_KEY",
    "MOONSHOT_API_KEY",
    "POLYMARKET_PRIVATE_KEY",
    "POLY_API_KEY",
    "POLY_API_SECRET",
    "POLY_PASSPHRASE",
    "CHAINLINK_CLIENT_ID",
    "CHAINLINK_CLIENT_SECRET",
)

COLD_PATH_ONLY = ("KIMI_API_KEY", "MOONSHOT_API_KEY")


def env_example_secret_values(path: str | Path = ".env.example") -> dict[str, str]:
    filled: dict[str, str] = {}
    text = Path(path).read_text(encoding="utf-8")
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        if key in PLACEHOLDER_ENV_KEYS and value.strip():
            filled[key] = value.strip()
    return filled
