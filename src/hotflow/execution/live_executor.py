"""Narrow LIVE executor. Paper/shadow always refuse. Signing is not shipped.

Conceptual surface only (Parte 37):
    place_order / cancel_order / get_positions / get_orders

There is no `execute_arbitrary_transaction()`. AI must never withdraw.
These methods fail closed even if acceptance gates are forced open.
"""

from __future__ import annotations

from typing import Any

from hotflow.config import HotflowConfig
from hotflow.execution.live_gate import LiveGateError, live_gates_open

SIGNING_IMPLEMENTED = False


class LiveExecutor:
    """Refuse-closed LIVE transmit stub. Never loads a private key."""

    def __init__(self, config: HotflowConfig) -> None:
        self.config = config

    def _refuse(self, method: str) -> None:
        if not live_gates_open(self.config):
            raise LiveGateError(f"{method} refused: LIVE gates closed (PAPER/SHADOW)")
        # Gates open still do not enable signing in this pass.
        raise LiveGateError(f"{method} refused: wallet/signing is not implemented; fail closed")

    def place_order(self, *_args: Any, **_kwargs: Any) -> None:
        self._refuse("place_order")

    def cancel_order(self, *_args: Any, **_kwargs: Any) -> None:
        self._refuse("cancel_order")

    def get_positions(self, *_args: Any, **_kwargs: Any) -> None:
        self._refuse("get_positions")

    def get_orders(self, *_args: Any, **_kwargs: Any) -> None:
        self._refuse("get_orders")

    def execute_arbitrary_transaction(self, *_args: Any, **_kwargs: Any) -> None:
        raise LiveGateError("execute_arbitrary_transaction is not exposed")


def require_signing_absent() -> None:
    if SIGNING_IMPLEMENTED:
        raise LiveGateError("signing must stay unimplemented while LIVE is frozen")
