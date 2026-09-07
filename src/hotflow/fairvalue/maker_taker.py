"""Parte 17 — choose MAKER vs TAKER by expected value. No LLM."""

from __future__ import annotations

from hotflow.config import MakerTakerConfig
from hotflow.types import EdgeBreakdown, LiquidityStyle


def choose_style(edge: EdgeBreakdown, cfg: MakerTakerConfig) -> tuple[LiquidityStyle, float, float]:
    ev_taker = edge.net_expected_edge
    maker_fee = 0.0  # official docs: makers are never charged
    persist = max(0.0, edge.raw_edge - maker_fee - edge.adverse_selection * cfg.maker_adverse_mult)
    ev_maker = persist * cfg.maker_fill_probability
    if ev_maker > ev_taker:
        return LiquidityStyle.MAKER, ev_maker, ev_taker
    return LiquidityStyle.TAKER, ev_maker, ev_taker
