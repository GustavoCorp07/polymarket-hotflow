"""Parte 23 — risk-adjusted expected PnL velocity. Not maximized in isolation."""

from __future__ import annotations


def pnl_velocity(expected_net_pnl: float, holding_ms: float, variance: float) -> float:
    holding_s = max(holding_ms / 1000.0, 1e-3)
    raw = expected_net_pnl / holding_s
    denom = max(variance, 1e-6) ** 0.5
    return raw / denom
