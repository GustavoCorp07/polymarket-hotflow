"""Event-driven backtester (Parte 26) and anti-overfit hooks (Parte 27)."""

from hotflow.backtest.engine import EventDrivenBacktester, NullBacktester
from hotflow.backtest.events import EventSource, FixtureEventSource, ListEventSource, MarketEvent
from hotflow.backtest.metrics import rank_reports, refuse_max_abs_pnl_selection
from hotflow.backtest.shadow import attach_shadow_fields, run_shadow
from hotflow.backtest.splits import walk_forward_windows

__all__ = [
    "EventDrivenBacktester",
    "EventSource",
    "FixtureEventSource",
    "ListEventSource",
    "MarketEvent",
    "NullBacktester",
    "attach_shadow_fields",
    "rank_reports",
    "refuse_max_abs_pnl_selection",
    "run_shadow",
    "walk_forward_windows",
]
