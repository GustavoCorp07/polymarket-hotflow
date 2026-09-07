"""Parte 25 — first-class regime labels from explicit features.

Never invent a regime when the required feature is missing. Detectors return
N/A and list `missing`. Strategies may be disabled via YAML; risk VETO is
unchanged. No LLM. No estimated residual.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from hotflow.config import RegimeConfig, RegimeCryptoConfig, RegimeSportsConfig, RegimeWeatherConfig
from hotflow.features.microstructure import imbalance
from hotflow.features.time_features import time_to_resolution_seconds
from hotflow.types import MarketRecord, SportsGameState, WeatherForecast


class Regime(StrEnum):
    LOW_VOL = "low_volatility"
    NORMAL = "normal"
    HIGH_VOL = "high_volatility"
    TREND = "trend"
    MEAN_REVERSION = "mean_reversion"
    NEWS_SHOCK = "news_shock"
    LIQUIDITY_VACUUM = "liquidity_vacuum"
    NEAR_RESOLUTION = "near_resolution"
    PRE_GAME = "pre_game"
    EARLY_LIVE = "early_live"
    MID_GAME = "mid_game"
    LATE_GAME = "late_game"
    OVERTIME = "overtime"
    LIVE = "live"  # coarse fallback when live=True but period is missing
    FORECAST_UNCERTAIN = "forecast_uncertainty_high"
    FORECAST_CONVERGING = "forecast_converging"
    OBSERVATION_PHASE = "observation_phase"
    NOT_AVAILABLE = "N/A"


_SPORTS_EARLY = frozenset({"1Q", "Q1", "1H"})
_SPORTS_MID = frozenset({"2Q", "Q2", "3Q", "Q3", "HT"})
_SPORTS_LATE = frozenset({"4Q", "Q4", "2H"})
_SPORTS_OT = frozenset({"OT", "OT1", "OT2", "F/OT", "FOT"})
_SPORTS_PRE = frozenset({"SCHEDULED", "PREGAME", "PRE-GAME", "NOTSTARTED", "NS"})


@dataclass
class RegimeReport:
    primary: Regime
    labels: tuple[Regime, ...] = ()
    features: dict[str, Any] = field(default_factory=dict)
    assumptions: tuple[str, ...] = ()
    missing: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {
            "primary": self.primary.value,
            "labels": [item.value for item in self.labels],
            "features": dict(self.features),
            "assumptions": list(self.assumptions),
            "missing": list(self.missing),
            "invented": False,
        }

    @property
    def label_ids(self) -> tuple[str, ...]:
        return tuple(item.value for item in self.labels if item is not Regime.NOT_AVAILABLE)


def _unique(items: list[Regime]) -> tuple[Regime, ...]:
    out: list[Regime] = []
    for item in items:
        if item not in out:
            out.append(item)
    return tuple(out)


def _norm_period(period: str | None) -> str:
    return (period or "").upper().replace(" ", "")


def detect_crypto(
    market: MarketRecord,
    *,
    ttr_seconds: float | None = None,
    news: dict[str, Any] | None = None,
    config: RegimeCryptoConfig | None = None,
) -> RegimeReport:
    """Spread / TTR / news / book imbalance only. Missing feature → not invented."""
    cfg = config or RegimeCryptoConfig()
    missing: list[str] = []
    features: dict[str, Any] = {}
    fired: list[Regime] = []
    assumptions: list[str] = []

    spread = market.spread
    if spread is None and market.book is not None:
        spread = market.book.spread
    features["spread"] = spread
    if spread is None:
        missing.append("spread")

    liq = market.liquidity
    features["liquidity"] = liq
    if liq is None:
        missing.append("liquidity")

    ttr = ttr_seconds if ttr_seconds is not None else time_to_resolution_seconds(market)
    features["ttr_seconds"] = ttr
    if ttr is None:
        missing.append("ttr_seconds")

    news = news or {}
    news_apply = bool(news.get("apply"))
    news_class = str(news.get("classification") or "")
    news_rel = float(news.get("relevance") or 0.0)
    features["news_apply"] = news_apply
    features["news_classification"] = news_class or None
    features["news_relevance"] = news_rel

    imb = imbalance(market.book) if market.book is not None else None
    mid = market.book.mid if market.book is not None else None
    last = market.last_trade_price
    features["imbalance"] = imb
    features["mid"] = mid
    features["last_trade_price"] = last
    if imb is None:
        missing.append("imbalance")
    if mid is None:
        missing.append("mid")
    if last is None:
        missing.append("last_trade_price")

    if (
        news_apply
        and news_class in {item.lower() for item in cfg.news_shock_classes}
        and news_rel + 1e-12 >= cfg.news_shock_min_relevance
    ):
        fired.append(Regime.NEWS_SHOCK)
        assumptions.append(
            "news_shock: validated news apply + official/wire/breaking class "
            f"and relevance>={cfg.news_shock_min_relevance}."
        )

    if liq is not None and spread is not None:
        if liq < cfg.liquidity_vacuum and spread >= cfg.vacuum_spread:
            fired.append(Regime.LIQUIDITY_VACUUM)
            assumptions.append(
                f"liquidity_vacuum: liquidity<{cfg.liquidity_vacuum} and spread>={cfg.vacuum_spread}."
            )
    elif liq is None or spread is None:
        assumptions.append("liquidity_vacuum not scored — liquidity or spread missing.")

    if ttr is not None and 0 < ttr < cfg.near_resolution_s:
        fired.append(Regime.NEAR_RESOLUTION)
        assumptions.append(f"near_resolution: 0 < ttr_seconds < {cfg.near_resolution_s}.")

    if spread is not None:
        if spread >= cfg.high_vol_spread:
            fired.append(Regime.HIGH_VOL)
            assumptions.append(f"high_volatility: spread>={cfg.high_vol_spread} (book spread heuristic).")
        elif spread <= cfg.low_vol_spread:
            fired.append(Regime.LOW_VOL)
            assumptions.append(f"low_volatility: spread<={cfg.low_vol_spread} (book spread heuristic).")

    if imb is not None and mid is not None and last is not None:
        deviation = last - mid
        if abs(imb) >= cfg.trend_imbalance and deviation * imb > 0:
            fired.append(Regime.TREND)
            assumptions.append(
                f"trend: |imbalance|>={cfg.trend_imbalance} and last_trade on the same side of mid."
            )
        elif abs(imb) <= cfg.mean_reversion_imbalance and abs(deviation) <= cfg.mean_reversion_dev:
            fired.append(Regime.MEAN_REVERSION)
            assumptions.append(
                f"mean_reversion: |imbalance|<={cfg.mean_reversion_imbalance} "
                f"and |last-mid|<={cfg.mean_reversion_dev}."
            )
    else:
        assumptions.append("trend/mean_reversion not scored — need imbalance, mid, and last_trade.")

    if spread is not None and Regime.HIGH_VOL not in fired and Regime.LOW_VOL not in fired:
        if Regime.NEWS_SHOCK not in fired and Regime.LIQUIDITY_VACUUM not in fired:
            fired.append(Regime.NORMAL)
            assumptions.append("normal: spread present and inside the configured vol band.")

    primary = _crypto_primary(fired, missing)
    labels = _unique(fired) if fired else (Regime.NOT_AVAILABLE,)
    if primary is Regime.NOT_AVAILABLE:
        labels = (Regime.NOT_AVAILABLE,)
        assumptions.append("N/A: required features missing; regime not invented.")
    return RegimeReport(
        primary=primary,
        labels=labels,
        features=features,
        assumptions=tuple(assumptions),
        missing=tuple(missing),
    )


def _crypto_primary(fired: list[Regime], missing: list[str]) -> Regime:
    priority = (
        Regime.NEWS_SHOCK,
        Regime.LIQUIDITY_VACUUM,
        Regime.NEAR_RESOLUTION,
        Regime.HIGH_VOL,
        Regime.LOW_VOL,
        Regime.TREND,
        Regime.MEAN_REVERSION,
        Regime.NORMAL,
    )
    for item in priority:
        if item in fired:
            return item
    return Regime.NOT_AVAILABLE


def detect_sports(
    state: SportsGameState | None,
    *,
    live: bool | None = None,
    config: RegimeSportsConfig | None = None,
) -> RegimeReport:
    """Official Sports WS live/ended/period only. Missing period while live → N/A."""
    _ = config or RegimeSportsConfig()
    features: dict[str, Any] = {}
    missing: list[str] = []
    assumptions: list[str] = []
    if state is None and live is None:
        return RegimeReport(
            primary=Regime.NOT_AVAILABLE,
            labels=(Regime.NOT_AVAILABLE,),
            features={"state": None},
            assumptions=("N/A: no official sports state and no live flag.",),
            missing=("sports_state",),
        )

    ended = state.ended if state is not None else None
    is_live = state.live if state is not None and state.live is not None else live
    period = _norm_period(state.period if state is not None else None)
    status = (state.status if state is not None else None) or ""
    features["live"] = is_live
    features["ended"] = ended
    features["period"] = period or None
    features["status"] = status or None

    if ended or status.upper() in {"FINAL", "F/OT", "FORFEIT"}:
        if period in _SPORTS_OT or status.upper() in {"F/OT"}:
            assumptions.append("overtime: official ended status with OT period/F/OT.")
            return RegimeReport(
                primary=Regime.OVERTIME,
                labels=(Regime.OVERTIME,),
                features=features,
                assumptions=tuple(assumptions),
                missing=(),
            )
        assumptions.append("ended without OT period — late_game (clock expired).")
        return RegimeReport(
            primary=Regime.LATE_GAME,
            labels=(Regime.LATE_GAME,),
            features=features,
            assumptions=tuple(assumptions),
            missing=(),
        )

    status_key = status.upper().replace(" ", "")
    if is_live is False or status_key in _SPORTS_PRE:
        assumptions.append("pre_game: live=false or official scheduled/pre-game status.")
        return RegimeReport(
            primary=Regime.PRE_GAME,
            labels=(Regime.PRE_GAME,),
            features=features,
            assumptions=tuple(assumptions),
            missing=(),
        )

    if period in _SPORTS_OT:
        assumptions.append("overtime: official OT period while live.")
        return RegimeReport(
            primary=Regime.OVERTIME,
            labels=(Regime.OVERTIME,),
            features=features,
            assumptions=tuple(assumptions),
            missing=(),
        )
    if period in _SPORTS_EARLY:
        assumptions.append("early_live: official opening period (Q1/1H).")
        return RegimeReport(
            primary=Regime.EARLY_LIVE,
            labels=(Regime.EARLY_LIVE, Regime.LIVE),
            features=features,
            assumptions=tuple(assumptions),
            missing=(),
        )
    if period in _SPORTS_MID:
        assumptions.append("mid_game: official middle period (Q2/Q3/HT).")
        return RegimeReport(
            primary=Regime.MID_GAME,
            labels=(Regime.MID_GAME, Regime.LIVE),
            features=features,
            assumptions=tuple(assumptions),
            missing=(),
        )
    if period in _SPORTS_LATE:
        assumptions.append("late_game: official closing period (Q4/2H).")
        return RegimeReport(
            primary=Regime.LATE_GAME,
            labels=(Regime.LATE_GAME, Regime.LIVE),
            features=features,
            assumptions=tuple(assumptions),
            missing=(),
        )

    if is_live is True:
        missing.append("period")
        assumptions.append("N/A for early/mid/late: live=true but official period missing.")
        return RegimeReport(
            primary=Regime.NOT_AVAILABLE,
            labels=(Regime.NOT_AVAILABLE, Regime.LIVE),
            features=features,
            assumptions=tuple(assumptions),
            missing=tuple(missing),
        )

    missing.append("live_or_period")
    return RegimeReport(
        primary=Regime.NOT_AVAILABLE,
        labels=(Regime.NOT_AVAILABLE,),
        features=features,
        assumptions=("N/A: cannot classify sports phase from available official fields.",),
        missing=tuple(missing),
    )


def detect_weather(
    market: MarketRecord,
    *,
    forecast: WeatherForecast | None = None,
    ttr_seconds: float | None = None,
    config: RegimeWeatherConfig | None = None,
) -> RegimeReport:
    """TTR + labeled forecast std/ensemble only. Missing both → N/A."""
    cfg = config or RegimeWeatherConfig()
    ttr = ttr_seconds if ttr_seconds is not None else time_to_resolution_seconds(market)
    features: dict[str, Any] = {"ttr_seconds": ttr}
    missing: list[str] = []
    fired: list[Regime] = []
    assumptions: list[str] = []
    if ttr is None:
        missing.append("ttr_seconds")

    std = forecast.std if forecast is not None else None
    spread = forecast.ensemble_spread if forecast is not None else None
    center = None
    if forecast is not None:
        center = forecast.mean if forecast.mean is not None else forecast.median
    features["forecast_std"] = std
    features["ensemble_spread"] = spread
    features["forecast_center"] = center
    if forecast is None:
        missing.append("forecast")
    else:
        if std is None and spread is None:
            missing.append("forecast_dispersion")

    if ttr is not None and 0 < ttr < cfg.near_resolution_s:
        fired.append(Regime.NEAR_RESOLUTION)
        assumptions.append(f"near_resolution: 0 < ttr_seconds < {cfg.near_resolution_s}.")
    elif ttr is not None and 0 < ttr < cfg.observation_phase_s:
        fired.append(Regime.OBSERVATION_PHASE)
        assumptions.append(f"observation_phase: ttr_seconds < {cfg.observation_phase_s}.")

    frac: float | None = None
    if std is not None and center is not None and abs(center) > 1e-9:
        frac = abs(std / center)
    elif spread is not None and center is not None and abs(center) > 1e-9:
        frac = abs(spread / center)
    features["dispersion_frac"] = frac
    if frac is not None:
        if frac >= cfg.uncertain_std_frac:
            fired.append(Regime.FORECAST_UNCERTAIN)
            assumptions.append(
                f"forecast_uncertainty_high: std_or_ensemble/|center|>={cfg.uncertain_std_frac}."
            )
        elif frac <= cfg.converging_std_frac:
            fired.append(Regime.FORECAST_CONVERGING)
            assumptions.append(
                f"forecast_converging: std_or_ensemble/|center|<={cfg.converging_std_frac}."
            )

    if not fired:
        assumptions.append("N/A: no TTR band and no usable forecast dispersion.")
        return RegimeReport(
            primary=Regime.NOT_AVAILABLE,
            labels=(Regime.NOT_AVAILABLE,),
            features=features,
            assumptions=tuple(assumptions),
            missing=tuple(missing),
        )
    primary = fired[0]
    return RegimeReport(
        primary=primary,
        labels=_unique(fired),
        features=features,
        assumptions=tuple(assumptions),
        missing=tuple(missing),
    )


def detect_regime(
    market: MarketRecord,
    *,
    category: str,
    ttr_seconds: float | None = None,
    news: dict[str, Any] | None = None,
    forecast: WeatherForecast | None = None,
    sports_state: SportsGameState | None = None,
    config: RegimeConfig | None = None,
) -> RegimeReport:
    cfg = config or RegimeConfig()
    if not cfg.enabled:
        return RegimeReport(
            primary=Regime.NOT_AVAILABLE,
            labels=(Regime.NOT_AVAILABLE,),
            features={"enabled": False},
            assumptions=("regime detection disabled in YAML.",),
            missing=(),
        )
    if category == "crypto":
        return detect_crypto(market, ttr_seconds=ttr_seconds, news=news, config=cfg.crypto)
    if category == "sports":
        live = None
        if sports_state is not None:
            live = sports_state.live
        return detect_sports(sports_state, live=live, config=cfg.sports)
    if category == "weather":
        return detect_weather(market, forecast=forecast, ttr_seconds=ttr_seconds, config=cfg.weather)
    return RegimeReport(
        primary=Regime.NOT_AVAILABLE,
        labels=(Regime.NOT_AVAILABLE,),
        features={"category": category},
        assumptions=(f"N/A: no first-class detector for category={category}.",),
        missing=(),
    )


def strategy_blocked(category: str, report: RegimeReport, config: RegimeConfig) -> str | None:
    """Return a detail string if YAML disables this category in the detected regime."""
    if not config.enabled:
        return None
    row = config.strategies.get(category)
    if row is None:
        return None
    labels = {report.primary.value, *report.label_ids}
    disabled = {item.lower() for item in row.disabled_regimes}
    hit = sorted(labels & disabled)
    if hit:
        return f"disabled_regimes={hit}"
    enabled = [item.lower() for item in row.enabled_regimes]
    if enabled and not (labels & set(enabled)):
        return f"enabled_regimes={enabled} labels={sorted(labels)}"
    return None


def classify_crypto(market: MarketRecord, ttr_seconds: float | None = None) -> Regime:
    """Backward-compatible wrapper. Same TTR/spread rules as detect_crypto."""
    return detect_crypto(market, ttr_seconds=ttr_seconds).primary


def classify_sports(live: bool | None) -> Regime:
    if live is None:
        return Regime.NOT_AVAILABLE
    if live:
        return Regime.LIVE
    return Regime.PRE_GAME


def classify_weather(ensemble_wide: bool = False) -> Regime:
    return Regime.FORECAST_UNCERTAIN if ensemble_wide else Regime.NORMAL
