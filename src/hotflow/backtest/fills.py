"""Backtest fill model. Assumptions are documented paper rules, not venue math.

Fees use the official taker formula on a dated fixture schedule.
Makers are never charged (docs.polymarket.com/trading/fees).
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from hotflow.fairvalue.fees import UnknownFeesError, taker_fee_per_share, walk_slippage
from hotflow.reason_codes import ReasonCode
from hotflow.types import FeeSchedule, LiquidityStyle, OrderBook, Side


@dataclass(frozen=True)
class FillAssumptions:
    """Paper simulation knobs. Not official CLOB parameters."""

    latency_ms: float = 50.0
    taker_delay_ms: float = 80.0
    queue_penalty: float = 0.15
    partial_fill_ratio: float = 0.55
    maker_fill_probability: float = 0.35
    reject_on_gap: bool = True
    note: str = (
        "latency + taker_delay shift fill time only. queue_penalty and "
        "partial_fill_ratio are paper assumptions. maker_fill_probability "
        "comes from config.maker_taker. Fees are not hardcoded."
    )


def fill_delay(style: LiquidityStyle, assumptions: FillAssumptions) -> timedelta:
    extra = assumptions.taker_delay_ms if style == LiquidityStyle.TAKER else 0.0
    return timedelta(milliseconds=assumptions.latency_ms + extra)


def deterministic_unit(seed: str) -> float:
    digest = hashlib.sha256(seed.encode("utf-8")).hexdigest()
    return int(digest[:8], 16) / float(0xFFFFFFFF)


@dataclass
class FillResult:
    filled: bool
    reason: str
    size: float = 0.0
    price: float | None = None
    fee: float = 0.0
    slippage: float = 0.0
    style: str = LiquidityStyle.TAKER.value
    detail: str = ""
    fill_ts: datetime | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "filled": self.filled,
            "reason": self.reason,
            "size": self.size,
            "price": self.price,
            "fee": self.fee,
            "slippage": self.slippage,
            "style": self.style,
            "detail": self.detail,
            "fill_ts": self.fill_ts.isoformat() if self.fill_ts else None,
        }


def _walk_fill(levels: list[tuple[float, float]], shares: float) -> tuple[float, float]:
    remaining = shares
    cost = 0.0
    filled = 0.0
    for price, size in levels:
        take = min(remaining, size)
        cost += take * price
        filled += take
        remaining -= take
        if remaining <= 1e-12:
            break
    avg = (cost / filled) if filled > 0 else 0.0
    return filled, avg


def simulate_execution(
    *,
    side: Side,
    style: LiquidityStyle,
    intended_shares: float,
    book: OrderBook | None,
    fees: FeeSchedule,
    assumptions: FillAssumptions,
    seed: str,
    fill_ts: datetime | None = None,
    gap: bool = False,
) -> FillResult:
    if gap and assumptions.reject_on_gap:
        return FillResult(filled=False, reason=ReasonCode.DATA_GAP, style=style.value, fill_ts=fill_ts)
    if book is None:
        return FillResult(filled=False, reason=ReasonCode.NO_BOOK, style=style.value, fill_ts=fill_ts)
    levels = [(lvl.price, lvl.size) for lvl in (book.asks if side == Side.BUY else book.bids)]
    if not levels or intended_shares <= 0:
        return FillResult(filled=False, reason=ReasonCode.NO_BOOK, style=style.value, fill_ts=fill_ts)

    if style == LiquidityStyle.MAKER:
        if deterministic_unit(seed) >= assumptions.maker_fill_probability:
            return FillResult(
                filled=False,
                reason=ReasonCode.ORDER_REJECTED,
                style=style.value,
                detail="maker_unfilled",
                fill_ts=fill_ts,
            )
        join = book.best_bid if side == Side.BUY else book.best_ask
        if join is None:
            return FillResult(filled=False, reason=ReasonCode.NO_BOOK, style=style.value, fill_ts=fill_ts)
        visible = levels[0][1]
        size = min(intended_shares, visible) * (1.0 - assumptions.queue_penalty)
        size *= assumptions.partial_fill_ratio
        if size <= 1e-9:
            return FillResult(filled=False, reason=ReasonCode.ORDER_REJECTED, style=style.value, fill_ts=fill_ts)
        return FillResult(
            filled=True,
            reason=ReasonCode.OK,
            size=size,
            price=join,
            fee=0.0,
            slippage=0.0,
            style=style.value,
            detail="queue_penalty_applied",
            fill_ts=fill_ts,
        )

    target = intended_shares * assumptions.partial_fill_ratio
    filled, avg = _walk_fill(levels, target)
    if filled <= 1e-9:
        return FillResult(filled=False, reason=ReasonCode.ORDER_REJECTED, style=style.value, fill_ts=fill_ts)
    slip = walk_slippage(levels, filled, is_buy=(side == Side.BUY))
    try:
        fee = taker_fee_per_share(avg, fees) * filled
    except UnknownFeesError:
        return FillResult(filled=False, reason=ReasonCode.UNKNOWN_FEES, style=style.value, fill_ts=fill_ts)
    return FillResult(
        filled=True,
        reason=ReasonCode.OK,
        size=filled,
        price=avg,
        fee=fee,
        slippage=slip,
        style=style.value,
        fill_ts=fill_ts,
    )
