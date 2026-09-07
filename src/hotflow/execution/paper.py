"""Paper broker: partial fills, idempotency, never infers fills from the book."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from hotflow.config import TradingConfig
from hotflow.execution.orders import OrderStateMachine
from hotflow.portfolio.ledger import LedgerEvent, PaperLedger
from hotflow.reason_codes import ReasonCode
from hotflow.types import Opportunity, OrderRecord, OrderStatus, TradingMode


class PaperBroker:
    def __init__(self, trading: TradingConfig, ledger: PaperLedger | None = None) -> None:
        self.trading = trading
        self.orders: dict[str, OrderRecord] = {}
        self.ledger = ledger or PaperLedger(
            starting_cash=trading.paper_starting_cash,
            session_id=trading.session_id,
        )
        self.last_fill_event: LedgerEvent | None = None

    @property
    def cash(self) -> float:
        return self.ledger.cash

    @cash.setter
    def cash(self, value: float) -> None:
        self.ledger.cash = float(value)

    @property
    def positions(self) -> dict[str, float]:
        return {token: pos.qty for token, pos in self.ledger.positions.items() if abs(pos.qty) > 1e-12}

    def create(
        self,
        opp: Opportunity,
        *,
        price: float,
        size: float,
        client_order_id: str | None = None,
    ) -> OrderRecord:
        cid = client_order_id or str(uuid.uuid4())
        if cid in self.orders:
            existing = self.orders[cid]
            existing.reject_reason = ReasonCode.IDEMPOTENT_REPLAY
            return existing
        order = OrderRecord(
            client_order_id=cid,
            status=OrderStatus.CREATED,
            market_id=opp.market_id,
            token_id=opp.token_id,
            side=opp.side,
            price=price,
            size=size,
            mode=TradingMode.PAPER,
        )
        self.orders[cid] = order
        return order

    def submit(self, client_order_id: str) -> OrderRecord:
        sm = OrderStateMachine(self.orders[client_order_id])
        sm.transition(OrderStatus.SUBMITTED)
        sm.transition(OrderStatus.ACKNOWLEDGED)
        return sm.order

    def simulate_fill(
        self,
        client_order_id: str,
        *,
        fill_ratio: float | None = None,
        fee_per_share: float = 0.0,
    ) -> OrderRecord:
        """Fill from the simulator only — never from book disappearance."""
        order = self.orders[client_order_id]
        sm = OrderStateMachine(order)
        if order.status == OrderStatus.CREATED:
            sm.transition(OrderStatus.SUBMITTED)
        if order.status == OrderStatus.SUBMITTED:
            sm.transition(OrderStatus.ACKNOWLEDGED)
        ratio = self.trading.paper_fill_ratio if fill_ratio is None else fill_ratio
        remaining = order.size - order.filled_size
        fill = remaining * max(0.0, min(1.0, ratio))
        self.last_fill_event = None
        if fill <= 0:
            return order
        sm.apply_fill(fill, order.price)
        fee = abs(fill) * max(0.0, fee_per_share)
        self.last_fill_event = self.ledger.apply_fill(
            token_id=order.token_id,
            market_id=order.market_id,
            side=order.side,
            size=fill,
            price=order.avg_fill_price or order.price,
            fee=fee,
            client_order_id=client_order_id,
            note="paper_fill",
        )
        order.updated_at = datetime.now(UTC)
        return order

    def request_cancel(self, client_order_id: str) -> OrderRecord:
        sm = OrderStateMachine(self.orders[client_order_id])
        if sm.order.status in {OrderStatus.FILLED, OrderStatus.CANCELLED, OrderStatus.REJECTED}:
            return sm.order
        if sm.order.status != OrderStatus.CANCEL_REQUESTED:
            sm.transition(OrderStatus.CANCEL_REQUESTED)
        sm.transition(OrderStatus.CANCELLED)
        return sm.order

    def reject(self, client_order_id: str, reason: str) -> OrderRecord:
        sm = OrderStateMachine(self.orders[client_order_id])
        if sm.order.status in {OrderStatus.CREATED, OrderStatus.SUBMITTED}:
            sm.transition(OrderStatus.REJECTED, reason=reason)
        return sm.order

    def cancel_open(self) -> list[OrderRecord]:
        cancelled: list[OrderRecord] = []
        for cid, order in list(self.orders.items()):
            if order.status in {
                OrderStatus.CREATED,
                OrderStatus.SUBMITTED,
                OrderStatus.ACKNOWLEDGED,
                OrderStatus.PARTIAL,
            }:
                cancelled.append(self.request_cancel(cid))
        return cancelled
