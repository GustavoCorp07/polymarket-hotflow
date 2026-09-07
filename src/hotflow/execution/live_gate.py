"""LIVE transmit is unreachable unless every explicit acceptance gate passes."""

from __future__ import annotations

import os

from hotflow.config import HotflowConfig
from hotflow.reason_codes import ReasonCode


class LiveGateError(RuntimeError):
    reason = ReasonCode.LIVE_GATES_BLOCKED


def live_gates_open(config: HotflowConfig) -> bool:
    if config.trading.mode.lower() != "live":
        return False
    if not config.live.accept_live_trading:
        return False
    if not config.live.accept_capital_at_risk:
        return False
    if not config.live.i_understand_orders_are_real:
        return False
    if os.environ.get("HOTFLOW_ACCEPT_LIVE") != "1":
        return False
    return True


def assert_live_allowed(config: HotflowConfig) -> None:
    if not live_gates_open(config):
        raise LiveGateError(
            "LIVE blocked: need trading.mode=live, three YAML accept flags, and HOTFLOW_ACCEPT_LIVE=1"
        )
