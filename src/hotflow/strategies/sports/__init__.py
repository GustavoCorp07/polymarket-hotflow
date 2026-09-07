from hotflow.fairvalue.sports import sports_model_for
from hotflow.types import MarketRecord


class SportsStrategy:
    name = "sports_live_paper"
    category = "sports"

    def accepts(self, market: MarketRecord) -> bool:
        return (market.category or "").lower() == "sports"

    def experiment_fields(self) -> dict[str, str]:
        return {
            "strategy": self.name,
            "category": self.category,
            "status": "paper",
            "models": "NBABasketballModel,SoccerModel",
            "unsupported": "refuse_not_reuse",
        }

    def model_name(self, league: str | None) -> str | None:
        model = sports_model_for(league)
        return model.sport if model else None
