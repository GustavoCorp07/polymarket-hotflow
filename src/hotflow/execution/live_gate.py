"""LIVE transmit is unreachable unless every explicit acceptance gate passes.

This pass freezes gates CLOSED. Signing / CLOB transmit is not implemented.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any

from hotflow.config import HotflowConfig
from hotflow.reason_codes import ReasonCode

ACCEPTANCE_GATE_IDS = (
    "trading.mode",
    "live.accept_live_trading",
    "live.accept_capital_at_risk",
    "live.i_understand_orders_are_real",
    "HOTFLOW_ACCEPT_LIVE",
)


class LiveGateError(RuntimeError):
    reason = ReasonCode.LIVE_GATES_BLOCKED


@dataclass(frozen=True)
class GateStatus:
    id: str
    open: bool
    expected_open: bool
    detail: str = ""

    @property
    def closed(self) -> bool:
        return not self.open

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "open": self.open,
            "closed": self.closed,
            "expected_open": self.expected_open,
            "detail": self.detail,
        }


@dataclass
class LiveGateReport:
    mode: str
    live_gates_open: bool
    signing_implemented: bool
    gates: list[GateStatus] = field(default_factory=list)
    still_blocked: list[str] = field(default_factory=list)

    @property
    def any_acceptance_open(self) -> bool:
        return any(g.open for g in self.gates if g.id in ACCEPTANCE_GATE_IDS)

    @property
    def freeze_ok(self) -> bool:
        return (not self.live_gates_open) and (not self.any_acceptance_open) and (not self.signing_implemented)

    def as_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "live_gates_open": self.live_gates_open,
            "signing_implemented": self.signing_implemented,
            "freeze_ok": self.freeze_ok,
            "any_acceptance_open": self.any_acceptance_open,
            "gates": [g.as_dict() for g in self.gates],
            "still_blocked": list(self.still_blocked),
        }


LIVE_PREP_STILL_BLOCKED = (
    "LIVE transmit (all acceptance gates stay closed)",
    "wallet / EIP-712 / HMAC order signing (not implemented)",
    "CLOB user credentials on the hot path",
    "venue-balance reconciliation (paper ledger ≠ venue)",
    "real-socket failure injection",
    "known-critical-bug sign-off after billing-unlocked CI",
)


def live_gates_open(config: HotflowConfig, *, environ: dict[str, str] | None = None) -> bool:
    env = environ if environ is not None else os.environ
    if config.trading.mode.lower() != "live":
        return False
    if not config.live.accept_live_trading:
        return False
    if not config.live.accept_capital_at_risk:
        return False
    if not config.live.i_understand_orders_are_real:
        return False
    if env.get("HOTFLOW_ACCEPT_LIVE") != "1":
        return False
    return True


def inspect_live_gates(config: HotflowConfig, *, environ: dict[str, str] | None = None) -> LiveGateReport:
    env = environ if environ is not None else dict(os.environ)
    env_flag = env.get("HOTFLOW_ACCEPT_LIVE", "")
    gates = [
        GateStatus(
            "trading.mode",
            config.trading.mode.lower() == "live",
            expected_open=False,
            detail=config.trading.mode,
        ),
        GateStatus(
            "live.accept_live_trading",
            bool(config.live.accept_live_trading),
            expected_open=False,
            detail=str(config.live.accept_live_trading).lower(),
        ),
        GateStatus(
            "live.accept_capital_at_risk",
            bool(config.live.accept_capital_at_risk),
            expected_open=False,
            detail=str(config.live.accept_capital_at_risk).lower(),
        ),
        GateStatus(
            "live.i_understand_orders_are_real",
            bool(config.live.i_understand_orders_are_real),
            expected_open=False,
            detail=str(config.live.i_understand_orders_are_real).lower(),
        ),
        GateStatus(
            "HOTFLOW_ACCEPT_LIVE",
            env_flag == "1",
            expected_open=False,
            detail=env_flag or "unset",
        ),
        GateStatus(
            "signing_implemented",
            False,
            expected_open=False,
            detail="place_order/cancel/get_positions/get_orders refuse; no EIP-712/HMAC",
        ),
    ]
    return LiveGateReport(
        mode=config.trading.mode,
        live_gates_open=live_gates_open(config, environ=env),
        signing_implemented=False,
        gates=gates,
        still_blocked=list(LIVE_PREP_STILL_BLOCKED),
    )


def assert_live_allowed(config: HotflowConfig) -> None:
    if not live_gates_open(config):
        raise LiveGateError(
            "LIVE blocked: need trading.mode=live, three YAML accept flags, and HOTFLOW_ACCEPT_LIVE=1"
        )


def require_live_closed(config: HotflowConfig, *, environ: dict[str, str] | None = None) -> LiveGateReport:
    """Phase 15 freeze: any open acceptance gate is unexpected."""
    report = inspect_live_gates(config, environ=environ)
    if not report.freeze_ok:
        raise LiveGateError("LIVE gates must stay closed; signing is not implemented")
    return report
