"""Build static GitHub Pages demo JSON from a mock PAPER session.

Snapshots match the localhost dashboard `/api/state` shape (paper ledger only).
No LIVE transmit, no venue PnL, no secrets.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from hotflow.config import HotflowConfig, load_config
from hotflow.monitoring.dashboard import DashboardHub
from hotflow.monitoring.observer import Observability
from hotflow.monitoring.redact import redact
from hotflow.portfolio.session import PaperSession, mock_markets
from hotflow.storage.sqlite_store import SqliteStore

DEFAULT_PAGES_DIR = Path("docs/pages")
DEMO_NOTICE = "Static GitHub Pages demo — for live local ledger use `hotflow dashboard`"
DEMO_SOURCE = "paper-run --mock"

EXPECTED_STATE_KEYS = frozenset(
    {
        "page",
        "updated_at",
        "generation",
        "mode",
        "paper_only",
        "live_transmit",
        "health",
        "kill_switch",
        "live_gates",
        "ledger",
        "open_positions",
        "hot_markets",
        "recent",
        "feeds",
        "cycle_count",
        "last_cycle_at",
        "static_pages_demo",
        "demo_source",
        "demo_label",
        "demo_notice",
    }
)

LEDGER_KEYS = frozenset(
    {
        "origin",
        "note",
        "equity",
        "realized_pnl",
        "unrealized_pnl",
        "drawdown",
        "session_pnl",
        "cash",
        "fees",
        "win_rate",
        "expectancy",
        "closed_count",
        "open_positions",
        "positions",
        "event_count",
    }
)

SECRET_NEEDLES = (
    "api_key",
    "apikey",
    "private_key",
    "HOTFLOW_ACCEPT_LIVE=1",
    "sk-live",
    "mnemonic",
    "passphrase",
)


def pages_root() -> Path:
    return Path(__file__).resolve().parents[3] / DEFAULT_PAGES_DIR


def _prepare_mock_config(cfg: HotflowConfig) -> HotflowConfig:
    cfg.risk.cooldown_ms = 0
    cfg.risk.cooldown_after_losses_ms = 0
    cfg.trading.mode = "paper"
    cfg.trading.session_id = "pages-demo-paper"
    return cfg


def annotate_snapshot(snap: dict[str, Any], *, label: str, index: int, total: int) -> dict[str, Any]:
    body = dict(snap)
    body["static_pages_demo"] = True
    body["demo_source"] = DEMO_SOURCE
    body["demo_label"] = label
    body["demo_notice"] = DEMO_NOTICE
    body["demo_index"] = index
    body["demo_count"] = total
    body["page"] = "hotflow-paper-dashboard"
    body["paper_only"] = True
    body["live_transmit"] = False
    body["mode"] = "paper"
    gates = body.get("live_gates")
    if isinstance(gates, dict):
        gates = dict(gates)
        gates["closed"] = True
        gates["open"] = False
        body["live_gates"] = gates
    cleaned = redact(body)
    return cleaned if isinstance(cleaned, dict) else body


def _session(*, sqlite_path: Path | None = None) -> PaperSession:
    cfg = _prepare_mock_config(load_config())
    store = SqliteStore(str(sqlite_path)) if sqlite_path is not None else None
    obs = Observability.from_config(cfg, announce_restart=False)
    obs.dashboard.attach_live_gates(cfg)
    return PaperSession(cfg, store, obs=obs, use_twap_fixtures=True)


def capture_frame(hub: DashboardHub, *, label: str, index: int, total: int) -> dict[str, Any]:
    return annotate_snapshot(hub.snapshot(), label=label, index=index, total=total)


def build_demo_frames(
    *,
    cycles: int = 2,
    flatten: bool = True,
    sqlite_path: Path | None = None,
) -> list[tuple[str, dict[str, Any]]]:
    """Run a mock paper session and snapshot the dashboard hub after each cycle.

    Default is two mock cycles plus an explicit flatten frame (three rotating
    snapshots). A third *evaluate* cycle often trips RUNAWAY_REJECTS on this
    fixture mix; that is real paper risk, but the public demo stays on the
    healthy ready / live-gates-CLOSED path.
    """
    if cycles < 1:
        raise ValueError("cycles must be >= 1")
    session = _session(sqlite_path=sqlite_path)
    session.obs.dashboard.note_ledger(session.ledger.snapshot())
    planned = cycles + (1 if flatten else 0)
    frames: list[tuple[str, dict[str, Any]]] = []
    for i in range(cycles):
        session.run_markets(mock_markets())
        label = f"cycle-{i + 1}"
        name = f"{len(frames) + 1:02d}-{label}.json"
        frames.append((name, capture_frame(session.obs.dashboard, label=label, index=len(frames) + 1, total=planned)))
    if flatten:
        session.flatten()
        label = f"cycle-{cycles}-flatten"
        name = f"{len(frames) + 1:02d}-{label}.json"
        frames.append((name, capture_frame(session.obs.dashboard, label=label, index=len(frames) + 1, total=planned)))
    return frames


def missing_state_keys(payload: dict[str, Any]) -> list[str]:
    return sorted(key for key in EXPECTED_STATE_KEYS if key not in payload)


def state_errors(payload: Any) -> list[str]:
    errors: list[str] = []
    if not isinstance(payload, dict):
        return ["payload is not an object"]
    missing = missing_state_keys(payload)
    if missing:
        errors.append("missing keys: " + ", ".join(missing))
    if payload.get("mode") != "paper":
        errors.append("mode must be paper")
    if payload.get("paper_only") is not True:
        errors.append("paper_only must be true")
    if payload.get("live_transmit") is not False:
        errors.append("live_transmit must be false")
    if payload.get("page") != "hotflow-paper-dashboard":
        errors.append("page must be hotflow-paper-dashboard")
    if payload.get("static_pages_demo") is not True:
        errors.append("static_pages_demo must be true")
    gates = payload.get("live_gates")
    if not isinstance(gates, dict) or gates.get("closed") is not True:
        errors.append("live_gates.closed must be true")
    ledger = payload.get("ledger")
    if not isinstance(ledger, dict):
        errors.append("ledger missing")
    else:
        if ledger.get("origin") != "paper_ledger":
            errors.append("ledger.origin must be paper_ledger")
        absent = sorted(key for key in LEDGER_KEYS if key not in ledger)
        if absent:
            errors.append("ledger missing keys: " + ", ".join(absent))
    recent = payload.get("recent")
    if not isinstance(recent, list):
        errors.append("recent must be a list")
    else:
        allowed = {"TRADE", "SKIP", "SHADOW"}
        for row in recent:
            if not isinstance(row, dict):
                errors.append("recent row is not an object")
                break
            if row.get("decision") not in allowed:
                errors.append(f"unexpected decision {row.get('decision')}")
                break
    blob = json.dumps(payload, default=str).lower()
    for needle in SECRET_NEEDLES:
        if needle.lower() in blob:
            errors.append(f"secret needle present: {needle}")
            break
    return errors


def _dump(payload: Any) -> str:
    return json.dumps(payload, indent=2, default=str) + "\n"


def write_pages_demo(
    out_dir: Path,
    *,
    cycles: int = 2,
    flatten: bool = True,
    sqlite_path: Path | None = None,
) -> dict[str, Path]:
    """Write demo JSON, poll target, rotating snapshots, and an embedded JS bundle."""
    out = Path(out_dir)
    snap_dir = out / "snapshots"
    snap_dir.mkdir(parents=True, exist_ok=True)
    frames = build_demo_frames(cycles=cycles, flatten=flatten, sqlite_path=sqlite_path)
    written: dict[str, Path] = {}
    rotate: list[str] = []
    payloads: list[dict[str, Any]] = []
    for name, payload in frames:
        path = snap_dir / name
        path.write_text(_dump(payload), encoding="utf-8")
        rel = f"snapshots/{name}"
        written[rel] = path
        rotate.append(rel)
        payloads.append(payload)
    latest = payloads[-1]
    demo_state = out / "demo-state.json"
    state = out / "state.json"
    demo_state.write_text(_dump(latest), encoding="utf-8")
    state.write_text(_dump(latest), encoding="utf-8")
    written["demo-state.json"] = demo_state
    written["state.json"] = state
    manifest = {
        "page": "hotflow-paper-dashboard",
        "static_pages_demo": True,
        "demo_notice": DEMO_NOTICE,
        "demo_source": DEMO_SOURCE,
        "mode": "paper",
        "paper_only": True,
        "live_transmit": False,
        "poll": "state.json",
        "primary": "demo-state.json",
        "rotate": rotate,
        "interval_ms": 2000,
        "frame_count": len(rotate),
    }
    manifest_path = out / "snapshots.json"
    manifest_path.write_text(_dump(manifest), encoding="utf-8")
    written["snapshots.json"] = manifest_path
    bundle = {
        "notice": DEMO_NOTICE,
        "poll": "state.json",
        "primary": "demo-state.json",
        "rotate": rotate,
        "interval_ms": 2000,
        "frames": payloads,
    }
    bundle_path = out / "demo-bundle.js"
    bundle_path.write_text(
        "window.HOTFLOW_PAGES_DEMO = " + json.dumps(bundle, default=str) + ";\n",
        encoding="utf-8",
    )
    written["demo-bundle.js"] = bundle_path
    return written
