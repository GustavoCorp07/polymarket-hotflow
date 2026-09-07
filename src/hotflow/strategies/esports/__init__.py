from hotflow.types import MarketRecord


class EsportsStrategy:
    name = "esports_stub"
    category = "esports"

    def accepts(self, market: MarketRecord) -> bool:
        return (market.category or "").lower() == "esports"

    def experiment_fields(self) -> dict[str, str]:
        return {"strategy": self.name, "category": self.category, "status": "stub"}
