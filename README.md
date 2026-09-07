# POLYMARKET HOTFLOW

Paper-first autonomous multi-market quantitative system for [Polymarket](https://docs.polymarket.com).

**Default mode is PAPER.** The process never transmits live orders unless every LIVE acceptance gate is explicitly set. **NO TRADE is a valid outcome.** There is no martingale and no automatic risk-up after losses.

Kimi K3 is **cold-path research only**. The decide/transmit path is deterministic Python.

**Source of truth:** [`docs/MISSION-FULL.md`](docs/MISSION-FULL.md) (64-part mission).
Alignment map: [`docs/MISSION-ALIGNMENT.md`](docs/MISSION-ALIGNMENT.md).

Official endpoints and fee/tick/min-size fields: [`docs/research-current.md`](docs/research-current.md).
Architecture: [`docs/architecture.md`](docs/architecture.md). Also
[`docs/strategy.md`](docs/strategy.md), [`docs/risk.md`](docs/risk.md),
[`docs/security.md`](docs/security.md), [`docs/runbook.md`](docs/runbook.md),
[`docs/deployment.md`](docs/deployment.md).

## Safety rules

1. `trading.mode: paper` in `configs/default.yaml`
2. LIVE requires **all** of: `trading.mode: live`, three YAML accept flags, and `HOTFLOW_ACCEPT_LIVE=1`
3. Fees, tick size, and min order size are **fetched** from current Gamma/CLOB APIs — never hardcoded
4. Risk engine has absolute **VETO** and kill switches (block new orders, cancel when safe, keep logs, explicit recovery)
5. No secrets in git, logs, prompts, or reports — ship `.env.example` only

## Quick start (paper)

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"

# Documented fixture path (no network required). Exercises official-shape
# RTDS 30s/60s TWAP, Chicago + real Gamma weather texts, and NBA sports
# fixtures on PAPER only. Weather forecasts in --mock are labeled fixtures.
hotflow paper-run --mock

# Refresh public Gamma weather-tag resolution text (no forecasts, no orders)
hotflow weather-fixtures
# or: python scripts/fetch_weather_gamma_fixtures.py --out tests/fixtures/weather

# Public Gamma esports-tag text (no live odds; paper path is skip-heavy)
hotflow esports-fixtures

# Public Gamma + CLOB scan (read-only)
hotflow scan
hotflow paper-run --cycles 1

# Event-driven BACKTEST on a recorded fixture (offline, no LIVE orders)
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
hotflow paper-run --mock --cycles 3 --flatten
hotflow paper-soak --cycles 5

# Optional localhost observability (PAPER only; off by default)
hotflow serve-metrics
hotflow paper-run --mock --serve-metrics
# scrape http://127.0.0.1:9108/metrics  /health  /ready
```

Reports land in `reports/`. SQLite state lands in `data/hotflow.sqlite`.

Docker (paper only):

```bash
docker compose up --build
```

## Configuration

All tunables live in [`configs/default.yaml`](configs/default.yaml): scanner filters, HMS weights/tiers, opportunity weights, fair-value haircuts, risk limits, per-feed `max_data_age_ms`, category toggles.

Copy [`.env.example`](.env.example) to `.env` locally. Leave `HOTFLOW_ACCEPT_LIVE=0`.

## What runs on the hot path

1. **Universe scanner** — Gamma `GET /markets` + public CLOB book / fee-rate / `clob-markets/{condition_id}`
2. **HMS 0–100** — COLD / WARM / HOT / ULTRA-HOT
3. **Opportunity score** after HMS threshold
4. **Fair value** — `P(outcome|info)`, RAW_EDGE, NET after fetched fees + spread + slippage + latency + adverse selection. Crypto TWAP markets use the official Chainlink 30s/60s observation when the window/symbol/strike can be parsed; otherwise they skip. Weather/sports parse resolution rules first; low confidence → `DO_NOT_TRADE`. Forecasts are features only. Sports models are per-sport (NBA ≠ Soccer); unsupported sports refuse.
5. **Risk VETO**
6. **Paper order state machine** with partial fills and idempotency

Fills are never inferred from a disappearing book level.

## LIVE (do not enable casually)

LIVE is a no-op unless:

| Gate | Required value |
| --- | --- |
| `trading.mode` | `live` |
| `live.accept_live_trading` | `true` |
| `live.accept_capital_at_risk` | `true` |
| `live.i_understand_orders_are_real` | `true` |
| `HOTFLOW_ACCEPT_LIVE` | `1` |

Missing any gate keeps transmit closed. Paper remains the supported path.
`hotflow live-gates` prints each gate and exits 1 if any is unexpectedly open.
Signing is **not implemented**; `place_order` / `cancel_order` refuse.

## Tests and CI

```bash
pytest -q
ruff check src tests scripts
mypy src/hotflow
```

GitHub Actions runs lint, typecheck, pytest, and a mock paper-run smoke.

## Package layout

`src/hotflow/{discovery,marketdata,hotmarket,features,fairvalue,news,strategies,risk,execution,portfolio,storage,analytics,ai_research,monitoring}`

News (Parte 15) is fixture-only on the hot path: classify → validate →
impact features → existing FV/risk. It never becomes BUY/SELL.

Weather and sports PAPER adapters parse resolution rules before trading.
Forecasts never replace the official weather source. Sports uses official WS
field names and **distinct** NBA/Soccer models (Tennis/NFL refuse). Esports
parses official Gamma match text and skips unless an official-shape state
can be scored without inventing map/economy math. Official RTDS 30s/60s TWAP paper path is unchanged (fixtures
by default; optional unauthenticated live client off). WS reconnect/heartbeat,
event-driven backtester (`hotflow backtest --fixture`), shadow
`would_buy` / `would_sell` logs, Prometheus + JSON logs, and the offline
tuner stay in PAPER/BACKTEST/SHADOW (no LIVE). JSON logs redact secrets.
Prometheus + `/health` `/ready` are localhost-only and default-off.

## TWAP paper path

```bash
# Deterministic official-shape RTDS fixture (no live socket, no LIVE orders)
hotflow paper-run --mock
hotflow rtds-cache --mock --out data/rtds_twap_cache.json
hotflow paper-run --twap-cache data/rtds_twap_cache.json --mock
hotflow sports-cache --mock --out data/sports_ws_cache.json
hotflow paper-run --sports-cache data/sports_ws_cache.json --mock
pytest -q tests/test_twap.py tests/test_rtds_cache.py tests/test_weather_sports.py tests/test_sports_cache.py
```

Optional public RTDS / Sports WS collect (still PAPER — no orders):

```bash
hotflow rtds-cache --live --duration 12
hotflow paper-run --rtds-live
hotflow sports-cache --live --seconds 12
hotflow paper-run --sports-live
```

Window is **never** defaulted. It must appear as an official 30s or 60s lookback
in the market’s resolution text. See `docs/research-current.md`.
Subscriber and live socket stay **off** unless explicitly enabled.
