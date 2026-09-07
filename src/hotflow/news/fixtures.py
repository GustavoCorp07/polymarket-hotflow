"""Labeled news fixtures. Not live headlines; not invented market moves."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from hotflow.news.item import NewsClass, NewsItem


def labeled_news_items(*, now: datetime | None = None) -> list[NewsItem]:
    stamp = now or datetime.now(UTC)
    return [
        NewsItem(
            news_id="btc-sec-filing",
            headline="SEC filing names BTC spot product terms matching up/down window",
            body="Labeled fixture. Official-source text only.",
            source_id="sec.gov",
            source_name="SEC EDGAR (fixture)",
            published_at=stamp - timedelta(minutes=8),
            market_id="demo-btc-updown",
            resolution_terms=["btc", "up/down", "demo"],
            event_key="btc-sec-window",
            classification_label=NewsClass.OFFICIAL,
            claimed_p_shift=0.08,
            pre_event_mid=0.41,
            origin="fixture",
            labels={"role": "validated_apply"},
        ),
        NewsItem(
            news_id="btc-sec-filing-dup",
            headline="SEC filing names BTC spot product terms matching up/down window",
            body="Same event_key as btc-sec-filing.",
            source_id="sec.gov",
            source_name="SEC EDGAR (fixture)",
            published_at=stamp - timedelta(minutes=7),
            market_id="demo-btc-updown",
            resolution_terms=["btc", "up/down", "demo"],
            event_key="btc-sec-window",
            classification_label=NewsClass.OFFICIAL,
            claimed_p_shift=0.08,
            origin="fixture",
            labels={"role": "duplicate"},
        ),
        NewsItem(
            news_id="btc-already-repriced",
            headline="BTC up/down already printed the claimed mid after the filing",
            body="Labeled already-repriced case.",
            source_id="reuters",
            source_name="Reuters (fixture)",
            published_at=stamp - timedelta(minutes=20),
            market_id="demo-btc-repriced",
            resolution_terms=["btc", "up/down", "demo"],
            event_key="btc-repriced-print",
            classification_label=NewsClass.WIRE,
            claimed_p_shift=0.28,
            claimed_p_after=0.70,
            pre_event_mid=0.42,
            origin="fixture",
            labels={"role": "already_repriced"},
        ),
        NewsItem(
            news_id="chicago-heat-on-btc",
            headline="Chicago official high exceeds 90F on the listed weather window",
            body="Weather wording; must not bind a BTC up/down market.",
            source_id="fixture_official",
            source_name="NWS fixture text",
            published_at=stamp - timedelta(minutes=5),
            market_id="demo-btc-updown",
            resolution_terms=["chicago", "fahrenheit", "nws", "weather"],
            event_key="chi-heat-90",
            classification_label=NewsClass.OFFICIAL,
            claimed_p_shift=0.20,
            origin="fixture",
            labels={"role": "irrelevant_resolution"},
        ),
        NewsItem(
            news_id="anon-btc-rumor",
            headline="anon blog says BTC up/down is a lock",
            body="Unvalidated source.",
            source_id="anon_blog",
            source_name="anonymous blog (fixture)",
            published_at=stamp - timedelta(minutes=2),
            market_id="demo-btc-updown",
            resolution_terms=["btc", "up/down"],
            event_key="anon-btc-lock",
            classification_label=NewsClass.RUMOR,
            claimed_p_shift=0.40,
            origin="fixture",
            labels={"role": "unvalidated"},
        ),
        NewsItem(
            news_id="old-commentary",
            headline="Week-old BTC commentary restates the demo up/down question",
            body="Aged fixture → low recency confidence.",
            source_id="fixture_commentary",
            source_name="commentary desk (fixture)",
            published_at=stamp - timedelta(days=12),
            market_id="demo-btc-updown",
            resolution_terms=["btc", "up/down", "demo"],
            event_key="old-btc-comment",
            classification_label=NewsClass.COMMENTARY,
            claimed_p_shift=0.05,
            origin="fixture",
            labels={"role": "low_confidence"},
        ),
        NewsItem(
            news_id="btc-large-labeled-shift",
            headline="Labeled large BTC up/down impact feature for edge-gate tests",
            body="Still only a p_info feature. Risk and min edge remain in force.",
            source_id="fixture_official",
            source_name="official fixture",
            published_at=stamp - timedelta(minutes=3),
            market_id="demo-btc-news-edge",
            resolution_terms=["btc", "up/down", "demo"],
            event_key="btc-large-shift",
            classification_label=NewsClass.OFFICIAL,
            claimed_p_shift=0.15,
            origin="fixture",
            labels={"role": "edge_gate"},
        ),
    ]


def public_fetch_status(*, enabled: bool) -> dict[str, object]:
    """Live news scrape is default-off and not implemented in this pass."""
    if not enabled:
        return {
            "fetched": False,
            "label": "public_fetch_default_off",
            "items": [],
            "note": "No news crawl. Use labeled fixtures.",
        }
    return {
        "fetched": False,
        "label": "news_scrape_not_implemented",
        "items": [],
        "note": "Refused: this pass does not scrape paywalled or live news APIs.",
    }
