# Runbook

## Paper (supported)

```bash
pip install -e ".[dev]"
hotflow paper-run --mock    # TWAP + Chicago + Gamma weather texts + NBA, PAPER only
hotflow weather-fixtures    # public Gamma weather-tag text → tests/fixtures/weather/
hotflow news-fixtures       # labeled news → classify/validate/impact (no orders)
hotflow esports-fixtures    # public Gamma esports-tag text → tests/fixtures/esports/
hotflow rtds-cache --mock   # write official-shape cache (no socket)
hotflow paper-run --twap-cache data/rtds_twap_cache.json --mock
hotflow sports-cache --mock # write official-shape Sports WS cache (no socket)
hotflow paper-run --sports-cache data/sports_ws_cache.json --mock
hotflow scan
hotflow backtest --fixture tests/fixtures/backtest/crypto_book_trade.json
hotflow backtest --fixture tests/fixtures/backtest/crypto_longer_synthetic.json
hotflow record-stream --mock
hotflow tune --report reports/backtest-*.json --write-suggestion reports/tune-suggestion.yaml
hotflow shadow --mock
hotflow shadow-soak --cycles 5
hotflow failure-soak
hotflow live-gates
hotflow readiness
hotflow news-fixtures
hotflow paper-run --mock --news-fixtures
hotflow shadow --mock --news-fixtures
hotflow paper-soak --long --target-closes 50
hotflow paper-soak --mixed --cycles 5
hotflow performance --report reports/paper-soak-long-*.json
hotflow decay --report reports/paper-soak-long-*.json
hotflow walk-forward --report reports/paper-soak-long-*.json
pytest -q tests/test_twap.py tests/test_rtds_cache.py tests/test_weather_sports.py tests/test_weather_gamma_fixtures.py tests/test_esports.py tests/test_sports_cache.py tests/test_backtest.py tests/test_recorder.py tests/test_tuner.py tests/test_observability.py tests/test_paper_ledger.py tests/test_paper_gates.py tests/test_shadow_gates.py tests/test_failure_injection.py tests/test_live_gates.py tests/test_security_hygiene.py tests/test_readiness.py tests/test_news_engine.py tests/test_performance.py tests/test_paper_long_soak.py tests/test_mixed_paper_soak.py tests/test_mixed_walkforward.py tests/test_walkforward.py
pytest -q
```

Weather fixtures are **public Gamma market text** (`GET /events?tag_slug=weather`
plus `GET /markets/{id}`). They do not include forecasts. `paper-run --mock`
attaches labeled `source=fixture` forecasts for scoring demos only — not live
NWS. Unparseable rules (e.g. hottest-year rank markets) skip
`WEATHER_RULES_UNKNOWN`.

`weather.enabled` / `sports.enabled` default on for paper scoring. They never
open paid weather APIs. `feeds.sports_ws.subscriber_enabled` and
`--sports-live` stay off unless you want a brief unauthenticated Sports WS
collect (`hotflow sports-cache --live --seconds 12`). They never enable LIVE
CLOB orders. Live Sports frames are informational and may be delayed or wrong. Unparseable rules or
missing/stale forecast/game state skip (`WEATHER_*` / `SPORTS_*` /
`UNSUPPORTED_SPORT`).

`feeds.rtds.subscriber_enabled` and `--rtds-live` stay off unless you want a
brief unauthenticated RTDS collect. They never enable LIVE CLOB orders.

## Backtest

```bash
hotflow backtest --fixture tests/fixtures/backtest/crypto_book_trade.json
```

Replays a time-ordered recorded stream (books, trades, optional TWAP/sports/
weather fixture states). Decisions use only events at or before `ts`.
Candle-only streams are refused. Fees must be a **dated** official-shape
schedule. Reports include expectancy, drawdown, fees, slippage, trade count,
reason-code skips, train/validation/OOS, and a walk-forward window stub.
Absolute PnL is recorded but is **not** a selection metric.

## Record official-shape streams

