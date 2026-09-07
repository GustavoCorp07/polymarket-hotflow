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

# Documented fixture path (no network required)
hotflow paper-run --mock

# Public Gamma + CLOB scan (read-only)
hotflow scan
hotflow paper-run --cycles 1
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
4. **Fair value** — `P(outcome|info)`, RAW_EDGE, NET after fetched fees + spread + slippage + latency + adverse selection
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

## Tests and CI

```bash
pytest -q
ruff check src tests scripts
mypy src/hotflow
```

GitHub Actions runs lint, typecheck, pytest, and a mock paper-run smoke.

## Package layout

`src/hotflow/{discovery,marketdata,hotmarket,features,fairvalue,strategies,risk,execution,portfolio,storage,analytics,ai_research,monitoring}`

Category adapters (weather/sports/esports), WS reconnect/heartbeat, TWAP hooks (official 30s/60s only), backtester protocol, shadow mode, Prometheus + JSON logs, and the offline tuner are scaffolded with tested interfaces.
