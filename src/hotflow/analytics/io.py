"""Load existing JSON reports. Does not invent missing files."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def load_json(path: Path | None) -> dict[str, Any] | None:
    if path is None or not path.is_file():
        return None
    raw = json.loads(path.read_text(encoding="utf-8"))
    return raw if isinstance(raw, dict) else None


def latest_report(directory: Path, prefixes: tuple[str, ...]) -> Path | None:
    if not directory.is_dir():
        return None
    candidates: list[Path] = []
    for path in directory.glob("*.json"):
        name = path.name
        if name.startswith(("readiness-", "performance-", "decay-", "walk-forward-")):
            continue
        if any(name.startswith(prefix) for prefix in prefixes):
            candidates.append(path)
    if not candidates:
        return None
    candidates.sort(key=lambda item: item.stat().st_mtime, reverse=True)
    return candidates[0]
