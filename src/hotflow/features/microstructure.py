"""Parte 45 — book microstructure with an economic hypothesis each."""

from __future__ import annotations

from hotflow.types import MarketRecord, OrderBook


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
    bid_d = sum(level.size for level in book.bids[:levels])
    ask_d = sum(level.size for level in book.asks[:levels])
    return bid_d, ask_d


def microstructure_features(market: MarketRecord) -> dict[str, float | None]:
    book = market.book
    mid = book.mid if book else None
    if mid is None and market.best_bid is not None and market.best_ask is not None:
        mid = (market.best_bid + market.best_ask) / 2.0
    micro = microprice(book) if book else None
    imb = imbalance(book) if book else None
    bid_d, ask_d = top_depth(book) if book else (None, None)
    return {
        "mid": mid,
        "microprice": micro,
        "imbalance": imb,
        "spread": market.spread if market.spread is not None else (book.spread if book else None),
        "bid_depth": bid_d,
        "ask_depth": ask_d,
    }
