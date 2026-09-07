from hotflow.official import ESPORTS_DOCUMENTED_TITLES
from hotflow.types import MarketRecord


class EsportsStrategy:
    name = "esports_skip_heavy"
    category = "esports"

    def accepts(self, market: MarketRecord) -> bool:
        return (market.category or "").lower() == "esports"

    def experiment_fields(self) -> dict[str, str]:
        return {
            "strategy": self.name,
            "category": self.category,
            "status": "skip_heavy",
            "titles": ",".join(sorted(ESPORTS_DOCUMENTED_TITLES)),
            "live_model": "none",
        }
