from hotflow.types import MarketRecord


class SportsStrategy:
    name = "sports_stub"
    category = "sports"

    def accepts(self, market: MarketRecord) -> bool:
        return (market.category or "").lower() == "sports"

    def experiment_fields(self) -> dict[str, str]:
        return {"strategy": self.name, "category": self.category, "status": "stub"}
