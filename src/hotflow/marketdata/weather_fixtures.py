"""Deterministic weather forecast fixtures. Not official resolution observations."""

from __future__ import annotations

from typing import Protocol

from hotflow.types import WeatherForecast, WeatherResolutionSpec


class WeatherForecastSource(Protocol):
    def latest(self, spec: WeatherResolutionSpec) -> WeatherForecast | None: ...


class FixtureWeatherSource:
    def __init__(self, rows: list[tuple[str, WeatherForecast]] | None = None) -> None:
        self._rows = dict(rows or [])

    def put(self, key: str, forecast: WeatherForecast) -> None:
        self._rows[key.lower()] = forecast

    def latest(self, spec: WeatherResolutionSpec) -> WeatherForecast | None:
        for key in (spec.city, spec.station, spec.source):
            if key and key.lower() in self._rows:
                return self._rows[key.lower()]
        return self._rows.get("default")


def default_weather_forecast() -> WeatherForecast:
    return WeatherForecast(
        mean=78.0,
        median=77.5,
        std=2.5,
        p_above_threshold=0.92,
        ensemble_spread=3.0,
        source="fixture",
    )