```bash
hotflow record-stream --mock
# optional public collect (PAPER data only, capped duration, default off)
hotflow record-stream --live --seconds 20 --out reports/record-stream.json
hotflow record-stream --live --seconds 12 --rtds --symbol btc/usd
# or: python scripts/record_official_stream.py
```

`--mock` writes the labeled synthetic longer fixture. `--live` polls official
`GET /book` (and optional RTDS 30s/60s). Token ids are redacted. If live
collect fails, keep using the synthetic fixture.

## Offline tuner

```bash
hotflow backtest --fixture tests/fixtures/backtest/crypto_longer_synthetic.json \
  --out reports/backtest-longer.json
hotflow tune --report reports/backtest-longer.json --objective expectancy \
  --hypothesis "bounded edge vs drawdown" \
  --write-suggestion reports/tune-suggestion.yaml
```

Suggestions are **not** applied. `--write-suggestion` must be under `reports/`.
`--objective pnl` / `abs_pnl` is refused. `tuner.auto_apply` stays false.

## Shadow

```bash
hotflow shadow --mock
hotflow shadow --mock --cycles 5 --stale-probe --compare-paper
hotflow shadow-soak --cycles 5 --serve-metrics
# or: python scripts/shadow_soak.py --cycles 5
```

Or set `trading.mode: shadow` / `trading.shadow: true`. Decisions and
`would_buy` / `would_sell` / `expected_price` / `actual_price_after_signal` /
`simulated_fill` rows are written for **accepted and rejected** paths;
`simulated_fill.sent` stays false. **No orders.** `actual_price_after_signal`
is a later-cycle observed mid or null — never invented.

`--stale-probe` ages a fixture book past `MAX_DATA_AGE` and expects a STALE /
kill skip with `would_buy=false` / `would_sell=false`. `--compare-paper` runs
the same fixtures through a separate paper pipeline and records agreement
between paper fills and shadow `would_*`. That is **not** a live-edge claim.

## Parte 59 shadow gates

Ready for SHADOW when:

- paper is stable (`hotflow paper-soak`)
- signal logging is complete (every row has reason + would_* + prices + unsent fill)
- simulated fills are unsent and share-sized from the decision, not a venue print
- data loss is detected (stale / reconnect / `MAX_DATA_AGE` blocks new `would_*`)
- performance is reproducible from the same fixtures (report under `reports/`)

LIVE stays gated.

## Failure injection (Phase 14 / Parte 39)

Mocked only — no live sockets, no LIVE orders, no invented prints.

```bash
hotflow failure-soak --out reports/failure-soak.json
# or: python scripts/failure_soak.py
```

Cases: WS disconnect/reconnect (market/user/RTDS stubs), HTTP 500/429/timeout on
Gamma/CLOB, corrupt/duplicate/out-of-order events, stale / `MAX_DATA_AGE`,
missing fees / missing TWAP / data-gap, paper partial-fill vs cancel race,
ledger vs caller-supplied position mismatch, clock skew / negative latency.

Each case must **fail safe**: skip or kill-switch, `would_*=false`, zero new
order submits. The report lists `live_prep_still_blocked` (signing, LIVE gates,
venue reconcile, real-socket inject).

## LIVE (frozen closed)

```bash
hotflow live-gates                 # exit 0 only when every acceptance gate is CLOSED
```

Do **not** enable LIVE in this pass. Signing / CLOB transmit is not implemented.
`LiveExecutor.place_order` / `cancel_order` / `get_positions` / `get_orders`
raise in PAPER and still refuse if flags are forced open.

### Parte 59 LIVE readiness

| Item | Status |
| --- | --- |
| Paper stable (accounting + kill drill) | Done (`hotflow paper-soak`) |
| Shadow consistent (complete would_*, stale skip) | Done (`hotflow shadow-soak`) |
| Failure injection (mocked) | Done (`hotflow failure-soak`) |
| Risk / kill switch | Done (paper + failure soak) |
| Secrets isolated | This pass (`hotflow live-gates`, `.env.example` placeholders, redaction) |
| Accounting reconciled vs **venue** | Blocked (paper ledger only) |
| Wallet / EIP-712 / HMAC signing | Blocked (not implemented) |
| `accept_*` + `HOTFLOW_ACCEPT_LIVE` | **Must stay false / 0** |
| Zero critical bugs + billing-unlocked CI | Blocked |

