# HOTFLOW architecture

Paper-first autonomous multi-market system for Polymarket. Default mode is
**PAPER**. LIVE transmit is unreachable unless every acceptance gate passes.

```
                    ┌─────────────────────────┐
                    │  Kimi K3 (cold path)    │
                    │  research / critique /  │
                    │  post-trade analysis    │
                    └────────────┬────────────┘
                                 │ offline only
                                 ▼
┌──────────┐   ┌──────────┐   ┌──────────┐   ┌────────────┐   ┌────────────┐
│ Gamma +  │──▶│ Features │──▶│ Quant    │──▶│ Risk VETO  │──▶│ Execution  │
│ public   │   │ HMS      │   │ Fair     │   │ kill       │   │ paper /    │
│ CLOB     │   │ Opp score│   │ value    │   │ switches   │   │ gated LIVE │
└──────────┘   └──────────┘   └──────────┘   └────────────┘   └─────┬──────┘
     ▲                │              │               │               │
     │                └──────────────┴───────────────┴───────┐       │
     │                                                       ▼       ▼
     │                                              SQLite/Parquet +
     │                                              signal audit JSON
     └──────────── marketdata freshness / WS heartbeats ─────────────┘
```

## Hot path vs cold path

| Path | Allowed | Forbidden |
| --- | --- | --- |
| **Hot** (scan → score → fair value → risk → paper/live order) | Deterministic Python, official HTTP/WS, config, risk engine | Any LLM call, Kimi client, prompt I/O |
| **Cold** | Kimi roles, experiment notes, offline tuner stubs, human review | Secrets, private keys, raw `.env`, order-signing material |

`hotflow.execution` and `hotflow.risk` do not import `hotflow.ai_research`.

## Pipeline

1. **Discovery** — Gamma `GET /markets` plus public CLOB book / tick / fee /
   `clob-markets/{condition_id}`. Dynamic eligibility: `acceptingOrders`,
   `enableOrderBook`, liquidity, volume, bid/ask/spread, fee flags, resolution
   metadata. Not a category whitelist.
2. **Hot Market Score (HMS)** — 0–100 from liquidity, volume, spread, book
   openness, competitive, persistence. Tiers: COLD / WARM / HOT / ULTRA-HOT
   (thresholds in `configs/default.yaml`).
3. **Opportunity** — only if HMS ≥ configured threshold:
   `expected_net_edge × confidence × liquidity × persistence × execution_probability`
   with YAML weights.
4. **Fair value** — `FairValueProvider` → `P(outcome|info)`, `RAW_EDGE`,
   `NET_EXPECTED_EDGE` after **fetched** fees + spread + slippage + latency +
   adverse-selection haircut. Skip when `NET <= MIN_REQUIRED_EDGE`.
5. **Risk** — absolute **VETO**. Limits on order / market / category / total
   exposure, daily/session loss, drawdown, open orders, concurrent markets,
   slippage, spread, data age, latency, cooldown. **NO TRADE is valid.** No
   martingale; size does not increase after losses.
6. **Kill switches** — stale WS, auth fail, position mismatch, runaway rejects,
   manual, data-feed dead. On trip: block new orders, cancel when safe,
   preserve logs, require explicit `reset_kill_switch()`.
7. **Execution** — internal SM:
   `CREATED → SUBMITTED → ACKNOWLEDGED → PARTIAL → FILLED`
   plus `CANCEL_*` / `REJECTED` / `EXPIRED`. Paper simulator supports partial
   fills and client-order-id idempotency. Fills come from the simulator (or
   future venue acks), **never** from a missing book level.
8. **Storage** — SQLite now (schema ready for Postgres/Timescale). Parquet
   export for features. Persist trades, orders, feature snapshots, signals,
   risk decisions.
9. **Audit** — every opportunity, including rejects, as JSON with reason codes
   (`EDGE_TOO_SMALL`, `STALE_DATA`, `RISK_LIMIT`, `MARKET_NOT_HOT`,
   `UNKNOWN_RESOLUTION`, `UNKNOWN_FEES`, …).

## LIVE acceptance gates

LIVE is blocked unless **all** of the following are true:

1. `trading.mode: live` in YAML  
2. `live.accept_live_trading: true`  
3. `live.accept_capital_at_risk: true`  
4. `live.i_understand_orders_are_real: true`  
5. Environment `HOTFLOW_ACCEPT_LIVE=1`  
6. Risk engine not killed  
7. Credentials present (never logged)

Any missing gate keeps the process in paper or refuses to start transmit.

## Data freshness

Each feed has `max_data_age_ms` in config. Stale **critical** data (books,
fees, tick/min size) → block new orders and cancel working paper/live orders
when safe (`STALE_DATA` / `KILL_SWITCH_STALE_WS`).

## Configuration

All tunables live in `configs/*.yaml` (`trading`, `scanner`, `hot_market`,
`opportunity`, `fair_value`, `risk`, `categories`, `feeds`, `ai_research`).
No scattered magic numbers in strategy code.

## Scaffolded (interfaces tested; adapters incomplete)

- Market / user / RTDS / sports WS reconnect + heartbeat  
- TWAP-aware crypto hooks (official 30s/60s topics only)  
- Weather / sports / esports strategy adapters  
- Event-driven backtester protocol  
- `trading.shadow: true` (score + audit, no orders)  
- Prometheus metrics + JSON logs  
- Offline auto-tuner stub  
- Strategy experiment tracking fields
