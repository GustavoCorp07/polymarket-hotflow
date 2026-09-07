"""SHADOW mode: real-data decisions logged, never transmitted."""

from __future__ import annotations

from typing import Any

from hotflow.config import HotflowConfig
from hotflow.pipeline import PaperPipeline
from hotflow.reason_codes import ReasonCode
from hotflow.types import MarketRecord, Side


def attach_shadow_fields(
    result: dict[str, Any],
    *,
    next_price: float | None = None,
) -> dict[str, Any]:
    """Fill would_* / expected_price / actual_price_after_signal. No orders."""
    opp_raw = result.get("opportunity")
    opportunity: dict[str, Any] = opp_raw if isinstance(opp_raw, dict) else {}
    edge_raw = result.get("edge")
    edge: dict[str, Any] = edge_raw if isinstance(edge_raw, dict) else {}
    if not edge:
        nested = opportunity.get("edge")
        edge = nested if isinstance(nested, dict) else {}
    side = str(result.get("side") or opportunity.get("side") or Side.BUY.value)
    expected = result.get("expected_price")
    if expected is None:
        expected = edge.get("market_price")
    payload = dict(result)
    payload["would_buy"] = side == Side.BUY.value and result.get("reason") == ReasonCode.SHADOW_MODE
    payload["would_sell"] = side == Side.SELL.value and result.get("reason") == ReasonCode.SHADOW_MODE
    payload["expected_price"] = expected
    payload["actual_price_after_signal"] = next_price
    if payload.get("simulated_fill") is None:
        payload["simulated_fill"] = {
            "sent": False,
            "style": result.get("style") or opportunity.get("style"),
            "shares": result.get("shares") or opportunity.get("intended_shares"),
            "fee_per_share": edge.get("fee_per_share"),
        }
    return payload


def run_shadow(
    config: HotflowConfig,
    markets: list[MarketRecord],
    *,
    next_prices: dict[str, float] | None = None,
    p_info: float | None = None,
    pipeline: PaperPipeline | None = None,
) -> list[dict[str, Any]]:
    config.trading.mode = "shadow"
    config.trading.shadow = True
    pipe = pipeline or PaperPipeline(config, use_twap_fixtures=True)
    rows: list[dict[str, Any]] = []
    prices = next_prices or {}
    for market in markets:
        result = pipe.evaluate_market(market, p_info=p_info)
        rows.append(attach_shadow_fields(result, next_price=prices.get(market.market_id)))
    return rows