## News fixtures (PAPER)

```bash
hotflow news-fixtures
hotflow news-fixtures --shadow
# or: python scripts/news_fixtures.py
hotflow paper-run --mock --news-fixtures
hotflow shadow --mock --news-fixtures
```

News is classify → validate → impact features → existing FV/risk.
It never places an order. `--fetch-public` stays off and does not scrape.

## Performance / alpha decay (PAPER)

```bash
hotflow paper-soak --long --target-closes 50   # labeled synthetic official-shape lots
hotflow paper-soak --mixed --cycles 5         # allocator/regime audit (not the n≥50 sample)
hotflow walk-forward --report reports/paper-soak-mixed-*.json
hotflow decay --report reports/paper-soak-mixed-*.json
hotflow performance --report reports/paper-soak-long-*.json
hotflow decay --report reports/paper-soak-long-*.json
hotflow walk-forward --report reports/paper-soak-long-*.json
# or: python scripts/walk_forward.py --report ...
```

`--long` records ≥50 **explicit** FILL / MARK / FLATTEN closes (MAE/MFE/holding
populate). Origin is `synthetic_official_shape` — prices are fixture arguments,
not live venue prints. Kill-switch still stops the soak if it trips. Decay
never auto-disables. If you only have a short soak, performance will say
`empty_sample` / `too_small_for_inference` instead of inventing trades.

Reviews **existing** paper-ledger / backtest JSON only (Gross/Net, fees,
slippage when present, win rate, profit factor, drawdown, MAE/MFE/holding
when events include them). Tiny samples are labeled; no strong conclusions.
`--rank-by abs_pnl` is refused (`MAX_ABS_PNL_SELECTION_REFUSED`).

Decay compares recent 50 / 100 / 500 (clipped to whatever exists) vs an
earlier baseline with stderr + a lite bootstrap CI. Flags are
**suggestion-only** — they never auto-disable a strategy or change
`hotflow readiness` `ok`.

Signal half-life buckets come from report metadata (`signal_half_life_ms`);
otherwise `N/A`. Kimi `PERFORMANCE_ANALYST` is cold-path only.

### Walk-forward / regime split (anti-overfitting)

```bash
hotflow paper-soak --long --target-closes 50
hotflow walk-forward --report reports/paper-soak-long-*.json
# expanding train 20 → holdout 10, step 10 (default). --rolling for a sliding train.

# Mixed soak: detected detector labels (not --long synthetic notes)
hotflow paper-soak --mixed --cycles 5 --out reports/paper-soak-mixed.json
hotflow walk-forward --report reports/paper-soak-mixed.json
hotflow decay --report reports/paper-soak-mixed.json
hotflow performance --report reports/paper-soak-mixed.json
```

Uses **only** the closed trades already in the report. Each fold reports
expectancy, win rate, drawdown, fees, and trade count for train and holdout.
Holdouts of 10 are caveated (`small_sample_no_strong_conclusion`).
`--rank-by abs_pnl` is refused. `auto_disable=false`; `live_ready` is untouched.

Long-soak lots carry a **labeled synthetic** regime (`normal` first half,
`high_volatility` second half) — not a live-vol classifier. Reports without
regime notes get `regime_split.status=N/A`.

`paper-soak --mixed` JSON is a different unit: walk-forward/decay group by
**detected** `extras.regime` on evaluate proposals (`news_shock`,
`near_resolution`, …). Close PnL is joined by market_id + flatten recipe when
present. Default 20/10 folds are **not invented** when n_closes is ~8–15
(`fold_note`). Per-label decay windows 50/100/500 stay `insufficient_sample`.
This is PAPER fixture analysis, not live edge.

## Readiness rollup

```bash
hotflow readiness                          # lightweight paper/shadow + failure-soak + live-gates
hotflow readiness --from-reports reports   # parse latest real JSON only; no invented results
# or: python scripts/readiness.py
```

