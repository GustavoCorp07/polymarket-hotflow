"""Prometheus metrics for paper / backtest / shadow. No invented venue fees."""

from __future__ import annotations

from prometheus_client import CollectorRegistry, Counter, Gauge, Histogram

# Seconds. Grafana `histogram_quantile` yields p50 / p90 / p99.
LATENCY_BUCKETS = (0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0)

REQUIRED_METRIC_NAMES = (
    "hotflow_equity",
    "hotflow_realized_pnl",
    "hotflow_unrealized_pnl",
    "hotflow_daily_pnl",
    "hotflow_drawdown",
    "hotflow_win_rate",
    "hotflow_expectancy",
    "hotflow_fill_ratio",
    "hotflow_hot_markets",
    "hotflow_opportunity_score",
    "hotflow_exposure",
    "hotflow_kill_switch",
    "hotflow_ws_health",
    "hotflow_rtds_health",
    "hotflow_sports_health",
    "hotflow_signals_total",
    "hotflow_trades_total",
    "hotflow_orders_total",
    "hotflow_fees_total",
    "hotflow_slippage_total",
    "hotflow_fill_attempts_total",
    "hotflow_fills_total",
    "hotflow_api_errors_total",
    "hotflow_alerts_total",
    "hotflow_signal_latency_seconds",
    "hotflow_order_latency_seconds",
    "hotflow_hms",
    "hotflow_ready",
    "hotflow_process_start_timestamp_seconds",
)


class MetricsRegistry:
    def __init__(self, registry: CollectorRegistry | None = None) -> None:
        self.registry = registry or CollectorRegistry()
        self._wins = 0
        self._closed = 0
        self._pnl_sum = 0.0
        self._fill_attempts = 0
        self._fills = 0

        self.equity = Gauge("hotflow_equity", "Paper session ledger equity", registry=self.registry)
        self.realized_pnl = Gauge(
            "hotflow_realized_pnl", "Paper ledger realized PnL from closed fills", registry=self.registry
        )
        self.unrealized_pnl = Gauge(
            "hotflow_unrealized_pnl", "Paper ledger unrealized PnL at last marks", registry=self.registry
        )
        self.daily_pnl = Gauge(
            "hotflow_daily_pnl", "Paper ledger realized PnL (session/day)", registry=self.registry
        )
        self.drawdown = Gauge("hotflow_drawdown", "Drawdown fraction from peak", registry=self.registry)
        self.win_rate = Gauge(
            "hotflow_win_rate", "Closed-trade win rate from paper ledger", registry=self.registry
        )
        self.expectancy = Gauge("hotflow_expectancy", "Mean closed-trade PnL", registry=self.registry)
        self.fill_ratio = Gauge("hotflow_fill_ratio", "Filled size / intended size", registry=self.registry)
        self.hot_markets = Gauge(
            "hotflow_hot_markets", "Hot-market count by tier", ["tier"], registry=self.registry
        )
        self.opportunity_score = Gauge(
            "hotflow_opportunity_score", "Latest opportunity score", ["category"], registry=self.registry
        )
        self.exposure = Gauge(
            "hotflow_exposure", "Notional exposure by category", ["category"], registry=self.registry
        )
        self.kill = Gauge("hotflow_kill_switch", "Kill switch tripped", registry=self.registry)
        self.ws_health = Gauge(
            "hotflow_ws_health", "Feed freshness 1=fresh 0=stale", ["feed"], registry=self.registry
        )
        self.rtds_health = Gauge("hotflow_rtds_health", "RTDS / TWAP cache health", registry=self.registry)
        self.sports_health = Gauge(
            "hotflow_sports_health", "Sports WS / cache health", registry=self.registry
        )
        self.ready = Gauge("hotflow_ready", "Process ready (not killed, not LIVE)", registry=self.registry)
        self.process_start = Gauge(
            "hotflow_process_start_timestamp_seconds",
            "Unix time when this registry was created",
            registry=self.registry,
        )
        self.hms = Gauge("hotflow_hms", "Latest HMS", ["tier"], registry=self.registry)

        self.signals = Counter(
            "hotflow_signals_total", "Signals", ["decision", "reason"], registry=self.registry
        )
        self.trades = Counter("hotflow_trades_total", "Trades", ["status"], registry=self.registry)
        self.orders = Counter("hotflow_orders_total", "Orders", ["status"], registry=self.registry)
        self.fees = Counter(
            "hotflow_fees_total", "Fee units from fetched/fixture schedules", registry=self.registry
        )
        self.slippage = Counter(
            "hotflow_slippage_total", "Recorded slippage units", registry=self.registry
        )
        self.fill_attempts = Counter(
            "hotflow_fill_attempts_total", "Fill attempts", registry=self.registry
        )
        self.fills = Counter("hotflow_fills_total", "Fills with size > 0", registry=self.registry)
        self.maker_fills = Counter("hotflow_maker_fills_total", "Maker fills", registry=self.registry)
        self.taker_fills = Counter("hotflow_taker_fills_total", "Taker fills", registry=self.registry)
        self.api_errors = Counter(
            "hotflow_api_errors_total", "Local API / scanner errors", ["source"], registry=self.registry
        )
        self.alerts = Counter("hotflow_alerts_total", "Alert emissions", ["kind"], registry=self.registry)

        self.signal_latency = Histogram(
            "hotflow_signal_latency_seconds",
            "Evaluate-market latency",
            buckets=LATENCY_BUCKETS,
            registry=self.registry,
        )
        self.order_latency = Histogram(
            "hotflow_order_latency_seconds",
            "Paper submit/fill latency",
            buckets=LATENCY_BUCKETS,
            registry=self.registry,
        )
        self.request_latency = Histogram(
            "hotflow_request_latency_seconds",
            "Local HTTP / scan request latency",
            buckets=LATENCY_BUCKETS,
            registry=self.registry,
        )

    def registered_names(self) -> set[str]:
        names: set[str] = set()
        for metric in self.registry.collect():
            names.add(metric.name)
            if metric.type == "counter":
                # Family name omits _total until a labeled child exists.
                names.add(f"{metric.name}_total")
            for sample in metric.samples:
                names.add(sample.name)
        return names

    def note_closed_trade(self, pnl: float) -> None:
        self._closed += 1
        self._pnl_sum += pnl
        if pnl > 0:
            self._wins += 1
        self.win_rate.set(self._wins / self._closed if self._closed else 0.0)
        self.expectancy.set(self._pnl_sum / self._closed if self._closed else 0.0)

    def note_fill_attempt(self, *, filled: bool, fill_ratio: float, style: str | None = None) -> None:
        self._fill_attempts += 1
        self.fill_attempts.inc()
        if filled:
            self._fills += 1
            self.fills.inc()
            if style and style.upper() == "MAKER":
                self.maker_fills.inc()
            elif style and style.upper() == "TAKER":
                self.taker_fills.inc()
        ratio = self._fills / self._fill_attempts if self._fill_attempts else 0.0
        self.fill_ratio.set(fill_ratio if fill_ratio >= 0 else ratio)

    def serve(self, port: int, bind: str = "127.0.0.1") -> None:
        """Optional localhost scrape. Prefer Observability.start_http for /health."""
        from hotflow.monitoring.http import start_metrics_server

        start_metrics_server(bind=bind, port=port, registry=self.registry)
