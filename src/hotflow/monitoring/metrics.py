from __future__ import annotations

from prometheus_client import CollectorRegistry, Counter, Gauge, start_http_server


class MetricsRegistry:
    def __init__(self) -> None:
        self.registry = CollectorRegistry()
        self.signals = Counter("hotflow_signals_total", "Signals", ["reason"], registry=self.registry)
        self.orders = Counter("hotflow_orders_total", "Orders", ["status"], registry=self.registry)
        self.hms = Gauge("hotflow_hms", "Latest HMS", ["market_id"], registry=self.registry)
        self.kill = Gauge("hotflow_kill_switch", "Kill switch tripped", registry=self.registry)

    def serve(self, port: int) -> None:
        start_http_server(port, registry=self.registry)
