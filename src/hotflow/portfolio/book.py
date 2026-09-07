from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class PortfolioBook:
    cash: float
    positions: dict[str, float] = field(default_factory=dict)
    realized_pnl: float = 0.0

    def mark(self, token_id: str, mid: float) -> float:
        qty = self.positions.get(token_id, 0.0)
        return qty * mid

    def equity(self, marks: dict[str, float]) -> float:
        return self.cash + sum(self.mark(tid, px) for tid, px in marks.items())
