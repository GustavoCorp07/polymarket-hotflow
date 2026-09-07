"""Light observer facade for paper / backtest / shadow. Stay off the LIVE path."""

from __future__ import annotations

import os
import time
from http.server import ThreadingHTTPServer
from typing import Any

from hotflow.config import HotflowConfig, MonitoringConfig
from hotflow.marketdata.clock import monotonic_ms
from hotflow.monitoring.alerts import Alert, AlertCallback, AlertKind, AlertRouter, kinds_for_kill
from hotflow.monitoring.dashboard import DASHBOARD_PORT, DashboardHub
from hotflow.monitoring.health import HealthState
from hotflow.monitoring.http import start_metrics_server, stop_metrics_server
from hotflow.monitoring.json_logs import JsonLogger
from hotflow.monitoring.metrics import MetricsRegistry
from hotflow.risk.kill_switch import KillEvent


def http_enabled(config: HotflowConfig) -> bool:
    env = os.environ.get("HOTFLOW_METRICS", "").strip().lower()
    if env in {"1", "true", "yes", "on"}:
        return True
    return bool(config.monitoring.http_enabled)


class Observability:
    """JSON logs + Prometheus + alerts. Cheap increments; no LLM; no secrets."""

    def __init__(
        self,
        config: HotflowConfig | None = None,
        *,
        metrics: MetricsRegistry | None = None,
        logger: JsonLogger | None = None,
        alerts: AlertRouter | None = None,
        announce_restart: bool = False,
    ) -> None:
        self.config = config or HotflowConfig()
        self.mon: MonitoringConfig = self.config.monitoring
        self.metrics = metrics or MetricsRegistry()
        self.logger = logger or JsonLogger()
        from hotflow.execution.live_gate import live_gates_open

        self.health = HealthState(
            mode=self.config.trading.mode,
            live_gates_open=live_gates_open(self.config),
        )
        self.alerts = alerts or AlertRouter(self.logger, on_emit=self._on_alert)
        self.dashboard = DashboardHub(self.health)
        self.dashboard.attach_live_gates(self.config)
        self._http: ThreadingHTTPServer | None = None
        self._drawdown_alerted = False
        self._audit_cursor = 0
        self.metrics.process_start.set(time.time())
        self.metrics.kill.set(0)
        self._sync_ready()
        if announce_restart:
            self.alert(AlertKind.PROCESS_RESTART, "process start", mode=self.health.mode)

    @classmethod
    def from_config(
        cls,
        config: HotflowConfig,
        *,
        announce_restart: bool = False,
        callback: AlertCallback | None = None,
    ) -> Observability:
        obs = cls(config, announce_restart=announce_restart)
        if callback is not None:
            obs.alerts.add_callback(callback)
        return obs

    def _on_alert(self, alert: Alert) -> None:
        self.metrics.alerts.labels(kind=alert.kind.value).inc()

    def _sync_ready(self) -> None:
        self.health.mode = self.config.trading.mode
        self.metrics.ready.set(1 if self.health.ready else 0)

    def add_alert_callback(self, callback: AlertCallback) -> None:
        self.alerts.add_callback(callback)

    def start_http(self, *, bind: str | None = None, port: int | None = None) -> Any:
        if self._http is not None:
            return self._http
        host = bind if bind is not None else self.mon.http_bind
        listen = self.mon.prometheus_port if port is None else port
        self._http = start_metrics_server(
            bind=host,
            port=listen,
            registry=self.metrics.registry,
            health=self.health,
            logger=self.logger,
            hub=self.dashboard,
        )
        return self._http

    def start_dashboard(self, *, bind: str | None = None, port: int | None = None) -> Any:
        """Same localhost server as metrics; default dashboard port 9109."""
        listen = DASHBOARD_PORT if port is None else port
        return self.start_http(bind=bind, port=listen)

    @property
    def http_addr(self) -> tuple[str, int] | None:
        if self._http is None:
            return None
        host, port = self._http.server_address[:2]
        return str(host), int(port)

    def stop_http(self) -> None:
        if self._http is not None:
            stop_metrics_server(self._http)
            self._http = None

    def alert(self, kind: AlertKind | str, message: str, **fields: Any) -> Alert:
        return self.alerts.emit(kind, message, **fields)

    def on_kill_event(self, event: KillEvent) -> None:
        self.health.kill_switch = True
        self.health.kill_reason = event.reason.value
        self.metrics.kill.set(1)
        self._sync_ready()
        payload = {"reason": event.reason.value, "detail": event.detail, "mode": self.health.mode}
        for kind in kinds_for_kill(event.reason):
            self.alert(kind, f"kill switch {event.reason.value}", **payload)

    def note_kill_clear(self) -> None:
        self.health.kill_switch = False
        self.health.kill_reason = None
        self.metrics.kill.set(0)
        self._sync_ready()

    def note_api_error(self, source: str, error: str) -> None:
        self.metrics.api_errors.labels(source=source).inc()
        self.health.last_error = error
        self.logger.emit("api_error", source=source, error=error, mode=self.health.mode)
        if source in {"auth", "user_ws"}:
            self.alert(AlertKind.AUTH_FAILURE, "auth failure", source=source, error=error)

    def set_feed_health(self, feed: str, healthy: bool) -> None:
        value = 1.0 if healthy else 0.0
        self.metrics.ws_health.labels(feed=feed).set(value)
        if feed == "rtds":
            self.metrics.rtds_health.set(value)
        elif feed == "sports_ws":
            self.metrics.sports_health.set(value)
        if not healthy and feed in {"market_ws", "user_ws", "rtds", "sports_ws", "clob_book"}:
            self.alert(AlertKind.STALE_WS, "stale feed", feed=feed)

    def set_equity_pnl(
        self,
        *,
        equity: float | None = None,
        realized: float | None = None,
        unrealized: float | None = None,
        daily: float | None = None,
        drawdown: float | None = None,
        expectancy: float | None = None,
    ) -> None:
        if equity is not None:
            self.metrics.equity.set(equity)
        if realized is not None:
            self.metrics.realized_pnl.set(realized)
        if unrealized is not None:
            self.metrics.unrealized_pnl.set(unrealized)
        if daily is not None:
            self.metrics.daily_pnl.set(daily)
        if drawdown is not None:
            self.metrics.drawdown.set(drawdown)
            if drawdown >= self.mon.alert_drawdown and not self._drawdown_alerted:
                self._drawdown_alerted = True
                self.alert(AlertKind.DRAWDOWN, "drawdown threshold", drawdown=drawdown)
        if expectancy is not None:
            self.metrics.expectancy.set(expectancy)

    def publish_ledger(self, snap: Any) -> None:
        self.set_equity_pnl(
            equity=float(snap.equity),
            realized=float(snap.realized_pnl),
            unrealized=float(snap.unrealized_pnl),
            daily=float(snap.realized_pnl),
            drawdown=float(snap.drawdown),
            expectancy=float(snap.expectancy),
        )
        self.metrics.win_rate.set(float(snap.win_rate))
        self.dashboard.note_ledger(snap)
        if self.mon.json_logs:
            self.logger.emit("ledger", **snap.as_dict())

    def set_exposure(self, category: str, notional: float) -> None:
        self.metrics.exposure.labels(category=category).set(notional)

    def set_hot_markets(self, counts: dict[str, int]) -> None:
        for tier, count in counts.items():
            self.metrics.hot_markets.labels(tier=str(tier)).set(count)

    def observe_signal_latency(self, latency_ms: float) -> None:
        self.metrics.signal_latency.observe(max(0.0, latency_ms) / 1000.0)
        if latency_ms >= self.mon.alert_latency_ms:
            self.alert(AlertKind.HIGH_LATENCY, "high signal latency", latency_ms=latency_ms)

    def observe_order_latency(self, latency_ms: float) -> None:
        self.metrics.order_latency.observe(max(0.0, latency_ms) / 1000.0)
        if latency_ms >= self.mon.alert_latency_ms:
            self.alert(AlertKind.HIGH_LATENCY, "high order latency", latency_ms=latency_ms)

    def after_evaluate(
        self,
        result: dict[str, Any],
        *,
        latency_ms: float,
        market_id: str,
        category: str = "other",
        session_id: str = "",
        kill_switch: bool = False,
        exposure: float | None = None,
        drawdown: float | None = None,
    ) -> None:
        """One cheap hook after evaluate_market. Avoid dumping extras."""
        accepted = bool(result.get("accepted"))
        reason = str(result.get("reason") or "NO_TRADE")
        decision = "TRADE" if accepted else "SKIP"
        if reason == "SHADOW_MODE":
            decision = "SHADOW"
        edge_raw = result.get("edge")
        opp_raw = result.get("opportunity")
        edge: dict[str, Any] = edge_raw if isinstance(edge_raw, dict) else {}
        opp: dict[str, Any] = opp_raw if isinstance(opp_raw, dict) else {}
        hms = result.get("hms")
        if hms is None:
            nested_hms = opp.get("hms")
            if isinstance(nested_hms, dict):
                hms = nested_hms.get("score")
        net_edge = edge.get("net_expected_edge")
        opp_score = opp.get("score")
        if self.mon.json_logs:
            self.logger.signal(
                market_id=market_id,
                decision=decision,
                reason=reason,
                accepted=accepted,
                mode=self.health.mode,
                session_id=session_id,
                hms=float(hms) if hms is not None else None,
                net_edge=float(net_edge) if net_edge is not None else None,
                opportunity_score=float(opp_score) if opp_score is not None else None,
                latency_ms=round(latency_ms, 3),
                side=result.get("side"),
            )
        self.metrics.signals.labels(decision=decision, reason=reason).inc()
        self.observe_signal_latency(latency_ms)
        self.dashboard.note_decision(
            {
                **result,
                "market_id": market_id,
                "accepted": accepted,
                "reason": reason,
            }
        )
        if hms is not None:
            tier = "unknown"
            nested_hms = opp.get("hms")
            nested: dict[str, Any] = nested_hms if isinstance(nested_hms, dict) else {}
            if nested.get("tier"):
                tier = str(nested["tier"])
            self.metrics.hms.labels(tier=tier).set(float(hms))
        if opp_score is not None:
            self.metrics.opportunity_score.labels(category=category or "other").set(float(opp_score))
        if "reason" in result:
            if self.mon.json_logs:
                self.logger.risk_decision(
                    market_id=market_id,
                    allowed=accepted,
                    reason=reason,
                    veto=not accepted,
                    detail=str(result.get("detail") or ""),
                    kill_switch=kill_switch,
                    exposure=exposure,
                    drawdown=drawdown,
                    mode=self.health.mode,
                )
        order = result.get("order")
        if isinstance(order, dict):
            self.after_order(order, edge=edge, latency_ms=None)
        if kill_switch and reason in {"STALE_DATA", "KILL_SWITCH"}:
            # Kill callback already alerts; keep gauges in sync if trip happened mid-eval.
            self.health.kill_switch = True
            self.metrics.kill.set(1)
            self._sync_ready()

    def after_order(
        self,
        order: dict[str, Any],
        *,
        edge: dict[str, Any] | None = None,
        latency_ms: float | None = None,
        style: str | None = None,
    ) -> None:
        status = str(order.get("status") or "UNKNOWN")
        size = float(order.get("size") or 0.0)
        filled = float(order.get("filled_size") or 0.0)
        price = float(order.get("price") or 0.0)
        ratio = (filled / size) if size else 0.0
        fee_ps = float((edge or {}).get("fee_per_share") or 0.0)
        slip_ps = float((edge or {}).get("slippage") or 0.0)
        fees = fee_ps * filled
        slippage = slip_ps * filled
        self.metrics.orders.labels(status=status).inc()
        self.metrics.trades.labels(status=status).inc()
        if fees:
            self.metrics.fees.inc(fees)
        if slippage:
            self.metrics.slippage.inc(slippage)
            if slip_ps >= self.mon.alert_slippage:
                self.alert(AlertKind.HIGH_SLIPPAGE, "high slippage", slippage=slip_ps)
        self.metrics.note_fill_attempt(filled=filled > 0, fill_ratio=ratio, style=style)
        if latency_ms is not None:
            self.observe_order_latency(latency_ms)
        if self.mon.json_logs:
            self.logger.trade(
                market_id=str(order.get("market_id") or ""),
                status=status,
                side=str(order.get("side") or ""),
                size=size,
                price=price,
                filled_size=filled,
                fill_ratio=ratio,
                fees=fees,
                slippage=slippage,
                client_order_id=order.get("client_order_id"),
                mode=self.health.mode,
            )

    def observe_backtest_report(self, report: dict[str, Any]) -> None:
        metrics_raw = report.get("metrics")
        metrics: dict[str, Any] = metrics_raw if isinstance(metrics_raw, dict) else {}
        self.set_equity_pnl(
            realized=float(metrics.get("abs_pnl") or 0.0),
            daily=float(metrics.get("abs_pnl") or 0.0),
            drawdown=float(metrics.get("max_drawdown") or 0.0),
            expectancy=float(metrics.get("expectancy") or 0.0),
        )
        self.metrics.win_rate.set(float(metrics.get("win_rate") or 0.0))
        fees = float(metrics.get("fees") or 0.0)
        slip = float(metrics.get("slippage") or 0.0)
        if fees:
            self.metrics.fees.inc(fees)
        if slip:
            self.metrics.slippage.inc(slip)
        trades_raw = report.get("trades")
        trades: list[Any] = trades_raw if isinstance(trades_raw, list) else []
        for trade in trades:
            if not isinstance(trade, dict):
                continue
            pnl = trade.get("pnl")
            if pnl is not None:
                self.metrics.note_closed_trade(float(pnl))
            self.metrics.trades.labels(status="BACKTEST").inc()
            self.metrics.note_fill_attempt(
                filled=True,
                fill_ratio=1.0,
                style=str(trade.get("style") or ""),
            )

    def observe_shadow(self, rows: list[dict[str, Any]]) -> None:
        for row in rows:
            intent = "skip"
            if row.get("would_buy"):
                intent = "would_buy"
            elif row.get("would_sell"):
                intent = "would_sell"
            reason = str(row.get("reason") or "NO_TRADE")
            self.metrics.shadow_decisions.labels(intent=intent, reason=reason).inc()
            if self.mon.json_logs:
                fill = row.get("simulated_fill") if isinstance(row.get("simulated_fill"), dict) else {}
                self.logger.emit(
                    "shadow",
                    mode="shadow",
                    market_id=row.get("market_id"),
                    reason=reason,
                    would_buy=bool(row.get("would_buy")),
                    would_sell=bool(row.get("would_sell")),
                    expected_price=row.get("expected_price"),
                    actual_price_after_signal=row.get("actual_price_after_signal"),
                    simulated_fill_sent=False,
                    signal_complete=bool(row.get("signal_complete")),
                    style=fill.get("style") if isinstance(fill, dict) else None,
                )
        if self.mon.json_logs:
            self.logger.emit("shadow_summary", decisions=len(rows), sent_orders=False, mode="shadow")

    def snapshot_pipeline(self, pipe: Any) -> None:
        """End-of-cycle gauges from risk / broker / clock. Not per-tick."""
        risk = getattr(pipe, "risk", None)
        broker = getattr(pipe, "broker", None)
        clock = getattr(pipe, "clock", None)
        kills = getattr(pipe, "kills", None)
        ledger = getattr(pipe, "ledger", None)
        if ledger is not None:
            self.publish_ledger(ledger.snapshot())
        elif risk is not None:
            realized = float(risk.state.session_pnl)
            daily = float(risk.state.daily_pnl)
            equity = float(self.config.trading.paper_starting_cash) + realized
            if broker is not None:
                equity = float(broker.cash)
            peak = float(risk.state.peak_equity) or equity
            drawdown = max(0.0, (peak - float(risk.state.equity)) / peak) if peak > 0 else 0.0
            self.set_equity_pnl(equity=equity, realized=realized, daily=daily, drawdown=drawdown)
        if risk is not None:
            for category, notional in risk.state.category_exposure.items():
                self.set_exposure(str(category), float(notional))
        if kills is not None:
            self.health.kill_switch = bool(kills.tripped)
            self.health.kill_reason = kills.reason.value if kills.reason else None
            self.metrics.kill.set(1 if kills.tripped else 0)
        feeds: dict[str, float | None] = {}
        if clock is not None:
            known = clock.samples()
            for feed in ("gamma", "clob_book", "clob_fees", "market_ws", "user_ws", "rtds", "sports_ws"):
                sample = known.get(feed)
                if sample is None:
                    continue
                age = clock.age_ms(feed)
                healthy = age is None or age <= sample.max_age_ms
                # Snapshot only — do not re-alert stale on every cycle end.
                value = 1.0 if healthy else 0.0
                feeds[feed] = value
                self.metrics.ws_health.labels(feed=feed).set(value)
                if feed == "rtds":
                    self.metrics.rtds_health.set(value)
                elif feed == "sports_ws":
                    self.metrics.sports_health.set(value)
        if feeds:
            self.dashboard.note_feeds(feeds)
        tiers: dict[str, int] = {}
        audits = list(getattr(pipe, "audits", []) or [])
        fresh = audits[self._audit_cursor :]
        self._audit_cursor = len(audits)
        hot_rows: list[dict[str, Any]] = []
        for audit in audits:
            tier = getattr(audit, "tier", None)
            if tier:
                tiers[str(tier)] = tiers.get(str(tier), 0) + 1
        for audit in fresh:
            extra = getattr(audit, "extra", None)
            extra_map: dict[str, Any] = extra if isinstance(extra, dict) else {}
            signal_raw = extra_map.get("signal")
            signal: dict[str, Any] = signal_raw if isinstance(signal_raw, dict) else {}
            audit_tier = getattr(audit, "tier", None)
            hot_rows.append(
                {
                    "market_id": getattr(audit, "market_id", ""),
                    "tier": str(audit_tier) if audit_tier else None,
                    "hms": getattr(audit, "hms", None),
                    "decision": "TRADE" if getattr(audit, "accepted", False) else "SKIP",
                    "reason": getattr(audit, "reason", None),
                    "reason_codes": signal.get("reason_codes") or [getattr(audit, "reason", "NO_TRADE")],
                    "spread_regime": signal.get("spread_regime"),
                }
            )
        if tiers:
            self.set_hot_markets(tiers)
        if hot_rows:
            self.dashboard.note_cycle(hot_rows)
        self._sync_ready()


def timed_ms() -> float:
    return monotonic_ms()
