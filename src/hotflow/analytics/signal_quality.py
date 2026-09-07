"""Parte 46 — persisted decision snapshot for audit (no secrets).

Every PAPER evaluate writes this shape. Missing fields are null (never invented
zeros). Extra keys (style, fill_penalty, compact microstructure) are omitted
when the evaluate path has not computed them yet.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from hotflow.features.microstructure import compact_microstructure
from hotflow.reason_codes import ReasonCode
from hotflow.types import EdgeBreakdown, HotMarketResult, LiquidityStyle, Opportunity

# Mission Parte 46 contract. Always present on the persisted JSON.
PARTE46_REQUIRED_KEYS: tuple[str, ...] = (
    "market",
    "strategy",
    "fair_probability",
    "execution_price",
    "gross_edge",
    "expected_fee",
    "expected_slippage",
    "latency_penalty",
    "net_edge",
    "confidence",
    "signal_half_life_ms",
    "hot_market_score",
    "opportunity_score",
    "decision",
    "reason_codes",
)


def _micro_blob(extras: Mapping[str, Any] | None) -> dict[str, Any]:
    if not extras:
        return {}
    raw = extras.get("microstructure")
    return raw if isinstance(raw, dict) else {}


def spread_regime_label(extras: Mapping[str, Any] | None) -> str | None:
    """Persisted Parte 45 label, or None when the book/regime is missing."""
    regime = _micro_blob(extras).get("spread_regime")
    if isinstance(regime, dict):
        label = regime.get("label")
        if label in (None, "", "N/A"):
            return None
        return str(label)
    if isinstance(regime, str) and regime and regime != "N/A":
        return regime
    return None


def impact_exhausted(extras: Mapping[str, Any] | None) -> bool | None:
    """True when the probe walk left the book; None when exhaustion was not measured."""
    micro = _micro_blob(extras)
    buy = micro.get("exhausted_buy")
    sell = micro.get("exhausted_sell")
    if buy is None and sell is None:
        return None
    return bool(buy) or bool(sell)


def tag_skip_reasons(
    primary: str | None,
    extras: Mapping[str, Any] | None = None,
    *,
    extra_codes: Sequence[str] | None = None,
    accepted: bool = False,
) -> list[str]:
    """Primary decision reason plus audit-only microstructure slices.

    Slice tags use existing codes when they already describe the fact
    (`SPREAD_TOO_LARGE` for a wide regime). `IMPACT_EXHAUSTED` is the one new
    code: probe notional walked off the book — not Gamma `LOW_LIQUIDITY` and
    not a default risk veto (`max_impact` / `min_top_depth` stay off).
    """
    codes: list[str] = []

    def _add(code: str | None) -> None:
        if not code:
            return
        text = str(code)
        if text and text not in codes:
            codes.append(text)

    _add(primary)
    for code in extra_codes or []:
        _add(str(code) if code is not None else None)
    if accepted:
        return codes

    label = spread_regime_label(extras)
    if label == "wide":
        _add(ReasonCode.SPREAD_TOO_LARGE)
    exhausted = impact_exhausted(extras)
    if exhausted is True:
        _add(ReasonCode.IMPACT_EXHAUSTED)
    return codes


def _edge_from(
    opp: Opportunity | None,
    edge: EdgeBreakdown | None,
) -> EdgeBreakdown | None:
    if opp is not None:
        return opp.edge
    return edge


def signal_quality(
    opp: Opportunity | None = None,
    *,
    decision: str,
    reason_codes: list[str],
    strategy: str,
    extras: dict[str, Any] | None = None,
    market_id: str | None = None,
    edge: EdgeBreakdown | None = None,
    hms: HotMarketResult | float | None = None,
    opportunity_score: float | None = None,
    signal_half_life_ms: float | None = None,
) -> dict[str, Any]:
    """Build the Parte 46 audit record. Nulls mean the path had no value yet."""
    resolved_edge = _edge_from(opp, edge)
    market = (
        (opp.market_id if opp is not None else None)
        or market_id
        or (str(extras.get("market_id")) if extras and extras.get("market_id") else None)
    )
    hms_score: float | None
    if opp is not None:
        hms_score = opp.hms.score
    elif isinstance(hms, HotMarketResult):
        hms_score = hms.score
    else:
        hms_score = hms

    opp_score = opportunity_score
    if opp_score is None and opp is not None:
        opp_score = opp.score

    half_life = signal_half_life_ms
    if half_life is None and opp is not None:
        half_life = opp.signal_half_life_ms

    payload: dict[str, Any] = {
        "market": market,
        "strategy": strategy,
        "fair_probability": resolved_edge.p_fair if resolved_edge is not None else None,
        "execution_price": resolved_edge.market_price if resolved_edge is not None else None,
        "gross_edge": resolved_edge.raw_edge if resolved_edge is not None else None,
        "expected_fee": resolved_edge.fee_per_share if resolved_edge is not None else None,
        "expected_slippage": resolved_edge.slippage if resolved_edge is not None else None,
        "latency_penalty": resolved_edge.latency_haircut if resolved_edge is not None else None,
        "net_edge": resolved_edge.net_expected_edge if resolved_edge is not None else None,
        "confidence": resolved_edge.confidence if resolved_edge is not None else None,
        "signal_half_life_ms": half_life,
        "hot_market_score": hms_score,
        "opportunity_score": opp_score,
        "decision": decision,
        "reason_codes": list(reason_codes),
    }
    if resolved_edge is not None:
        payload["fill_penalty"] = resolved_edge.fill_penalty
    if opp is not None:
        style = opp.style.value if isinstance(opp.style, LiquidityStyle) else opp.style
        payload["style"] = style
        payload["pnl_velocity"] = opp.pnl_velocity
    compact = compact_microstructure(_micro_blob(extras) or None)
    if compact:
        payload["microstructure"] = compact
        label = spread_regime_label(extras)
        if label is not None:
            payload["spread_regime"] = label
        exhausted = impact_exhausted(extras)
        if exhausted is not None:
            payload["impact_exhausted"] = exhausted
    return payload