The report under `reports/readiness-*.json` lists PASSED / FAILED / SKIPPED per
check, `paper_ready` / `shadow_ready` / `failure_ready`, and **`live_ready=false`**.
Exit 0 only when paper + shadow + failure-soak + frozen live-gates all pass.
`--from-reports` skips (does not invent) missing files and then fails closed.

When (later) those are truly ready, LIVE still needs **all** of:

- `trading.mode: live`
- `live.accept_*` flags true
- `HOTFLOW_ACCEPT_LIVE=1`

## Cold-path skills (do not mutate production)

```bash
python scripts/hotflow_daily_review.py
python scripts/hotflow_experiment.py
python scripts/hotflow_incident.py
```

## Paper soak and accounting (Phase 12 / Parte 59)

Paper equity is the **session ledger**, not a venue balance. Cash, positions,
realized/unrealized PnL, fees, peak equity, and drawdown replay from explicit
`FILL` / `MARK` / `FLATTEN` events. Flatten prices must be last observed mids
or fill prices — missing marks are refused.

```bash
# Shared ledger across cycles; optional flatten + kill-switch drill
hotflow paper-run --mock --cycles 5 --flatten --out reports/paper-soak.json
hotflow paper-soak --cycles 5 --serve-metrics
# or: python scripts/paper_soak.py --cycles 5

# Longer labeled soak for performance/decay (n≥50 closes, MARK between open/close)
hotflow paper-soak --long --target-closes 50
# writes reports/paper-soak-long-*.json (session + ledger events)

# Mixed fixture soak: allocator + regime overlays (5m AND 15m + news). PAPER only.
hotflow paper-soak --mixed --cycles 5
# writes reports/paper-soak-mixed-*.json with totals.reasons / overlay_applied
```

`--flatten` closes open paper qty at collected marks. `--kill-drill` opens and
closes a labeled paper lot that breaches `risk.max_daily_loss`, verifies the
next order is `KILL_SWITCH`, and clears only with `--acknowledge "..."` (blank
ack is rejected). SQLite tables `ledger_events` / `ledger_snapshots` persist
the same numbers the Prometheus gauges read.

Session reports include `accounting` and the event list so a soak can be
replayed with `replay_events(...)`.

## Metrics and alerts (Parte 35–36)

Optional localhost scrape. Default bind is `127.0.0.1` (not a Polymarket
endpoint). `trading.mode` stays **paper**. The HTTP server is **off** unless
`--serve-metrics`, `monitoring.http_enabled: true`, or `HOTFLOW_METRICS=1`.

```bash
hotflow serve-metrics                  # /metrics /health /ready on :9108
hotflow paper-run --mock --serve-metrics
curl -sS http://127.0.0.1:9108/health
curl -sS http://127.0.0.1:9108/ready
curl -sS http://127.0.0.1:9108/metrics | head
```

Prometheus can scrape `http://127.0.0.1:9108/metrics`. Histogram series
`hotflow_signal_latency_seconds` and `hotflow_order_latency_seconds` support
`histogram_quantile(0.5|0.9|0.99, …)` for p50/p90/p99. Equity / PnL /
drawdown / win-rate gauges are published from the **paper session ledger**
(replayable `FILL` / `MARK` / `FLATTEN` events). They are not venue balances.

Alert hooks emit a redacted JSON `alert` event and an optional callback
(`Observability.add_alert_callback`). Kinds: kill switch, drawdown, stale WS,
high latency, auth failure, position mismatch, process restart, unexpected
exposure, API disconnected, high slippage, strategy disabled. Callbacks must
not block the decide path. **Never put API keys, private keys, or wallet
material in alerts.**

`/ready` is 503 when the kill switch is tripped or `trading.mode` is `live`.
`/health` stays 200 while the process is up.

Grafana: see `dashboards/README.md` (scrape notes only; no shipped dashboard).

## Kill switch recovery

Inspect logs and SQLite `risk_decisions`. Call
`KillSwitchBoard.reset(acknowledge="operator confirmed recover")` only after
the cause is understood. There is no silent auto-reset.
