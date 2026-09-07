"""Internal order state machine. Venue statuses are mapped only by adapters."""

from __future__ import annotations

from datetime import UTC, datetime

from hotflow.types import OrderRecord, OrderStatus

LEGAL_TRANSITIONS: dict[OrderStatus, frozenset[OrderStatus]] = {
    OrderStatus.CREATED: frozenset(
        {OrderStatus.SUBMITTED, OrderStatus.REJECTED, OrderStatus.CANCELLED, OrderStatus.EXPIRED}
    ),
    OrderStatus.SUBMITTED: frozenset(
        {
            OrderStatus.ACKNOWLEDGED,
            OrderStatus.REJECTED,
            OrderStatus.CANCEL_REQUESTED,
            OrderStatus.EXPIRED,
        }
    ),
    OrderStatus.ACKNOWLEDGED: frozenset(
        {
            OrderStatus.PARTIAL,
            OrderStatus.FILLED,
            OrderStatus.CANCEL_REQUESTED,
            OrderStatus.CANCELLED,
            OrderStatus.EXPIRED,
        }
    ),
    OrderStatus.PARTIAL: frozenset(
        {
            OrderStatus.PARTIAL,
            OrderStatus.FILLED,
            OrderStatus.CANCEL_REQUESTED,
            OrderStatus.CANCELLED,
            OrderStatus.EXPIRED,
        }
    ),
    OrderStatus.FILLED: frozenset(),
    OrderStatus.CANCEL_REQUESTED: frozenset({OrderStatus.CANCELLED, OrderStatus.FILLED, OrderStatus.PARTIAL}),
    OrderStatus.CANCELLED: frozenset(),
    OrderStatus.REJECTED: frozenset(),
    OrderStatus.EXPIRED: frozenset(),
}


class IllegalTransition(ValueError):
    pass


class OrderStateMachine:
    def __init__(self, order: OrderRecord) -> None:
        self.order = order

    def transition(self, dest: OrderStatus, *, reason: str | None = None) -> OrderRecord:
        allowed = LEGAL_TRANSITIONS[self.order.status]
        if dest not in allowed:
            raise IllegalTransition(f"{self.order.status} -> {dest} is illegal")
        self.order.status = dest
        self.order.updated_at = datetime.now(UTC)
        if reason:
            self.order.reject_reason = reason
        return self.order

    def apply_fill(self, fill_size: float, price: float) -> OrderRecord:
        if fill_size <= 0:
            raise ValueError("fill_size must be positive")
        if self.order.status in {OrderStatus.CREATED}:
            self.transition(OrderStatus.SUBMITTED)
        if self.order.status == OrderStatus.SUBMITTED:
            self.transition(OrderStatus.ACKNOWLEDGED)
        prev = self.order.filled_size
        new_filled = min(self.order.size, prev + fill_size)
        if new_filled <= prev:
            return self.order
        if self.order.avg_fill_price is None:
            self.order.avg_fill_price = price
        else:
            self.order.avg_fill_price = (
                self.order.avg_fill_price * prev + price * (new_filled - prev)
            ) / new_filled
        self.order.filled_size = new_filled
        if new_filled + 1e-12 >= self.order.size:
            self.transition(OrderStatus.FILLED)
        else:
            self.transition(OrderStatus.PARTIAL)
        return self.order
