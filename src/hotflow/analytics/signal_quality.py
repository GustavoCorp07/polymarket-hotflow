"""Parte 46 — persisted decision snapshot for audit (no secrets)."""

from __future__ import annotations

from typing import Any

from hotflow.features.microstructure import compact_microstructure
from hotflow.types import LiquidityStyle, Opportunity


def signal_quality(
    opp: Opportunity,
    *,
    decision: str,
    reason_codes: list[str],
    strategy: str,
    extras: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "market": opp.market_id,
        "strategy": strategy,
        "fair_probability": opp.edge.p_fair,
        "execution_price": opp.edge.market_price,
        "gross_edge": opp.edge.raw_edge,
        "expected_fee": opp.edge.fee_per_share,
        "expected_slippage": opp.edge.slippage,
        "latency_penalty": opp.edge.latency_haircut,
        "fill_penalty": opp.edge.fill_penalty,
        "net_edge": opp.edge.net_expected_edge,
        "confidence": opp.edge.confidence,
        "signal_half_life_ms": opp.signal_half_life_ms,
        "hot_market_score": opp.hms.score,
        "opportunity_score": opp.score,
        "style": opp.style.value if isinstance(opp.style, LiquidityStyle) else opp.style,
        "pnl_velocity": opp.pnl_velocity,
        "decision": decision,
        "reason_codes": reason_codes,
    }
    micro = None
    if extras and isinstance(extras.get("microstructure"), dict):
        micro = extras["microstructure"]
    compact = compact_microstructure(micro)
    if compact:
        payload["microstructure"] = compact
    return payload
