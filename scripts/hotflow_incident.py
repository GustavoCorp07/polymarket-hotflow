#!/usr/bin/env python3
"""Cold-path /hotflow-incident (Parte 50). Collect, do not mutate live params."""

from __future__ import annotations

import json
from pathlib import Path

from hotflow.analytics.experiments import git_commit
from hotflow.config import load_config
from hotflow.storage.sqlite_store import SqliteStore


def main() -> None:
    cfg = load_config()
    store = SqliteStore(cfg.storage.sqlite_path)
    report = {
        "git_commit": git_commit(),
        "mode": cfg.trading.mode,
        "orders": list(store.iter_orders()),
        "signals": store.list_signals()[-50:],
        "recommendation": "freeze changes, inspect kill-switch history, add a regression test",
        "production_changed": False,
    }
    out = Path(cfg.storage.reports_dir) / "incident.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    print(f"incident snapshot {out}")


if __name__ == "__main__":
    main()
