from __future__ import annotations

import os
import subprocess
from datetime import UTC, datetime

from pydantic import BaseModel, Field


def git_commit() -> str:
    env = os.environ.get("HOTFLOW_GIT_COMMIT") or os.environ.get("GITHUB_SHA")
    if env:
        return env
    try:
        out = subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], text=True, timeout=2)
        return out.strip()
    except (OSError, subprocess.SubprocessError):
        return "unknown"


class ExperimentRecord(BaseModel):
    experiment_id: str
    strategy: str
    category: str
    version: str = "0.1.0"
    git_commit: str = Field(default_factory=git_commit)
    feature_set_version: str = "v1"
    notes: str = ""
    params: dict[str, str] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    paper_only: bool = True
