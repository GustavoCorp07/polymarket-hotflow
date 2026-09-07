"""Paper weather fair value. Forecasts are features, never the resolution source."""

from __future__ import annotations

import math

from hotflow.types import WeatherForecast, WeatherResolutionSpec


def _clip_prob(value: float) -> float:
    return max(1e-6, min(1.0 - 1e-6, value))


def weather_p_above_threshold(spec: WeatherResolutionSpec, forecast: WeatherForecast) -> float | None:
    """P(forecast > parsed threshold). Not official settlement math."""
    if spec.threshold is None:
        return None
    if forecast.p_above_threshold is not None:
        return _clip_prob(forecast.p_above_threshold)
    center = forecast.mean if forecast.mean is not None else forecast.median
    if center is None or forecast.std is None or forecast.std <= 0:
        return None
    z = (center - spec.threshold) / forecast.std
    return _clip_prob(0.5 * (1.0 + math.erf(z / math.sqrt(2.0))))


def weather_p_yes(spec: WeatherResolutionSpec, forecast: WeatherForecast) -> float | None:
    """P(Yes) from labeled fixture p_yes or forecast vs parsed comparison."""
    if forecast.p_yes is not None:
        return _clip_prob(forecast.p_yes)
    p_above = weather_p_above_threshold(spec, forecast)
    if p_above is None:
        return None
    if spec.comparison in {"at_or_below", "less_than", "below"}:
        return _clip_prob(1.0 - p_above)
    if spec.comparison == "exact_bin":
        return None
    return p_above


class WeatherFairValue:
    """Forecast distribution vs Polymarket implied. Forecast ≠ official resolver."""

    name = "weather"

    def p_info(self, spec: WeatherResolutionSpec, forecast: WeatherForecast) -> float | None:
        return weather_p_yes(spec, forecast)
