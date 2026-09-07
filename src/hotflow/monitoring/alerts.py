"""Alert hooks: structured log + optional callbacks. Never include secrets."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from hotflow.monitoring.json_logs import JsonLogger
from hotflow.monitoring.redact import redact
from hotflow.types import KillSwitchReason

AlertCallback = Callable[["Alert"], None]


class AlertKind(StrEnum):
    KILL_SWITCH = "kill_switch"
    DRAWDOWN = "drawdown"
    STALE_WS = "stale_ws"
    HIGH_LATENCY = "high_latency"
    AUTH_FAILURE = "auth_failure"
    POSITION_MISMATCH = "position_mismatch"
    PROCESS_RESTART = "process_restart"
    UNEXPECTED_EXPOSURE = "unexpected_exposure"
    API_DISCONNECTED = "api_disconnected"
    HIGH_SLIPPAGE = "high_slippage"
    STRATEGY_DISABLED = "strategy_disabled"


_KILL_TO_KIND: dict[KillSwitchReason, AlertKind] = {
    KillSwitchReason.AUTH_FAIL: AlertKind.AUTH_FAILURE,
    KillSwitchReason.POSITION_MISMATCH: AlertKind.POSITION_MISMATCH,
    KillSwitchReason.STALE_WS: AlertKind.STALE_WS,
    KillSwitchReason.STALE_CRITICAL_DATA: AlertKind.STALE_WS,
    KillSwitchReason.DATA_FEED_DEAD: AlertKind.API_DISCONNECTED,
    KillSwitchReason.DRAWDOWN_EXCEEDED: AlertKind.DRAWDOWN,
    KillSwitchReason.EXCESSIVE_LATENCY: AlertKind.HIGH_LATENCY,
    KillSwitchReason.ABNORMAL_SLIPPAGE: AlertKind.HIGH_SLIPPAGE,
}


@dataclass(frozen=True)
class Alert:
    kind: AlertKind
    message: str
    fields: dict[str, Any] = field(default_factory=dict)
    ts: datetime = field(default_factory=lambda: datetime.now(UTC))

    def as_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind.value,
            "message": self.message,
            "ts": self.ts.isoformat(),
            **self.fields,
        }


def kinds_for_kill(reason: KillSwitchReason) -> tuple[AlertKind, ...]:
    extra = _KILL_TO_KIND.get(reason)
    if extra is None or extra is AlertKind.KILL_SWITCH:
        return (AlertKind.KILL_SWITCH,)
    return (AlertKind.KILL_SWITCH, extra)


class AlertRouter:
    """Log + metric + optional callback interface. Callbacks must not block the hot path."""

    def __init__(
        self,
        logger: JsonLogger | None = None,
        *,
        callbacks: list[AlertCallback] | None = None,
        on_emit: Callable[[Alert], None] | None = None,
    ) -> None:
        self.logger = logger or JsonLogger()
        self.callbacks = list(callbacks or [])
        self._on_emit = on_emit
        self.emitted: list[Alert] = []

    def add_callback(self, callback: AlertCallback) -> None:
        self.callbacks.append(callback)

    def emit(self, kind: AlertKind | str, message: str, **fields: Any) -> Alert:
        alert_kind = kind if isinstance(kind, AlertKind) else AlertKind(kind)
        clean = redact(fields)
        if not isinstance(clean, dict):
            clean = {}
        alert = Alert(kind=alert_kind, message=str(message), fields=clean)
        self.emitted.append(alert)
        self.logger.emit("alert", kind=alert_kind.value, message=alert.message, **clean)
        if self._on_emit is not None:
            self._on_emit(alert)
        for callback in self.callbacks:
            callback(alert)
        return alert
