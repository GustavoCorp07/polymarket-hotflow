#!/usr/bin/env python3
"""Cold-path /hotflow-daily-review (Parte 48). Never changes production."""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

from hotflow.analytics.experiments import git_commit
from hotflow.analytics.skip_audit import format_skip_audit, rollup_skip_audit
from hotflow.config import load_config
from hotflow.storage.sqlite_store import SqliteStore


def main() -> None:
    cfg = load_config()
    store = SqliteStore(cfg.storage.sqlite_path)
    signals = store.list_signals()
    reasons = Counter(row["reason"] for row in signals)
    skip_audit = rollup_skip_audit(signals, source=str(cfg.storage.sqlite_path))
    report = {
        "git_commit": git_commit(),
        "signals": len(signals),
        "accepted": sum(int(row["accepted"]) for row in signals),
        "reasons": dict(reasons),
        "skip_audit": skip_audit,
        "production_changed": False,
    }
    out = Path(cfg.storage.reports_dir) / "daily-review.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"daily-review written {out} (no production mutation)")
    print(format_skip_audit(skip_audit))


if __name__ == "__main__":
    main()
