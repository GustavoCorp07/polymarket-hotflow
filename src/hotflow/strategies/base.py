from __future__ import annotations

from typing import Protocol

from hotflow.types import MarketRecord


class StrategyAdapter(Protocol):
    name: str
    category: str

    def accepts(self, market: MarketRecord) -> bool: ...

    def experiment_fields(self) -> dict[str, str]: ...
