"""TWAP-aware paper fair-value math on official Chainlink observations.

Does not compute a homemade TWAP. `current_twap` is the official RTDS/Chainlink
value (or a fixture with that payload shape). Official docs do not publish
Chainlink sampling/weighting, so this module never reconstructs a remaining
in-window average.
"""

from __future__ import annotations

import math
from datetime import UTC, datetime

from hotflow.config import TwapFairValueConfig
from hotflow.discovery.resolution import parse_end_date
from hotflow.types import MarketRecord, OfficialTwapObservation, TwapResolutionSpec, TwapSnapshot

SECONDS_PER_YEAR = 365.25 * 24 * 3600.0


def _clip_prob(value: float) -> float:
    return max(1e-6, min(1.0 - 1e-6, value))


def _norm_cdf(z: float) -> float:
    return 0.5 * (1.0 + math.erf(z / math.sqrt(2.0)))


def digital_prob_above(*, spot: float, strike: float, time_remaining_s: float, annualized_vol: float) -> float:
    """Paper heuristic: r=0 cash-or-nothing under GBM around the official TWAP.

    Not an official Polymarket settlement formula.
    """
    if spot <= 0 or strike <= 0 or annualized_vol < 0:
        raise ValueError("spot, strike must be positive; vol must be >= 0")
    if time_remaining_s <= 0:
        if spot > strike:
            return 1.0
        if spot < strike:
            return 0.0
        return 0.5
    t_years = time_remaining_s / SECONDS_PER_YEAR
    sigma_sqrt_t = annualized_vol * math.sqrt(t_years)
    if sigma_sqrt_t <= 0:
        return 1.0 if spot > strike else (0.0 if spot < strike else 0.5)
    d2 = (math.log(spot / strike) - 0.5 * (annualized_vol**2) * t_years) / sigma_sqrt_t
    return _clip_prob(_norm_cdf(d2))


def time_remaining_seconds(end_date: str | None, *, now: datetime | None = None) -> float | None:
    parsed = parse_end_date(end_date)
    if parsed is None:
        return None
    current = now or datetime.now(UTC)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return (parsed - current).total_seconds()


def compute_twap_snapshot(
    spec: TwapResolutionSpec,
    observation: OfficialTwapObservation,
    *,
    time_remaining_s: float,
    config: TwapFairValueConfig | None = None,
) -> TwapSnapshot:
    cfg = config or TwapFairValueConfig()
    if not spec.complete or spec.window_seconds is None or spec.symbol is None or spec.strike is None:
        raise ValueError("TWAP spec is incomplete; refuse to invent missing fields")
    if observation.window_seconds != spec.window_seconds:
        raise ValueError("observation window does not match parsed official window")
    if observation.symbol.lower() != spec.symbol.lower():
        raise ValueError("observation symbol does not match parsed official symbol")

    current = observation.value
    strike = spec.strike
    # Persistence of the official observation — not a homemade projected TWAP.
    projected = current
    distance = current - strike
    # Required official TWAP at expiry. Cannot reconstruct Chainlink remainder.
    required = strike
    remaining = max(time_remaining_s, 0.0)
    if remaining < cfg.min_time_remaining_s and remaining > 0:
        remaining = time_remaining_s
    p_above = digital_prob_above(
        spot=current,
        strike=strike,
        time_remaining_s=remaining,
        annualized_vol=cfg.paper_annualized_vol,
    )
    return TwapSnapshot(
        current_twap=current,
        projected_twap=projected,
        distance_to_strike=distance,
        time_remaining_s=time_remaining_s,
        required_future_price=required,
        probability_of_finish_above=p_above,
        probability_of_finish_below=_clip_prob(1.0 - p_above),
        window_seconds=spec.window_seconds,
        symbol=spec.symbol,
        opening_reference=spec.opening_reference,
        strike=strike,
        feed=spec.feed,
        source=observation.source,
        final_calculation_rule=spec.final_calculation_rule,
    )


def twap_p_info_for_market(market: MarketRecord, snapshot: TwapSnapshot) -> float:
    label = (market.outcomes[0] if market.outcomes else "yes").lower()
    if "down" in label or label in {"no"}:
        return snapshot.probability_of_finish_below
    return snapshot.probability_of_finish_above
