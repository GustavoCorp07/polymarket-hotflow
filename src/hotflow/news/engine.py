"""Deterministic news path: classify → validate → impact features.

Never emits BUY/SELL. Never calls an LLM. Missing labeled impact is a skip.
"""

from __future__ import annotations

import hashlib
import re
from datetime import UTC, datetime

from hotflow.config import NewsEngineConfig
from hotflow.news.item import NewsClass, NewsImpact, NewsItem
from hotflow.news.sources import CLASS_WEIGHT, source_authority
from hotflow.reason_codes import ReasonCode
from hotflow.types import MarketRecord

_TOKEN = re.compile(r"[a-z0-9]{2,}")


def _clip_prob(value: float) -> float:
    return max(1e-6, min(1.0 - 1e-6, value))


def _tokens(text: str) -> list[str]:
    return _TOKEN.findall(text.lower())


def fingerprint(item: NewsItem) -> str:
    if item.event_key:
        return item.event_key
    blob = " ".join(_tokens(f"{item.headline} {item.source_id}"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


def classify(item: NewsItem) -> NewsClass:
    if item.classification_label is not None:
        return item.classification_label
    sid = item.source_id.strip().lower()
    if sid in {"sec.gov", "federal_reserve", "cftc", "treasury.gov", "fixture_official"}:
        return NewsClass.OFFICIAL
    if sid in {"reuters", "ap", "bloomberg", "fixture_wire"}:
        return NewsClass.WIRE
    if sid in {"fixture_commentary"}:
        return NewsClass.COMMENTARY
    if sid in {"anon_blog", "fixture_rumor"}:
        return NewsClass.RUMOR
    return NewsClass.UNKNOWN


def resolution_text(market: MarketRecord) -> str:
    parts = [
        market.question or "",
        market.slug or "",
        market.category or "",
        " ".join(market.tags),
        market.resolution.source or "",
        market.resolution.metric or "",
        " ".join(market.resolution.special_conditions),
    ]
    return " ".join(parts).lower()


def relevance(item: NewsItem, market: MarketRecord) -> float:
    haystack = resolution_text(market)
    terms = [t.lower() for t in item.resolution_terms] or _tokens(item.headline)
    if not terms:
        return 0.0
    hits = sum(1 for term in terms if term in haystack)
    return hits / len(terms)


def recency_weight(published_at: datetime, now: datetime, half_life_s: float) -> float:
    age = max(0.0, (now - published_at).total_seconds())
    if half_life_s <= 0:
        return 1.0
    return 0.5 ** (age / half_life_s)


def _mid(market: MarketRecord) -> float | None:
    if market.book and market.book.mid is not None:
        return float(market.book.mid)
    if market.best_bid is not None and market.best_ask is not None:
        return (float(market.best_bid) + float(market.best_ask)) / 2.0
    return None


class NewsEngine:
    """Ingest structured items and score impact features for one market."""

    def __init__(self, config: NewsEngineConfig | None = None) -> None:
        self.config = config or NewsEngineConfig()
        self.items: list[NewsItem] = []
        self._seen: set[str] = set()

    def ingest(self, item: NewsItem) -> None:
        self.items.append(item)

    def ingest_many(self, items: list[NewsItem]) -> None:
        for item in items:
            self.ingest(item)

    def reset_seen(self) -> None:
        self._seen.clear()

    def candidates_for(self, market: MarketRecord) -> list[NewsItem]:
        matched: list[NewsItem] = []
        for item in self.items:
            if item.market_id and item.market_id == market.market_id:
                matched.append(item)
            elif item.market_id is None and relevance(item, market) > 0:
                matched.append(item)
        return matched

    def evaluate_item(
        self,
        item: NewsItem,
        market: MarketRecord,
        *,
        p_base: float | None,
        now: datetime | None = None,
    ) -> NewsImpact:
        now = now or datetime.now(UTC)
        kind = classify(item)
        fp = fingerprint(item)
        authority = source_authority(item.source_id)
        rel = relevance(item, market)
        recency = recency_weight(item.published_at, now, self.config.recency_half_life_s)
        conf = authority * recency * CLASS_WEIGHT.get(kind.value, 0.15)
        impact = NewsImpact(
            news_id=item.news_id,
            classification=kind,
            source_authority=authority,
            relevance=rel,
            confidence=conf,
            p_base=p_base,
            origin=item.origin,
            fingerprint=fp,
        )

        if authority < self.config.min_source_authority:
            impact.reason = ReasonCode.NEWS_UNVALIDATED
            impact.detail = "source_authority"
            self._seen.add(fp)
            return impact
        if item.published_at.tzinfo is None:
            impact.reason = ReasonCode.NEWS_UNVALIDATED
            impact.detail = "published_at_naive"
            self._seen.add(fp)
            return impact
        skew_s = (item.published_at - now).total_seconds()
        if skew_s > 5.0:
            impact.reason = ReasonCode.NEWS_UNVALIDATED
            impact.detail = "published_in_future"
            self._seen.add(fp)
            return impact

        if fp in self._seen:
            impact.duplicate = True
            impact.reason = ReasonCode.NEWS_DUPLICATE
            impact.detail = fp
            return impact
        self._seen.add(fp)

        if rel < self.config.min_relevance:
            impact.reason = ReasonCode.NEWS_IRRELEVANT_RESOLUTION
            impact.detail = f"relevance={rel:.3f}"
            return impact

        if conf < self.config.min_confidence:
            impact.reason = ReasonCode.NEWS_LOW_CONFIDENCE
            impact.detail = f"confidence={conf:.3f}"
            return impact

        mid = _mid(market)
        if self._already_repriced(item, mid):
            impact.already_repriced = True
            impact.reason = ReasonCode.NEWS_ALREADY_REPRICED
            impact.detail = f"mid={mid}"
            return impact

        if item.claimed_p_after is None and item.claimed_p_shift is None:
            impact.reason = ReasonCode.NEWS_UNVALIDATED
            impact.detail = "no_labeled_impact"
            return impact

        if item.claimed_p_after is not None:
            adjusted = _clip_prob(item.claimed_p_after)
            base = p_base if p_base is not None else mid
            shift = (adjusted - base) if base is not None else 0.0
        else:
            assert item.claimed_p_shift is not None
            base = p_base if p_base is not None else mid
            if base is None:
                impact.reason = ReasonCode.NEWS_UNVALIDATED
                impact.detail = "no_p_base"
                return impact
            capped = max(-self.config.max_p_shift, min(self.config.max_p_shift, item.claimed_p_shift))
            shift = capped
            adjusted = _clip_prob(base + capped)

        impact.apply = True
        impact.reason = ReasonCode.OK
        impact.p_shift = shift
        impact.p_info_adjusted = adjusted
        impact.detail = "validated_impact_feature"
        return impact

    def _already_repriced(self, item: NewsItem, mid: float | None) -> bool:
        if mid is None:
            return False
        tol = self.config.already_repriced_abs
        if item.claimed_p_after is not None and abs(mid - item.claimed_p_after) <= tol:
            return True
        if item.pre_event_mid is not None and item.claimed_p_shift is not None:
            implied = item.pre_event_mid + item.claimed_p_shift
            moved = mid - item.pre_event_mid
            captured = abs(moved) + 1e-12 >= abs(item.claimed_p_shift) - tol
            same_dir = moved * item.claimed_p_shift >= 0
            near_implied = abs(mid - implied) <= tol
            if same_dir and (captured or near_implied):
                return True
        return False

    def impact_for(
        self,
        market: MarketRecord,
        *,
        p_base: float | None,
        now: datetime | None = None,
    ) -> NewsImpact:
        if not self.config.enabled:
            return NewsImpact(apply=False, detail="news_disabled")
        candidates = self.candidates_for(market)
        if not candidates:
            return NewsImpact(apply=False, detail="no_matching_news")
        last = NewsImpact(apply=False, detail="no_matching_news")
        for item in candidates:
            last = self.evaluate_item(item, market, p_base=p_base, now=now)
            if last.apply:
                return last
        return last
