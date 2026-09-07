"""Run the Parte 39 failure matrix. PAPER/SHADOW only — LIVE stays gated."""

from __future__ import annotations

from typing import Any

from hotflow.execution.live_gate import live_gates_open
from hotflow.failure.scenarios import SCENARIOS
from hotflow.monitoring.observer import Observability

LIVE_PREP_STILL_BLOCKED = (
    "LIVE transmit (trading.mode=live + accept_* + HOTFLOW_ACCEPT_LIVE)",
    "wallet / signing / CLOB user credentials",
    "venue-balance reconciliation (paper ledger is not a venue)",
    "real-socket failure injection (this soak uses transports / MockTransport)",
    "Postgres / remote storage down",
    "auto-applying tuner to production",
)


def run_failure_soak(*, obs: Observability | None = None) -> dict[str, Any]:
    watcher = obs or Observability.from_config(watcher_config(), announce_restart=False)
    rows = [scenario() for scenario in SCENARIOS]
    fail_safe = all(row.get("fail_safe") for row in rows)
    orders = sum(int(row.get("orders_submitted") or 0) for row in rows)
    would = any(row.get("would_buy") or row.get("would_sell") for row in rows)
    return {
        "mode": "paper",
        "sent_orders": False,
        "live_gates_open": live_gates_open(watcher.config),
        "fail_safe": fail_safe and orders == 0 and not would,
        "scenario_count": len(rows),
        "scenarios": rows,
        "orders_submitted": orders,
        "would_intent": would,
        "live_prep_still_blocked": list(LIVE_PREP_STILL_BLOCKED),
        "gates": {
            "failures_fail_safe": fail_safe,
            "no_orders_sent": orders == 0,
            "no_would_submit": not would,
            "live_still_blocked": not live_gates_open(watcher.config),
        },
    }


def watcher_config():
    from hotflow.config import HotflowConfig

    cfg = HotflowConfig()
    cfg.trading.mode = "paper"
    return cfg
