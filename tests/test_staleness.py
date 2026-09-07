from datetime import UTC, datetime, timedelta

from hotflow.config import FeedsConfig
from hotflow.marketdata.freshness import FeedClock, StaleDataError


def test_fresh_feed_passes() -> None:
    clock = FeedClock(FeedsConfig())
    now = datetime.now(UTC)
    clock.touch("clob_book", observed_at=now)
    clock.check("clob_book", now)
    assert clock.is_fresh("clob_book", now)


def test_stale_critical_book() -> None:
    clock = FeedClock(FeedsConfig())
    now = datetime.now(UTC)
    clock.touch("clob_book", observed_at=now - timedelta(seconds=45))
    try:
        clock.check("clob_book", now)
        raise AssertionError("expected stale")
    except StaleDataError as exc:
        assert exc.critical is True
        assert exc.feed == "clob_book"
    assert "clob_book" in clock.critical_stale(now)


def test_noncritical_gamma_not_in_critical_list() -> None:
    clock = FeedClock(FeedsConfig())
    now = datetime.now(UTC)
    clock.touch("gamma", observed_at=now - timedelta(seconds=120))
    assert clock.critical_stale(now) == []
    assert not clock.is_fresh("gamma", now)
