"""Paper session ledger. Equity is replayable from explicit events only.

Marks and flatten prices must be supplied by the caller (book mid or fill
price). This module never invents a venue balance or fill.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from hotflow.types import Side


class LedgerEventKind(StrEnum):
    FILL = "FILL"
    MARK = "MARK"
    FLATTEN = "FLATTEN"


@dataclass
class PositionState:
    token_id: str
    market_id: str
    qty: float = 0.0
    avg_cost: float = 0.0
    mark: float | None = None

    @property
    def unrealized(self) -> float:
        if self.mark is None or abs(self.qty) < 1e-12:
            return 0.0
        return self.qty * (self.mark - self.avg_cost)

    @property
    def notional(self) -> float:
        px = self.mark if self.mark is not None else self.avg_cost
        return abs(self.qty) * px


@dataclass
class LedgerEvent:
    kind: LedgerEventKind
    ts: datetime
    session_id: str
    market_id: str | None
    token_id: str | None
    side: str | None
    size: float
    price: float | None
    fee: float
    cash_delta: float
    realized_delta: float
    closed: bool
    client_order_id: str | None
    note: str
    cash_after: float
    equity_after: float

    def as_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind.value,
            "ts": self.ts.isoformat(),
            "session_id": self.session_id,
            "market_id": self.market_id,
            "token_id": self.token_id,
            "side": self.side,
            "size": self.size,
            "price": self.price,
            "fee": self.fee,
            "cash_delta": self.cash_delta,
            "realized_delta": self.realized_delta,
            "closed": self.closed,
            "client_order_id": self.client_order_id,
            "note": self.note,
            "cash_after": self.cash_after,
            "equity_after": self.equity_after,
        }


@dataclass
class LedgerSnapshot:
    session_id: str
    starting_cash: float
    cash: float
    realized_pnl: float
    unrealized_pnl: float
    fees: float
    equity: float
    peak_equity: float
    drawdown: float
    session_pnl: float
    win_rate: float
    expectancy: float
    closed_count: int
    positions: dict[str, dict[str, float]]
    event_count: int
    closed_pnls: list[float] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "starting_cash": self.starting_cash,
            "cash": self.cash,
            "realized_pnl": self.realized_pnl,
            "unrealized_pnl": self.unrealized_pnl,
            "fees": self.fees,
            "equity": self.equity,
            "peak_equity": self.peak_equity,
            "drawdown": self.drawdown,
            "session_pnl": self.session_pnl,
            "win_rate": self.win_rate,
            "expectancy": self.expectancy,
            "closed_count": self.closed_count,
            "positions": self.positions,
            "event_count": self.event_count,
            "closed_pnls": list(self.closed_pnls),
        }


class PaperLedger:
    def __init__(self, *, starting_cash: float, session_id: str = "local-paper") -> None:
        if starting_cash < 0:
            raise ValueError("starting_cash must be >= 0")
        self.session_id = session_id
        self.starting_cash = float(starting_cash)
        self.cash = float(starting_cash)
        self.realized_pnl = 0.0
        self.fees = 0.0
        self.peak_equity = float(starting_cash)
        self.positions: dict[str, PositionState] = {}
        self.events: list[LedgerEvent] = []
        self.closed_pnls: list[float] = []

    def equity(self) -> float:
        marked = 0.0
        for pos in self.positions.values():
            px = pos.mark if pos.mark is not None else pos.avg_cost
            marked += pos.qty * px
        return self.cash + marked

    def unrealized_pnl(self) -> float:
        return sum(pos.unrealized for pos in self.positions.values())

    def drawdown(self) -> float:
        eq = self.equity()
        if self.peak_equity <= 0:
            return 0.0
        return max(0.0, (self.peak_equity - eq) / self.peak_equity)

    def snapshot(self) -> LedgerSnapshot:
        eq = self.equity()
        closed = list(self.closed_pnls)
        wins = sum(1 for pnl in closed if pnl > 0)
        return LedgerSnapshot(
            session_id=self.session_id,
            starting_cash=self.starting_cash,
            cash=self.cash,
            realized_pnl=self.realized_pnl,
            unrealized_pnl=self.unrealized_pnl(),
            fees=self.fees,
            equity=eq,
            peak_equity=self.peak_equity,
            drawdown=self.drawdown(),
            session_pnl=eq - self.starting_cash,
            win_rate=(wins / len(closed)) if closed else 0.0,
            expectancy=(sum(closed) / len(closed)) if closed else 0.0,
            closed_count=len(closed),
            positions={
                token: {
                    "qty": pos.qty,
                    "avg_cost": pos.avg_cost,
                    "mark": pos.mark if pos.mark is not None else pos.avg_cost,
                    "unrealized": pos.unrealized,
                }
                for token, pos in self.positions.items()
                if abs(pos.qty) > 1e-12
            },
            event_count=len(self.events),
            closed_pnls=closed,
        )

    def mark(self, token_id: str, price: float, *, market_id: str | None = None) -> LedgerEvent:
        if price < 0:
            raise ValueError("mark price must be >= 0")
        pos = self.positions.get(token_id)
        if pos is None:
            pos = PositionState(token_id=token_id, market_id=market_id or "")
            self.positions[token_id] = pos
        if market_id:
            pos.market_id = market_id
        pos.mark = float(price)
        return self._commit(
            LedgerEventKind.MARK,
            market_id=pos.market_id or market_id,
            token_id=token_id,
            side=None,
            size=0.0,
            price=float(price),
            fee=0.0,
            cash_delta=0.0,
            realized_delta=0.0,
            closed=False,
            client_order_id=None,
            note="mark",
        )

    def apply_fill(
        self,
        *,
        token_id: str,
        market_id: str,
        side: Side | str,
        size: float,
        price: float,
        fee: float = 0.0,
        client_order_id: str | None = None,
        note: str = "fill",
        kind: LedgerEventKind = LedgerEventKind.FILL,
        ts: datetime | None = None,
    ) -> LedgerEvent:
        if size <= 0:
            raise ValueError("fill size must be > 0")
        if price < 0:
            raise ValueError("fill price must be >= 0")
        if fee < 0:
            raise ValueError("fee must be >= 0")
        side_val = side.value if isinstance(side, Side) else str(side)
        signed = size if side_val == Side.BUY.value else -size
        pos = self.positions.get(token_id)
        if pos is None:
            pos = PositionState(token_id=token_id, market_id=market_id)
            self.positions[token_id] = pos
        pos.market_id = market_id or pos.market_id
        realized = 0.0
        closed = False
        qty_before = pos.qty
        if qty_before == 0 or (qty_before > 0 and signed > 0) or (qty_before < 0 and signed < 0):
            new_qty = qty_before + signed
            if abs(new_qty) < 1e-12:
                pos.qty = 0.0
                pos.avg_cost = 0.0
            else:
                pos.avg_cost = (abs(qty_before) * pos.avg_cost + size * price) / abs(new_qty)
                pos.qty = new_qty
        else:
            closing = min(size, abs(qty_before))
            if qty_before > 0:
                realized = (price - pos.avg_cost) * closing
            else:
                realized = (pos.avg_cost - price) * closing
            realized -= fee
            closed = True
            remainder = size - closing
            leftover = qty_before + (closing if signed > 0 else -closing)
            if abs(leftover) < 1e-12:
                pos.qty = remainder if signed > 0 else -remainder
                pos.avg_cost = price if remainder > 1e-12 else 0.0
            else:
                pos.qty = leftover
            if remainder > 1e-12 and abs(pos.qty) > 1e-12 and leftover * signed > 0:
                pos.avg_cost = price
        pos.mark = price
        cash_delta = -signed * price - fee
        self.cash += cash_delta
        self.fees += fee
        self.realized_pnl += realized
        if closed:
            self.closed_pnls.append(realized)
        if abs(pos.qty) < 1e-12:
            pos.qty = 0.0
            pos.avg_cost = 0.0
        return self._commit(
            kind,
            market_id=market_id,
            token_id=token_id,
            side=side_val,
            size=size,
            price=price,
            fee=fee,
            cash_delta=cash_delta,
            realized_delta=realized,
            closed=closed,
            client_order_id=client_order_id,
            note=note,
            ts=ts,
        )

    def flatten(
        self,
        marks: dict[str, float],
        *,
        note: str = "session_flatten",
    ) -> list[LedgerEvent]:
        """Close open qty at caller-supplied marks. Missing marks are refused."""
        events: list[LedgerEvent] = []
        open_tokens = [token for token, pos in self.positions.items() if abs(pos.qty) > 1e-12]
        missing = [token for token in open_tokens if token not in marks]
        if missing:
            raise ValueError(f"flatten refuses invented marks for tokens={missing}")
        for token in open_tokens:
            pos = self.positions[token]
            side = Side.SELL if pos.qty > 0 else Side.BUY
            events.append(
                self.apply_fill(
                    token_id=token,
                    market_id=pos.market_id,
                    side=side,
                    size=abs(pos.qty),
                    price=float(marks[token]),
                    fee=0.0,
                    note=note,
                    kind=LedgerEventKind.FLATTEN,
                )
            )
        return events

    def _commit(
        self,
        kind: LedgerEventKind,
        *,
        market_id: str | None,
        token_id: str | None,
        side: str | None,
        size: float,
        price: float | None,
        fee: float,
        cash_delta: float,
        realized_delta: float,
        closed: bool,
        client_order_id: str | None,
        note: str,
        ts: datetime | None = None,
    ) -> LedgerEvent:
        eq = self.equity()
        self.peak_equity = max(self.peak_equity, eq)
        event = LedgerEvent(
            kind=kind,
            ts=ts or datetime.now(UTC),
            session_id=self.session_id,
            market_id=market_id,
            token_id=token_id,
            side=side,
            size=size,
            price=price,
            fee=fee,
            cash_delta=cash_delta,
            realized_delta=realized_delta,
            closed=closed,
            client_order_id=client_order_id,
            note=note,
            cash_after=self.cash,
            equity_after=eq,
        )
        self.events.append(event)
        return event


def replay_events(
    events: list[LedgerEvent] | list[dict[str, Any]],
    *,
    starting_cash: float,
    session_id: str = "replay",
) -> PaperLedger:
    """Rebuild cash/positions from a recorded event list. MARK/FILL/FLATTEN only."""
    led = PaperLedger(starting_cash=starting_cash, session_id=session_id)
    for raw in events:
        payload = raw.as_dict() if isinstance(raw, LedgerEvent) else dict(raw)
        kind = LedgerEventKind(str(payload["kind"]))
        if kind is LedgerEventKind.MARK:
            token = str(payload.get("token_id") or "")
            price = payload.get("price")
            if not token or price is None:
                raise ValueError("MARK event missing token_id/price")
            led.mark(token, float(price), market_id=payload.get("market_id"))
            continue
        size = float(payload.get("size") or 0.0)
        price = payload.get("price")
        if size <= 0 or price is None:
            continue
        led.apply_fill(
            token_id=str(payload.get("token_id") or ""),
            market_id=str(payload.get("market_id") or ""),
            side=str(payload.get("side") or Side.BUY.value),
            size=size,
            price=float(price),
            fee=float(payload.get("fee") or 0.0),
            client_order_id=payload.get("client_order_id"),
            note=str(payload.get("note") or kind.value),
            kind=kind,
        )
    return led
