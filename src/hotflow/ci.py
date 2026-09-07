"""Local CI entry. Source of truth while GitHub-hosted runners are billing-locked."""

from __future__ import annotations

import subprocess
from pathlib import Path


def repo_root(start: Path | None = None) -> Path:
    here = start or Path.cwd()
    for candidate in [here, *here.resolve().parents]:
        if (candidate / "scripts" / "ci_local.sh").is_file() and (candidate / "pyproject.toml").is_file():
            return candidate
    return here


def run_local_ci(*, cwd: Path | None = None) -> int:
    root = repo_root(cwd)
    script = root / "scripts" / "ci_local.sh"
    if not script.is_file():
        raise FileNotFoundError(f"missing {script}; run from the hotflow checkout")
    completed = subprocess.run(["bash", str(script)], cwd=root, check=False)
    return int(completed.returncode)
