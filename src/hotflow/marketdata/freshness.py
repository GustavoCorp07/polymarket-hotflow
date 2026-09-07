"""MAX_DATA_AGE enforcement per feed. Critical stale data blocks trading."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime

from hotflow.config import FeedsConfig


class StaleDataError(RuntimeError):
    def __init__(self, feed: str, age_ms: float, max_age_ms: int, critical: bool) -> None:
        super().__init__(f"stale feed={feed} age_ms={age_ms:.0f} max={max_age_ms} critical={critical}")
        self.feed = feed
        self.age_ms = age_ms
        self.max_age_ms = max_age_ms
        self.critical = critical


@dataclass
class FeedSample:
    name: str
    observed_at: datetime
    critical: bool
    max_age_ms: int


@dataclass
class FeedClock:
    feeds: FeedsConfig
    _samples: dict[str, FeedSample] = field(default_factory=dict)

    def touch(self, name: str, *, observed_at: datetime | None = None) -> None:
        spec = getattr(self.feeds, name, None)
        max_age = spec.max_data_age_ms if spec else self.feeds.clob_book.max_data_age_ms
        critical = spec.critical if spec else False
        self._samples[name] = FeedSample(
            name=name,
            observed_at=observed_at or datetime.now(UTC),
            critical=critical,
            max_age_ms=max_age,
        )

    def age_ms(self, name: str, now: datetime | None = None) -> float | None:
        sample = self._samples.get(name)
        if sample is None:
            return None
        current = now or datetime.now(UTC)
        return max(0.0, (current - sample.observed_at).total_seconds() * 1000.0)

    def check(self, name: str, now: datetime | None = None) -> None:
        sample = self._samples.get(name)
        if sample is None:
            raise StaleDataError(name, float("inf"), 0, True)
        age = self.age_ms(name, now)
        assert age is not None
        if age > sample.max_age_ms:
            raise StaleDataError(name, age, sample.max_age_ms, sample.critical)

    def critical_stale(self, now: datetime | None = None) -> list[str]:
        bad: list[str] = []
        for name, sample in self._samples.items():
            if not sample.critical:
                continue
            age = self.age_ms(name, now)
            if age is not None and age > sample.max_age_ms:
                bad.append(name)
        return bad

    def is_fresh(self, name: str, now: datetime | None = None) -> bool:
        try:
            self.check(name, now)
            return True
        except StaleDataError:
            return False
