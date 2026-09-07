"""Labeled long PAPER soak: ≥50 closed ledger trades with MARK between fills.

Prices are fixture arguments (`origin=synthetic_official_shape`). This module
never invents a venue print or bypasses kill-switch / risk after each close.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from hotflow.portfolio.ledger import LedgerEventKind
from hotflow.portfolio.session import PaperSession
from hotflow.types import Side

ORIGIN = "synthetic_official_shape"
DEFAULT_TARGET_CLOSES = 50


@dataclass(frozen=True)
class LabeledLot:
    index: int
    token_id: str
    market_id: str
    size: float
    open_price: float
    mark_adverse: float
    mark_favorable: float
    close_price: float
    fee: float
    origin: str = ORIGIN

    def as_dict(self) -> dict[str, Any]:
        return {
            "index": self.index,
            "token_id": self.token_id,
            "market_id": self.market_id,
            "size": self.size,
            "open_price": self.open_price,
            "mark_adverse": self.mark_adverse,
            "mark_favorable": self.mark_favorable,
            "close_price": self.close_price,
            "fee": self.fee,
            "origin": self.origin,
        }


def labeled_round_trips(n: int = DEFAULT_TARGET_CLOSES) -> list[LabeledLot]:
    """Deterministic labeled lots. Not live markets."""
    if n < 1:
        raise ValueError("target closes must be >= 1")
    lots: list[LabeledLot] = []
    for index in range(n):
        win = index % 2 == 0
        lots.append(
            LabeledLot(
                index=index,
                token_id=f"soak-lot-{index:04d}",
                market_id=f"paper-long-soak-{index:04d}",
                size=5.0,
                open_price=0.40,
                mark_adverse=0.37,
                mark_favorable=0.44,
                close_price=0.42 if win else 0.39,
                fee=0.0,
            )
        )
    return lots


def run_labeled_long_soak(
    session: PaperSession,
    *,
    target_closes: int = DEFAULT_TARGET_CLOSES,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Open → MARK → MARK → FLATTEN for each labeled lot. Stop if kill trips."""
    start = now or datetime(2026, 9, 7, 12, 0, tzinfo=UTC)
    lots = labeled_round_trips(target_closes)
    applied = 0
    stopped = None
    for lot in lots:
        if session.pipe.kills.tripped:
            stopped = str(session.pipe.kills.reason.value if session.pipe.kills.reason else "kill")
            break
        t0 = start + timedelta(seconds=15 * lot.index)
        session.ledger.apply_fill(
            token_id=lot.token_id,
            market_id=lot.market_id,
            side=Side.BUY,
            size=lot.size,
            price=lot.open_price,
            fee=0.0,
            note="long_soak_open",
            ts=t0,
        )
        session.ledger.mark(
            lot.token_id,
            lot.mark_adverse,
            market_id=lot.market_id,
            ts=t0 + timedelta(seconds=2),
            note="long_soak_mark_adverse",
        )
        session.ledger.mark(
            lot.token_id,
            lot.mark_favorable,
            market_id=lot.market_id,
            ts=t0 + timedelta(seconds=4),
            note="long_soak_mark_favorable",
        )
        session.marks[lot.token_id] = lot.close_price
        closed = session.ledger.apply_fill(
            token_id=lot.token_id,
            market_id=lot.market_id,
            side=Side.SELL,
            size=lot.size,
            price=lot.close_price,
            fee=lot.fee,
            note="long_soak_close",
            kind=LedgerEventKind.FLATTEN,
            ts=t0 + timedelta(seconds=10),
        )
        if closed.closed:
            session.obs.metrics.note_closed_trade(closed.realized_delta)
            applied += 1
        session.pipe.risk.sync_from_ledger(session.ledger.snapshot())
        session.pipe.risk.enforce_session_limits()
        session.obs.publish_ledger(session.ledger.snapshot())
    snap = session.ledger.snapshot()
    return {
        "origin": ORIGIN,
        "long_soak": True,
        "target_closes": target_closes,
        "closed_count": snap.closed_count,
        "lots_applied": applied,
        "fail_safe": True,
        "live": False,
        "auto_disable": False,
        "stopped_reason": stopped,
        "kill_switch": {
            "tripped": session.pipe.kills.tripped,
            "reason": session.pipe.kills.reason.value if session.pipe.kills.reason else None,
        },
        "note": "Labeled synthetic official-shape lots. Prices are fixture arguments, not venue prints.",
    }
