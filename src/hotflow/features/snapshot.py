from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, Field

from hotflow.features.microstructure import compact_microstructure
from hotflow.types import HotMarketResult, MarketRecord


class FeatureSnapshot(BaseModel):
    ts: datetime = Field(default_factory=lambda: datetime.now(UTC))
    market_id: str
    liquidity: float | None = None
    volume_24hr: float | None = None
    spread: float | None = None
    mid: float | None = None
    hms: float | None = None
    tier: str | None = None
    extras: dict[str, Any] = Field(default_factory=dict)


def build_feature_snapshot(
    market: MarketRecord,
    hms: HotMarketResult | None = None,
    microstructure: dict[str, Any] | None = None,
) -> FeatureSnapshot:
    mid = None
    if market.book and market.book.mid is not None:
        mid = market.book.mid
    elif market.best_bid is not None and market.best_ask is not None:
        mid = (market.best_bid + market.best_ask) / 2.0
    extras: dict[str, Any] = {"tags": market.tags, "category": market.category}
    if microstructure:
        extras["microstructure"] = compact_microstructure(microstructure)
    return FeatureSnapshot(
        market_id=market.market_id,
        liquidity=market.liquidity,
        volume_24hr=market.volume_24hr,
        spread=market.spread if market.spread is not None else (market.book.spread if market.book else None),
        mid=mid,
        hms=hms.score if hms else None,
        tier=hms.tier.value if hms else None,
        extras=extras,
    )
