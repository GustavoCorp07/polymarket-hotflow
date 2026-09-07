"""Parquet export hook. Schema is storage-agnostic for later Timescale sync."""

from __future__ import annotations

from pathlib import Path
from typing import Any


def write_feature_parquet(path: str | Path, rows: list[dict[str, Any]]) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        import polars as pl
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("polars is required for parquet export") from exc
    if not rows:
        pl.DataFrame({"market_id": []}).write_parquet(target)
        return target
    pl.DataFrame(rows).write_parquet(target)
    return target
