"""Official taker fee curve. Rate must come from a fetched schedule.

docs.polymarket.com/trading/fees:
    fee = C × feeRate × p × (1 - p)

Market-details also expose feeSchedule.exponent on the price component.
When exponent is present we apply it to p*(1-p) as documented ("exponent
applied to the price component"). We never substitute a category default.
"""

from __future__ import annotations

from hotflow.reason_codes import ReasonCode
from hotflow.types import FeeSchedule


class UnknownFeesError(ValueError):
    reason = ReasonCode.UNKNOWN_FEES


def taker_fee_per_share(price: float, fees: FeeSchedule) -> float:
    if not fees.known:
        raise UnknownFeesError("fee_enabled was not fetched from Gamma/CLOB")
    if fees.enabled is False:
        return 0.0
    if fees.rate is None:
        raise UnknownFeesError("fee_rate missing from official schedule")
    if price <= 0.0 or price >= 1.0:
        return 0.0
    price_component = price * (1.0 - price)
    exponent = fees.exponent if fees.exponent is not None else 1.0
    # Official published formula uses exponent 1 (p*(1-p)). Extra exponent
    # is only applied when the live schedule provides it.
    if exponent != 1.0:
        price_component = price_component**exponent
    fee = float(fees.rate) * float(price_component)
    return round(max(0.0, fee), 5)


def walk_slippage(levels: list[tuple[float, float]], shares: float, is_buy: bool) -> float:
    """Share-weighted distance from touch. Not a venue fee."""
    if shares <= 0 or not levels:
        return 0.0
    remaining = shares
    cost = 0.0
    filled = 0.0
    touch = levels[0][0]
    for price, size in levels:
        take = min(remaining, size)
        cost += take * price
        filled += take
        remaining -= take
        if remaining <= 1e-12:
            break
    if filled <= 0:
        return 1.0
    avg = cost / filled
    raw = (avg - touch) if is_buy else (touch - avg)
    return max(0.0, raw)
