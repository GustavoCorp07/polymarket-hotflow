"""Cold-path Kimi PERFORMANCE_ANALYST stub. Never import from evaluate."""

from __future__ import annotations

import json
from typing import Any

from hotflow.ai_research.kimi_client import KimiClient, KimiRole, redact


def analyze_performance_cold(
    summary: dict[str, Any],
    client: KimiClient | None = None,
    *,
    hard: bool = False,
) -> dict[str, Any]:
    kimi = client or KimiClient()
    user = redact(
        "Sanitized performance summary. Do not invent trades or request secrets.\n"
        + json.dumps(summary, default=str)
    )
    return kimi.complete(KimiRole.PERFORMANCE_ANALYST, user, hard=hard)
