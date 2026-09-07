# Dashboards

Paper-mode scrape notes only. Full Grafana dashboards are optional and not
shipped. Do not invent Polymarket endpoints or fee series.

## Prometheus scrape

HOTFLOW optional HTTP (default bind `127.0.0.1:9108`, off unless enabled):

```text
hotflow serve-metrics
# or: HOTFLOW_METRICS=1 hotflow paper-run --mock --serve-metrics
```

Example scrape config:

```yaml
scrape_configs:
  - job_name: hotflow
    static_configs:
      - targets: ["127.0.0.1:9108"]
    metrics_path: /metrics
```

Useful series:

| Series | Notes |
| --- | --- |
| `hotflow_equity` / `hotflow_*_pnl` / `hotflow_drawdown` | Paper placeholders |
| `hotflow_trades_total` / `hotflow_win_rate` / `hotflow_expectancy` | Win-rate hooks from closed paper/backtest PnL |
| `hotflow_fees_total` / `hotflow_slippage_total` | From fetched or dated fixture schedules — never hardcoded venue rates |
| `hotflow_fill_ratio` | Simulator / backtest fill fraction |
| `hotflow_hot_markets` / `hotflow_opportunity_score` / `hotflow_hms` | Latest cycle |
| `hotflow_exposure{category=}` | Risk-state notional |
| `hotflow_signal_latency_seconds` / `hotflow_order_latency_seconds` | `histogram_quantile` → p50/p90/p99 |
| `hotflow_ws_health` / `hotflow_rtds_health` / `hotflow_sports_health` | 1=fresh, 0=stale |
| `hotflow_api_errors_total` | Scanner / local HTTP errors |
| `hotflow_kill_switch` / `hotflow_ready` / `hotflow_alerts_total` | Risk + alert hooks |

Health JSON: `GET /health` and `GET /ready` on the same process. Ready is 503
if the kill switch is tripped or mode is LIVE.

Grafana: add this Prometheus datasource and build panels from the table
above. Do not commit secrets into dashboard JSON.