# Dashboards

## Built-in paper UI (no Grafana required)

Same process as the paper bot. Localhost only. PAPER ledger numbers — never
venue balances, never LIVE transmit, no secrets on the page.

```bash
# Default: mock fixtures, UI on 127.0.0.1:9109, keep the server after the cycle
hotflow dashboard --mock

# Watch a longer soak on the same page (SSE + poll fallback)
hotflow paper-run --mock --cycles 8 --dashboard
hotflow paper-soak --cycles 5 --dashboard

# Serve the page only (idle gauges until a session publishes)
hotflow dashboard --idle
```

Open **http://127.0.0.1:9109/** in a browser.

The same server keeps Prometheus scrape and probes:

| Path | Role |
| --- | --- |
| `/` | Single-page paper watch UI |
| `/api/state` | JSON snapshot (short-poll) |
| `/events` | Server-sent events (primary live updates) |
| `/metrics` | Prometheus text |
| `/health` `/ready` | JSON probes |

`hotflow paper-run --mock --serve-metrics` still binds **:9108** and now also
serves `/` on that port. `--dashboard` prefers **:9109** so Grafana scrape and
the watch UI can coexist if you run both styles.

**SSE vs poll:** the page opens `EventSource("/events")` and falls back to
1.5s `GET /api/state` if SSE drops. SSE is cheaper on the wire; poll is the
compatible path through picky proxies. Stdlib `http.server` only — no extra
deps.

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
| `hotflow_equity` / `hotflow_*_pnl` / `hotflow_drawdown` | Paper session ledger (not venue balances) |
| `hotflow_trades_total` / `hotflow_win_rate` / `hotflow_expectancy` | Closed-trade stats from paper ledger / backtest PnL |
| `hotflow_shadow_decisions_total` | Shadow would_buy / would_sell / skip — never order submits |
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
above. Optional — the built-in `/` UI is enough to watch a local paper run.
Do not commit secrets into dashboard JSON.
