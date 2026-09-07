"""Parte 45 — book microstructure. Each feature has an economic hypothesis.

Computed from a single CLOB L2 snapshot unless optional event history is passed.
Missing history is labeled N/A with `invented: false` — never filled in.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any

from hotflow.config import MicrostructureConfig
from hotflow.types import BookLevel, MarketRecord, OrderBook

# Mission list items that need a stream we do not have on paper snapshots.
_STREAM_UNAVAILABLE: dict[str, str] = {
    "order_flow_imbalance": (
        "needs signed L3 add/cancel/trade diffs; fixtures and paper path are L2 snapshots"
    ),
    "trade_imbalance": (
        "needs a signed print stream; MarketRecord.last_trade_price is one unsigned print"
    ),
    "cancel_imbalance": "no cancel events in CLOB book fixtures or paper evaluate",
    "book_replenishment": "needs timed L2 diffs showing size restoration after a take",
}


def microprice(book: OrderBook) -> float | None:
    """Size-weighted mid: closer to the thinner side (adverse-selection proxy)."""
    if not book.bids or not book.asks:
        return None
    bid, ask = book.bids[0], book.asks[0]
    denom = bid.size + ask.size
    if denom <= 0:
        return book.mid
    return (bid.price * ask.size + ask.price * bid.size) / denom


def imbalance(book: OrderBook) -> float | None:
    """Top-of-book imbalance in [-1, 1]. Positive = bid-heavy."""
    if not book.bids or not book.asks:
        return None
    bid_sz, ask_sz = book.bids[0].size, book.asks[0].size
    denom = bid_sz + ask_sz
    if denom <= 0:
        return 0.0
    return (bid_sz - ask_sz) / denom


def top_depth(book: OrderBook, levels: int = 3) -> tuple[float, float]:
    """Displayed size in the first N levels. Thin depth raises walk-the-book cost."""
    bid_d = sum(level.size for level in book.bids[:levels])
    ask_d = sum(level.size for level in book.asks[:levels])
    return bid_d, ask_d


def inferred_tick(book: OrderBook, market_tick: float | None = None) -> float:
    """Smallest observed adjacent gap, else book/market tick, else 0.01. Not invented mid."""
    if book.tick_size is not None and book.tick_size > 0:
        return float(book.tick_size)
    if market_tick is not None and market_tick > 0:
        return float(market_tick)
    deltas: list[float] = []
    for side in (book.bids, book.asks):
        for closer, farther in zip(side, side[1:], strict=False):
            delta = abs(closer.price - farther.price)
            if delta > 0:
                deltas.append(delta)
    if deltas:
        return min(deltas)
    return 0.01


def weighted_imbalance(
    book: OrderBook,
    *,
    levels: int = 5,
    decay: float = 0.70,
) -> float | None:
    """Depth-weighted imbalance with exponential level decay.

    Hypothesis: L1 can be fleeting or spoofed; decaying weight on deeper size is a
    more stable bid-vs-ask pressure signal than top-of-book alone.

    Definition: w_i = decay^i for level i (0 = touch).
    wimb = (Σ w_i bid_i − Σ w_i ask_i) / (Σ w_i bid_i + Σ w_i ask_i) in [-1, 1].
    """
    if not book.bids or not book.asks:
        return None
    n = max(1, levels)
    decay = min(1.0, max(0.0, decay))
    bid_w = 0.0
    ask_w = 0.0
    for index in range(min(n, max(len(book.bids), len(book.asks)))):
        weight = decay**index
        if index < len(book.bids):
            bid_w += weight * book.bids[index].size
        if index < len(book.asks):
            ask_w += weight * book.asks[index].size
    denom = bid_w + ask_w
    if denom <= 0:
        return 0.0
    return (bid_w - ask_w) / denom


def book_slope(
    book: OrderBook,
    *,
    levels: int = 5,
) -> tuple[float | None, float | None]:
    """Displayed size per probability point away from mid.

    Hypothesis: a steep slope means the book restocks quickly as price walks —
    lower expected impact for a given take. A flat slope is a thin ladder.

    Definition: slope_side = cum_size(N) / |p_N − mid|.
    Units: contracts per price point. Needs at least two levels on that side;
    otherwise None (not invented).
    """
    mid = book.mid
    if mid is None:
        return None, None

    def _slope(side: list[BookLevel], *, bids: bool) -> float | None:
        rows = side[: max(2, levels)]
        if len(rows) < 2:
            return None
        far = rows[min(len(rows), levels) - 1]
        distance = (mid - far.price) if bids else (far.price - mid)
        if distance <= 1e-12:
            return None
        cum = sum(level.size for level in rows[:levels])
        return cum / distance

    return _slope(book.bids, bids=True), _slope(book.asks, bids=False)


def depth_convexity(
    book: OrderBook,
    *,
    levels: int = 5,
) -> tuple[float | None, float | None]:
    """Near-vs-far size split on each side.

    Hypothesis: negative convexity (size piled at the touch) is easier to sweep
    and more spoof-sensitive; positive convexity (size further out) means a
    hollow near book that walks farther before hitting rest.

    Definition: split the first N levels into near (first ceil(N/2)) and far
    (the rest). convexity = (far − near) / (far + near) in [-1, 1].
    Needs at least two levels; otherwise None.
    """

    def _conv(side: list[BookLevel]) -> float | None:
        rows = side[: max(2, levels)]
        if len(rows) < 2:
            return None
        take = min(len(rows), levels)
        split = max(1, (take + 1) // 2)
        near = sum(level.size for level in rows[:split])
        far = sum(level.size for level in rows[split:take])
        denom = near + far
        if denom <= 0:
            return None
        return (far - near) / denom

    return _conv(book.bids), _conv(book.asks)


def liquidity_gaps(
    book: OrderBook,
    *,
    tick: float,
    multiple: float = 2.0,
) -> dict[str, float | int | None]:
    """Thin spots: adjacent level gaps at or above tick × multiple.

    Hypothesis: a hole between rungs forces a marketable order to jump extra
    ticks — impact that spread-at-touch understates.

    Definition: bid gap_i = bid_i.price − bid_{i+1}.price; ask gap_i is the
    symmetric up-move. A gap counts when gap >= tick * multiple − 1e-12.
    """
    threshold = max(tick, 0.0) * max(multiple, 0.0)

    def _side(side: list[BookLevel], *, bids: bool) -> tuple[float | None, int, float | None]:
        max_gap: float | None = None
        count = 0
        first: float | None = None
        for closer, farther in zip(side, side[1:], strict=False):
            gap = (closer.price - farther.price) if bids else (farther.price - closer.price)
            if gap < 0:
                gap = 0.0
            if max_gap is None or gap > max_gap:
                max_gap = gap
            if threshold > 0 and gap + 1e-12 >= threshold:
                count += 1
                if first is None:
                    first = gap
        return max_gap, count, first

    bid_max, bid_n, bid_first = _side(book.bids, bids=True)
    ask_max, ask_n, ask_first = _side(book.asks, bids=False)
    return {
        "max_bid_gap": bid_max,
        "max_ask_gap": ask_max,
        "bid_gap_count": bid_n,
        "ask_gap_count": ask_n,
        "first_bid_gap": bid_first,
        "first_ask_gap": ask_first,
        "gap_threshold": threshold if threshold > 0 else None,
    }


def walk_vwap(
    levels: list[tuple[float, float]],
    notional: float,
) -> dict[str, float | bool | None]:
    """VWAP of taking `notional` (price × size) from one side of the book.

    Hypothesis: VWAP − mid is the immediate adverse move for that size — a
    slippage proxy better than spread alone, and the same walk fair-value uses.

    Exhausted books report filled VWAP plus exhausted=true; they do not invent
    a residual fill at a fake price.
    """
    if notional <= 0 or not levels:
        return {
            "vwap": None,
            "shares": 0.0,
            "filled_notional": 0.0,
            "exhausted": True,
            "impact_vs_touch": None,
        }
    remaining = notional
    cost = 0.0
    shares = 0.0
    touch = levels[0][0]
    for price, size in levels:
        if price <= 0 or size <= 0:
            continue
        level_notional = price * size
        take_notional = min(remaining, level_notional)
        take_shares = take_notional / price
        cost += take_notional
        shares += take_shares
        remaining -= take_notional
        if remaining <= 1e-12:
            break
    exhausted = remaining > 1e-9
    if shares <= 0:
        return {
            "vwap": None,
            "shares": 0.0,
            "filled_notional": 0.0,
            "exhausted": True,
            "impact_vs_touch": None,
        }
    vwap = cost / shares
    return {
        "vwap": vwap,
        "shares": shares,
        "filled_notional": cost,
        "exhausted": exhausted,
        "impact_vs_touch": max(0.0, abs(vwap - touch)),
    }


def price_impact(
    book: OrderBook,
    *,
    notional: float,
) -> dict[str, float | bool | None]:
    """Buy and sell VWAP-to-depth vs mid for a probe notional."""
    mid = book.mid
    asks = [(lvl.price, lvl.size) for lvl in book.asks]
    bids = [(lvl.price, lvl.size) for lvl in book.bids]
    buy = walk_vwap(asks, notional)
    sell = walk_vwap(bids, notional)
    buy_imp = None
    sell_imp = None
    if mid is not None and buy["vwap"] is not None:
        buy_imp = max(0.0, float(buy["vwap"]) - mid)
    if mid is not None and sell["vwap"] is not None:
        sell_imp = max(0.0, mid - float(sell["vwap"]))
    return {
        "notional": notional,
        "buy_vwap": buy["vwap"],
        "sell_vwap": sell["vwap"],
        "impact_buy": buy_imp,
        "impact_sell": sell_imp,
        "exhausted_buy": bool(buy["exhausted"]),
        "exhausted_sell": bool(sell["exhausted"]),
        "buy_shares": buy["shares"],
        "sell_shares": sell["shares"],
    }


def spread_regime(
    spread: float | None,
    cfg: MicrostructureConfig,
    recent_spreads: list[float] | None = None,
) -> dict[str, Any]:
    """Rule-based tight / normal / wide. History is optional.

    Hypothesis: a wide book raises adverse-selection and inventory risk; a tight
    book is cheaper to cross but may be fleeting.

    When fewer than `min_history` recent spreads are present, the label uses
    YAML thresholds only (`vs=config`). A recent-median comparison is never
    invented.
    """
    if spread is None:
        return {
            "label": "N/A",
            "invented": False,
            "vs": None,
            "spread": None,
            "reason": "spread_missing",
        }
    history = [float(item) for item in (recent_spreads or []) if item is not None]
    if len(history) >= cfg.min_history:
        ordered = sorted(history)
        mid_i = len(ordered) // 2
        median = ordered[mid_i] if len(ordered) % 2 else 0.5 * (ordered[mid_i - 1] + ordered[mid_i])
        if median <= 1e-12:
            label = "normal"
        elif spread <= median * cfg.recent_tight_frac:
            label = "tight"
        elif spread >= median * cfg.recent_wide_frac:
            label = "wide"
        else:
            label = "normal"
        return {
            "label": label,
            "invented": False,
            "vs": "recent_median",
            "spread": spread,
            "recent_median": median,
            "n_recent": len(history),
        }
    if spread <= cfg.spread_tight:
        label = "tight"
    elif spread >= cfg.spread_wide:
        label = "wide"
    else:
        label = "normal"
    return {
        "label": label,
        "invented": False,
        "vs": "config",
        "spread": spread,
        "tight": cfg.spread_tight,
        "wide": cfg.spread_wide,
        "n_recent": len(history),
    }


def intensity_from_events(
    events: Sequence[Mapping[str, Any]] | None,
    *,
    now: datetime | None = None,
    window_s: float = 60.0,
) -> dict[str, Any]:
    """Quote / trade intensity from timestamped fixture events.

    Hypothesis: bursty book updates or prints mark information arrival.

    A single snapshot cannot support a rate. Quote intensity needs ≥2 book
    events; trade intensity needs ≥1 trade and a positive elapsed window.
    Prints without a side stay unsigned — no invented trade imbalance.
    """
    unused = {
        "quote_intensity": None,
        "trade_intensity": None,
        "quote_count": 0,
        "trade_count": 0,
        "window_s": window_s,
        "invented": False,
        "reason": "no_event_stream",
    }
    if not events:
        return unused
    parsed: list[tuple[datetime, str]] = []
    for row in events:
        ts = row.get("ts")
        kind = str(row.get("kind") or "")
        if not isinstance(ts, datetime) or kind not in {"book", "trade"}:
            continue
        parsed.append((ts, kind))
    if not parsed:
        return unused
    parsed.sort(key=lambda item: item[0])
    end = now or parsed[-1][0]
    end_ts = end.timestamp()
    start = end_ts - max(window_s, 0.0)
    # Decision-time window only — do not look ahead of `now`.
    windowed = [item for item in parsed if start - 1e-9 <= item[0].timestamp() <= end_ts + 1e-9]
    quotes = [item for item in windowed if item[1] == "book"]
    trades = [item for item in windowed if item[1] == "trade"]
    elapsed = window_s if window_s > 0 else 0.0
    quote_rate = (len(quotes) / elapsed) if elapsed > 0 and len(quotes) >= 2 else None
    trade_rate = (len(trades) / elapsed) if elapsed > 0 and len(trades) >= 1 else None
    reason = None
    if quote_rate is None and trade_rate is None:
        reason = "insufficient_events_in_window"
    return {
        "quote_intensity": quote_rate,
        "trade_intensity": trade_rate,
        "quote_count": len(quotes),
        "trade_count": len(trades),
        "window_s": window_s,
        "invented": False,
        "reason": reason,
    }


def _effective_spread(market: MarketRecord) -> float | None:
    if market.spread is not None:
        return market.spread
    if market.book is not None:
        return market.book.spread
    return None


def _not_available(intensity: dict[str, Any]) -> dict[str, str]:
    missing = dict(_STREAM_UNAVAILABLE)
    if intensity.get("quote_intensity") is None:
        missing["quote_intensity"] = str(intensity.get("reason") or "no_event_stream")
    if intensity.get("trade_intensity") is None:
        missing["trade_intensity"] = str(intensity.get("reason") or "no_event_stream")
    return missing


def microstructure_features(
    market: MarketRecord,
    cfg: MicrostructureConfig | None = None,
    *,
    recent_spreads: list[float] | None = None,
    events: Sequence[Mapping[str, Any]] | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Snapshot + N/A map. Backward-compatible keys: mid, microprice, imbalance, spread, depths."""
    cfg = cfg or MicrostructureConfig()
    book = market.book
    spread = _effective_spread(market)
    mid = book.mid if book else None
    if mid is None and market.best_bid is not None and market.best_ask is not None:
        mid = (market.best_bid + market.best_ask) / 2.0
    intensity = intensity_from_events(events, now=now, window_s=cfg.intensity_window_s)
    if book is None:
        return {
            "mid": mid,
            "microprice": None,
            "imbalance": None,
            "weighted_imbalance": None,
            "spread": spread,
            "bid_depth": None,
            "ask_depth": None,
            "bid_slope": None,
            "ask_slope": None,
            "bid_convexity": None,
            "ask_convexity": None,
            "max_bid_gap": None,
            "max_ask_gap": None,
            "bid_gap_count": None,
            "ask_gap_count": None,
            "impact_buy": None,
            "impact_sell": None,
            "exhausted_buy": None,
            "exhausted_sell": None,
            "impact_notional": cfg.impact_notional,
            "spread_regime": spread_regime(spread, cfg, recent_spreads),
            "intensity": intensity,
            "not_available": _not_available(intensity),
            "invented": False,
        }
    n = cfg.depth_levels
    micro = microprice(book)
    imb = imbalance(book)
    wimb = weighted_imbalance(book, levels=n, decay=cfg.imbalance_decay)
    bid_d, ask_d = top_depth(book, n)
    bid_slope, ask_slope = book_slope(book, levels=n)
    bid_cx, ask_cx = depth_convexity(book, levels=n)
    tick = inferred_tick(book, market.tick_size)
    gaps = liquidity_gaps(book, tick=tick, multiple=cfg.gap_multiple)
    impact = price_impact(book, notional=cfg.impact_notional)
    return {
        "mid": mid,
        "microprice": micro,
        "imbalance": imb,
        "weighted_imbalance": wimb,
        "spread": spread if spread is not None else book.spread,
        "bid_depth": bid_d,
        "ask_depth": ask_d,
        "depth_levels": n,
        "bid_slope": bid_slope,
        "ask_slope": ask_slope,
        "bid_convexity": bid_cx,
        "ask_convexity": ask_cx,
        "tick": tick,
        **gaps,
        "impact_buy": impact["impact_buy"],
        "impact_sell": impact["impact_sell"],
        "exhausted_buy": impact["exhausted_buy"],
        "exhausted_sell": impact["exhausted_sell"],
        "buy_vwap": impact["buy_vwap"],
        "sell_vwap": impact["sell_vwap"],
        "impact_notional": cfg.impact_notional,
        "spread_regime": spread_regime(spread if spread is not None else book.spread, cfg, recent_spreads),
        "intensity": intensity,
        "not_available": _not_available(intensity),
        "invented": False,
    }


def compact_microstructure(feats: Mapping[str, Any] | None) -> dict[str, Any]:
    """Parte 46 audit subset — no secrets, no full book."""
    if not feats:
        return {}
    keys = (
        "mid",
        "spread",
        "microprice",
        "imbalance",
        "weighted_imbalance",
        "bid_depth",
        "ask_depth",
        "bid_slope",
        "ask_slope",
        "bid_convexity",
        "ask_convexity",
        "max_bid_gap",
        "max_ask_gap",
        "bid_gap_count",
        "ask_gap_count",
        "impact_buy",
        "impact_sell",
        "exhausted_buy",
        "exhausted_sell",
        "impact_notional",
        "spread_regime",
        "intensity",
        "not_available",
        "invented",
    )
    return {key: feats[key] for key in keys if key in feats}
