"""Parte 25 — regime labels. Strategies may enable/disable later; no live auto-switch."""

from __future__ import annotations

from enum import StrEnum

from hotflow.types import MarketRecord


class Regime(StrEnum):
    LOW_VOL = "low_volatility"
    NORMAL = "normal"
    HIGH_VOL = "high_volatility"
    NEAR_RESOLUTION = "near_resolution"
    PRE_GAME = "pre_game"
    LIVE = "live"
    FORECAST_UNCERTAIN = "forecast_uncertainty_high"


def classify_crypto(market: MarketRecord, ttr_seconds: float | None) -> Regime:
    if ttr_seconds is not None and 0 < ttr_seconds < 900:
        return Regime.NEAR_RESOLUTION
    spread = market.spread or 0.0
    if spread >= 0.08:
        return Regime.HIGH_VOL
    if spread <= 0.015:
        return Regime.LOW_VOL
    return Regime.NORMAL


def classify_sports(live: bool | None) -> Regime:
    return Regime.LIVE if live else Regime.PRE_GAME


def classify_weather(ensemble_wide: bool = False) -> Regime:
    return Regime.FORECAST_UNCERTAIN if ensemble_wide else Regime.NORMAL
