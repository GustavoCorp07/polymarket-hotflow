from hotflow.types import MarketRecord


class WeatherStrategy:
    name = "weather_stub"
    category = "weather"

    def accepts(self, market: MarketRecord) -> bool:
        return (market.category or "").lower() == "weather"

    def experiment_fields(self) -> dict[str, str]:
        return {"strategy": self.name, "category": self.category, "status": "stub"}
