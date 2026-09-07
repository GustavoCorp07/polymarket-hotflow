"""Event-driven backtester (Parte 26) and anti-overfit hooks (Parte 27)."""

from hotflow.backtest.engine import EventDrivenBacktester, NullBacktester
from hotflow.backtest.events import EventSource, FixtureEventSource, ListEventSource, MarketEvent
from hotflow.backtest.metrics import rank_reports, refuse_max_abs_pnl_selection
from hotflow.backtest.recorder import build_synthetic_longer_stream
from hotflow.backtest.shadow import (
    SHADOW_REQUIRED_FIELDS,
    ShadowSession,
    attach_shadow_fields,
    compare_shadow_vs_paper,
    run_shadow,
    run_stale_probe,
    shadow_completeness,
)
from hotflow.backtest.splits import walk_forward_windows

__all__ = [
    "EventDrivenBacktester",
    "EventSource",
    "FixtureEventSource",
    "ListEventSource",
    "MarketEvent",
    "NullBacktester",
    "SHADOW_REQUIRED_FIELDS",
    "ShadowSession",
    "attach_shadow_fields",
    "build_synthetic_longer_stream",
    "compare_shadow_vs_paper",
    "rank_reports",
    "refuse_max_abs_pnl_selection",
    "run_shadow",
    "run_stale_probe",
    "shadow_completeness",
    "walk_forward_windows",
]
