"""Paper weather fair value. Forecasts are features, never the resolution source."""

from __future__ import annotations

import math

from hotflow.types import WeatherForecast, WeatherResolutionSpec


def weather_p_above_threshold(spec: WeatherResolutionSpec, forecast: WeatherForecast) -> float | None:
    """P(forecast > parsed threshold). Not official settlement math."""
    if spec.threshold is None:
        return None
    if forecast.p_above_threshold is not None:
        return max(1e-6, min(1.0 - 1e-6, forecast.p_above_threshold))
    center = forecast.mean if forecast.mean is not None else forecast.median
    if center is None or forecast.std is None or forecast.std <= 0:
        return None
    z = (center - spec.threshold) / forecast.std
    return max(1e-6, min(1.0 - 1e-6, 0.5 * (1.0 + math.erf(z / math.sqrt(2.0)))))


class WeatherFairValue:
    """Forecast distribution vs Polymarket implied. Forecast ≠ official resolver."""

    name = "weather"

    def p_info(self, spec: WeatherResolutionSpec, forecast: WeatherForecast) -> float | None:
        return weather_p_above_threshold(spec, forecast)
