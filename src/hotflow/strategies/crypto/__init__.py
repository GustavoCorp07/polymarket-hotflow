"""Crypto adapter. TWAP hooks use official 30s/60s windows only."""

from __future__ import annotations

from hotflow.official import RTDS_TWAP_WINDOWS
from hotflow.types import MarketRecord


class CryptoStrategy:
    name = "crypto_updown"
    category = "crypto"

    def __init__(self, twap_window_seconds: int = 60) -> None:
        if twap_window_seconds not in RTDS_TWAP_WINDOWS:
            raise ValueError(
                f"twap_window_seconds must be one of {sorted(RTDS_TWAP_WINDOWS)} "
                "(official Chainlink/RTDS windows)"
            )
        self.twap_window_seconds = twap_window_seconds

    def accepts(self, market: MarketRecord) -> bool:
        return (market.category or "").lower() == "crypto"

    def experiment_fields(self) -> dict[str, str]:
        return {
            "strategy": self.name,
            "category": self.category,
            "twap_window_seconds": str(self.twap_window_seconds),
            "twap_source": "polymarket_rtds_chainlink",
        }
