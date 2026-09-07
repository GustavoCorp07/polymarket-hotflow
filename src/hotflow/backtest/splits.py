"""Train / validation / OOS split plus a walk-forward window stub."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from hotflow.backtest.events import MarketEvent, parse_ts


def parse_split(raw: dict[str, Any] | None) -> dict[str, datetime | None]:
    row = raw or {}
    return {
        "train_end": parse_ts(row.get("train_end")),
        "validation_end": parse_ts(row.get("validation_end")),
        "oos_start": parse_ts(row.get("oos_start")),
    }


def assign_split(ts: datetime, split: dict[str, datetime | None]) -> str:
    train_end = split.get("train_end")
    validation_end = split.get("validation_end")
    oos_start = split.get("oos_start")
    if oos_start and ts >= oos_start:
        return "oos"
    if validation_end and train_end and train_end <= ts < validation_end:
        return "validation"
    if train_end and ts < train_end:
        return "train"
    if oos_start and ts < oos_start:
        return "validation" if train_end and ts >= train_end else "train"
    return "train"


def walk_forward_windows(
    start: datetime,
    end: datetime,
    *,
    train_seconds: float,
    test_seconds: float,
    step_seconds: float,
) -> list[dict[str, str]]:
    """Sequential walk-forward stub. Not purged CV / Monte Carlo."""
    if train_seconds <= 0 or test_seconds <= 0 or step_seconds <= 0:
        return []
    windows: list[dict[str, str]] = []
    cursor = start
    train = timedelta(seconds=train_seconds)
    test = timedelta(seconds=test_seconds)
    step = timedelta(seconds=step_seconds)
    while cursor + train + test <= end:
        train_end = cursor + train
        test_end = train_end + test
        windows.append(
            {
                "train_start": cursor.isoformat(),
                "train_end": train_end.isoformat(),
                "test_start": train_end.isoformat(),
                "test_end": test_end.isoformat(),
            }
        )
        cursor += step
    return windows


def events_in_window(
    events: list[MarketEvent], start: datetime, end: datetime
) -> list[MarketEvent]:
    return [item for item in events if start <= item.ts < end]
