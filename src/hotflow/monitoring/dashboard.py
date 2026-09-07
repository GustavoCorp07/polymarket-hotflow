"""In-process PAPER dashboard snapshot. No venue PnL, no secrets, no LIVE transmit."""

from __future__ import annotations

import threading
from collections import deque
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from hotflow.execution.live_gate import inspect_live_gates
from hotflow.monitoring.health import HealthState
from hotflow.monitoring.redact import redact

DASHBOARD_PORT = 9109
MAX_RECENT = 80
HTML_NAME = "dashboard.html"


def utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()


def load_dashboard_html() -> str:
    """Ship a single-page UI next to this module. Stdlib only — no CDN."""
    path = Path(__file__).with_name("static") / HTML_NAME
    return path.read_text(encoding="utf-8")


def idle_ledger() -> dict[str, Any]:
    return {
        "origin": "paper_ledger",
        "note": "waiting for paper session — no invented venue PnL",
        "equity": None,
        "realized_pnl": None,
        "unrealized_pnl": None,
        "drawdown": None,
        "session_pnl": None,
        "cash": None,
        "fees": None,
        "win_rate": None,
        "expectancy": None,
        "closed_count": 0,
        "open_positions": 0,
        "positions": {},
        "event_count": 0,
    }


def idle_snapshot(health: HealthState, *, live_gates: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    payload = {
        "page": "hotflow-paper-dashboard",
        "updated_at": utc_now_iso(),
        "generation": 0,
        "mode": health.mode,
        "paper_only": True,
        "live_transmit": False,
        "health": health.payload(),
        "kill_switch": {
            "tripped": health.kill_switch,
            "reason": health.kill_reason,
        },
        "live_gates": {
            "open": health.live_gates_open,
            "closed": not health.live_gates_open,
            "gates": live_gates or [],
        },
        "ledger": idle_ledger(),
        "open_positions": 0,
        "hot_markets": [],
        "recent": [],
        "feeds": {},
        "cycle_count": 0,
        "last_cycle_at": None,
    }
    cleaned = redact(payload)
    return cleaned if isinstance(cleaned, dict) else payload


def decision_row(result: dict[str, Any], *, ts: str | None = None) -> dict[str, Any]:
    """Compact TRADE/SKIP row. Only known audit fields — never dump extras."""
    accepted = bool(result.get("accepted"))
    reason = str(result.get("reason") or "NO_TRADE")
    decision = "TRADE" if accepted else "SKIP"
    if reason == "SHADOW_MODE":
        decision = "SHADOW"
    signal_raw = result.get("signal")
    signal: dict[str, Any] = signal_raw if isinstance(signal_raw, dict) else {}
    codes_raw = signal.get("reason_codes")
    codes = [str(code) for code in codes_raw] if isinstance(codes_raw, list) else [reason]
    regime = signal.get("spread_regime")
    if isinstance(regime, dict):
        regime = regime.get("label")
    hms = result.get("hms")
    if hms is None:
        hms = signal.get("hot_market_score")
    edge_raw = result.get("edge")
    edge: dict[str, Any] = edge_raw if isinstance(edge_raw, dict) else {}
    net = edge.get("net_expected_edge")
    if net is None:
        net = signal.get("net_edge")
    opp_raw = result.get("opportunity")
    opp: dict[str, Any] = opp_raw if isinstance(opp_raw, dict) else {}
    opp_score = opp.get("score")
    if opp_score is None:
        opp_score = signal.get("opportunity_score")
    market_id = result.get("market_id") or signal.get("market") or ""
    tier = None
    nested_hms = opp.get("hms")
    if isinstance(nested_hms, dict):
        tier = nested_hms.get("tier")
    return {
        "ts": ts or utc_now_iso(),
        "decision": decision,
        "accepted": accepted,
        "market_id": str(market_id),
        "reason": reason,
        "reason_codes": codes,
        "spread_regime": str(regime) if regime not in (None, "", "N/A") else None,
        "hms": float(hms) if hms is not None else None,
        "tier": str(tier) if tier else None,
        "net_edge": float(net) if net is not None else None,
        "opportunity_score": float(opp_score) if opp_score is not None else None,
    }


class DashboardHub:
    """Thread-safe ring buffer + ledger snapshot for the local UI / SSE."""

    def __init__(self, health: HealthState, *, max_events: int = MAX_RECENT) -> None:
        self.health = health
        self._lock = threading.Lock()
        self._cond = threading.Condition(self._lock)
        self.generation = 0
        self._ledger: dict[str, Any] = idle_ledger()
        self._recent: deque[dict[str, Any]] = deque(maxlen=max_events)
        self._hot: list[dict[str, Any]] = []
        self._feeds: dict[str, float | None] = {}
        self._cycle_count = 0
        self._last_cycle_at: str | None = None
        self._live_gates: list[dict[str, Any]] = []
        self._open_positions = 0

    def attach_live_gates(self, config: Any) -> None:
        report = inspect_live_gates(config)
        rows = [gate.as_dict() for gate in report.gates]
        with self._cond:
            self._live_gates = rows
            self.health.live_gates_open = report.live_gates_open
            self._bump()

    def note_decision(self, result: dict[str, Any], *, ts: str | None = None) -> None:
        row = decision_row(result, ts=ts)
        with self._cond:
            self._recent.appendleft(row)
            self._bump()

    def note_ledger(self, snap: Any) -> None:
        payload = snap.as_dict() if hasattr(snap, "as_dict") else dict(snap)
        positions_raw = payload.get("positions")
        positions: dict[str, Any] = positions_raw if isinstance(positions_raw, dict) else {}
        body = {
            "origin": "paper_ledger",
            "note": "paper session ledger — not venue balances",
            "equity": payload.get("equity"),
            "realized_pnl": payload.get("realized_pnl"),
            "unrealized_pnl": payload.get("unrealized_pnl"),
            "drawdown": payload.get("drawdown"),
            "session_pnl": payload.get("session_pnl"),
            "cash": payload.get("cash"),
            "fees": payload.get("fees"),
            "win_rate": payload.get("win_rate"),
            "expectancy": payload.get("expectancy"),
            "closed_count": payload.get("closed_count") or 0,
            "open_positions": len(positions),
            "positions": positions,
            "event_count": payload.get("event_count") or 0,
            "session_id": payload.get("session_id"),
        }
        with self._cond:
            self._ledger = body
            self._open_positions = len(positions)
            self._bump()

    def note_cycle(self, hot_markets: list[dict[str, Any]]) -> None:
        with self._cond:
            self._hot = list(hot_markets)
            self._cycle_count += 1
            self._last_cycle_at = utc_now_iso()
            self._bump()

    def note_feeds(self, feeds: dict[str, float | None]) -> None:
        with self._cond:
            self._feeds = dict(feeds)
            self._bump()

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return self._snapshot_unlocked()

    def wait_snapshot(self, last_generation: int, timeout: float) -> dict[str, Any]:
        with self._cond:
            if self.generation == last_generation:
                self._cond.wait(timeout)
            return self._snapshot_unlocked()

    def _bump(self) -> None:
        self.generation += 1
        self._cond.notify_all()

    def _snapshot_unlocked(self) -> dict[str, Any]:
        payload = {
            "page": "hotflow-paper-dashboard",
            "updated_at": utc_now_iso(),
            "generation": self.generation,
            "mode": self.health.mode,
            "paper_only": True,
            "live_transmit": False,
            "health": self.health.payload(),
            "kill_switch": {
                "tripped": self.health.kill_switch,
                "reason": self.health.kill_reason,
            },
            "live_gates": {
                "open": self.health.live_gates_open,
                "closed": not self.health.live_gates_open,
                "gates": list(self._live_gates),
            },
            "ledger": dict(self._ledger),
            "open_positions": self._open_positions,
            "hot_markets": list(self._hot),
            "recent": list(self._recent),
            "feeds": dict(self._feeds),
            "cycle_count": self._cycle_count,
            "last_cycle_at": self._last_cycle_at,
        }
        cleaned = redact(payload)
        return cleaned if isinstance(cleaned, dict) else payload
