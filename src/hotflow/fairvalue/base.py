from __future__ import annotations

from typing import Protocol

from hotflow.config import FairValueConfig
from hotflow.types import EdgeBreakdown, MarketRecord, Side


class FairValueProvider(Protocol):
    name: str

    def evaluate(
        self,
        market: MarketRecord,
        *,
        side: Side,
        shares: float,
        min_required_edge: float,
        config: FairValueConfig,
        p_info: float | None = None,
    ) -> EdgeBreakdown: ...
