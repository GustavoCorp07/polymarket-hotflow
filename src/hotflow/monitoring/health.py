"""Process health / readiness state for local HTTP handlers."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from hotflow.monitoring.redact import redact


@dataclass
class HealthState:
    mode: str = "paper"
    kill_switch: bool = False
    kill_reason: str | None = None
    live_gates_open: bool = False
    started_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    last_error: str | None = None
    ready_override: bool | None = None

    @property
    def ready(self) -> bool:
        if self.ready_override is not None:
            return self.ready_override
        if self.kill_switch:
            return False
        # LIVE transmit is not a supported ready state in this pass.
        return self.mode.lower() != "live"

    def payload(self, *, ready: bool | None = None) -> dict[str, Any]:
        status_ready = self.ready if ready is None else ready
        body = {
            "status": "ok" if not self.kill_switch else "degraded",
            "mode": self.mode,
            "kill_switch": self.kill_switch,
            "kill_reason": self.kill_reason,
            "ready": status_ready,
            "live_gates_open": self.live_gates_open,
            "started_at": self.started_at.isoformat(),
            "last_error": self.last_error,
        }
        cleaned = redact(body)
        return cleaned if isinstance(cleaned, dict) else body
