"""Cold-path Kimi stub for news classification. Never import from evaluate."""

from __future__ import annotations

from typing import Any

from hotflow.ai_research.kimi_client import KimiClient, KimiRole, redact
from hotflow.news.item import NewsItem


def classify_news_cold(
    item: NewsItem,
    client: KimiClient | None = None,
    *,
    hard: bool = False,
) -> dict[str, Any]:
    """Optional research helper. Mockable. Not on the hot path."""
    kimi = client or KimiClient()
    user = redact(
        "Classify this labeled news item. Do not invent facts or request secrets.\n"
        f"headline={item.headline}\n"
        f"source_id={item.source_id}\n"
        f"origin={item.origin}\n"
        f"body={item.body}"
    )
    return kimi.complete(KimiRole.NEWS_CLASSIFIER, user, hard=hard)
