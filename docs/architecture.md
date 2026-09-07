# HOTFLOW architecture

Source of truth: [`MISSION-FULL.md`](MISSION-FULL.md). Alignment map:
[`MISSION-ALIGNMENT.md`](MISSION-ALIGNMENT.md).

Paper-first autonomous multi-market system for Polymarket. Default mode is
**PAPER**. Modes: `backtest` / `paper` / `shadow` / `live`. LIVE transmit is
unreachable unless every acceptance gate passes.

```
                    ┌─────────────────────────┐
                    │  Kimi K3 (cold path)    │
                    │  research / critique /  │
                    │  post-trade analysis    │
                    └────────────┬────────────┘
                                 │ offline only
                                 ▼
┌──────────┐   ┌──────────┐   ┌──────────┐   ┌──────────┐   ┌────────────┐   ┌────────────┐
│ Gamma +  │──▶│ Features │──▶│ Quant    │──▶│ Portfolio│──▶│ Risk VETO  │──▶│ Execution  │
│ public   │   │ HMS      │   │ Fair     │   │ allocate │   │ kill       │   │ paper /    │
│ CLOB     │   │ Opp score│   │ value    │   │ (propose)│   │ switches   │   │ gated LIVE │
└──────────┘   └──────────┘   └──────────┘   └──────────┘   └────────────┘   └─────┬──────┘
     ▲                │              │               │               │
     │                └──────────────┴───────────────┴───────┐       │
     │                                                       ▼       ▼
     │                                              SQLite/Parquet +
     │                                              paper ledger + JSON / Prometheus
     └──────────── marketdata freshness / WS heartbeats ─────────────┘
```

## Hot path vs cold path

| Path | Allowed | Forbidden |
| --- | --- | --- |
| **Hot** (scan → score → fair value → risk → paper/live order) | Deterministic Python, official HTTP/WS, config, risk engine | Any LLM call, Kimi client, prompt I/O |
| **Cold** | Kimi roles, experiment notes, offline tuner stubs, human review | Secrets, private keys, raw `.env`, order-signing material |

`hotflow.execution` and `hotflow.risk` do not import `hotflow.ai_research`.
News classification via Kimi is cold-path only (`hotflow.news.cold`); the
evaluate hot path consumes structured `NewsImpact` features already computed.

## Pipeline

1. **Discovery** — Gamma `GET /markets` plus public CLOB book / tick / fee /
   `clob-markets/{condition_id}`. Dynamic eligibility: `acceptingOrders`,
   `enableOrderBook`, liquidity, volume, bid/ask/spread, fee flags, resolution
   metadata. Not a category whitelist.
2. **Hot Market Score (HMS)** — 0–100 from liquidity, volume, spread, book
   openness, competitive, persistence, urgency (time-to-resolution). Tiers
   (Parte 9): COLD 0–30, WARM 30–55, HOT 55–75, ULTRA-HOT 75–100. Resource plan:
   metadata / low-frequency / full book / highest frequency.
3. **Opportunity** — only if HMS ≥ configured threshold:
   `expected_net_edge × confidence × liquidity × persistence × execution_probability`
   with YAML weights.
4. **News / event overlay (optional, PAPER)** — labeled `NewsItem` only:
   classify → source validation → impact features (`p_info` / confidence).
   News never becomes an order. Skip codes: `NEWS_UNVALIDATED`,
   `NEWS_DUPLICATE`, `NEWS_ALREADY_REPRICED`, `NEWS_LOW_CONFIDENCE`,
   `NEWS_IRRELEVANT_RESOLUTION`.
5. **Fair value** — `FairValueProvider` → `P(outcome|info)`, `RAW_EDGE`,
   `NET_EXPECTED_EDGE` after **fetched** fees + spread + slippage + latency +
   adverse-selection haircut. Skip when `NET <= MIN_REQUIRED_EDGE`. News-adjusted
   `p_info` still goes through this gate.
6. **Portfolio (Parte 24)** — when several names are hot in one scan, rank by
   opportunity / risk-adjusted PnL velocity and propose TAKE / DOWNSIZE / SKIP
   under explicit correlation groups and concentration caps. Never invents a
   residual correlation. Does not place orders. `paper-soak --mixed` is the
   fixture audit of that batch (5m/15m crypto + news + uncorrelated names).
7. **Risk** — absolute **VETO**. Limits on order / market / category / total
   exposure, daily/session loss, drawdown, open orders, concurrent markets,
   slippage, spread, data age, latency, cooldown. **NO TRADE is valid.** No
   martingale; size does not increase after losses. Portfolio proposals still
   pass through this gate.
8. **Kill switches** — stale WS, auth fail, position mismatch, runaway rejects,
   manual, data-feed dead. On trip: block new orders, cancel when safe,
   preserve logs, require explicit `reset_kill_switch()`.
9. **Execution** — internal SM:
   `CREATED → SUBMITTED → ACKNOWLEDGED → PARTIAL → FILLED`
   plus `CANCEL_*` / `REJECTED` / `EXPIRED`. Paper simulator supports partial
   fills and client-order-id idempotency. Fills come from the simulator (or
   future venue acks), **never** from a missing book level.
10. **Storage** — SQLite now (schema ready for Postgres/Timescale). Parquet
   export for features. Persist trades, orders, feature snapshots, signals,
   risk decisions.
11. **Audit** — every opportunity, including rejects, as JSON with reason codes
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
`hotflow live-gates` prints each gate and exits 1 if any is unexpectedly open.
Signing is not implemented in this pass.

## Data freshness

Each feed has `max_data_age_ms` in config. Stale **critical** data (books,
fees, tick/min size) → block new orders and cancel working paper/live orders
when safe (`STALE_DATA` / `KILL_SWITCH_STALE_WS`).

## Configuration

All tunables live in `configs/*.yaml` (`trading`, `scanner`, `hot_market`,
`opportunity`, `fair_value`, `risk`, `portfolio`, `regimes`, `microstructure`,
`categories`, `feeds`,
`weather`, `sports`, `esports`, `news`, `backtest`, `ai_research`).
No scattered magic numbers in strategy code.

Also: resolution parser (unknown rules ⇒ DO_NOT_TRADE), basic filter,
microstructure (mid/microprice/imbalance **plus** weighted imbalance, slope,
convexity, gaps, VWAP-to-depth, spread regime — see `docs/strategy.md`),
capped Kelly sizing, maker/taker EV,
PnL velocity, first-class regime detectors (Parte 25; N/A if features missing),
Parte 46 signal-quality JSON on **every** PAPER decision (TRADE and SKIP;
nulls when unknown), Parte 47 skip audit (`IMPACT_EXHAUSTED` is audit-only;
`max_impact` / `min_top_depth` default-off), Parte 52–53
performance/decay reviews from existing ledger/backtest JSON (suggestion-only).
Mixed soak JSON adds a detected-label split (proposals first; joined close PnL
second). `--long` remains the ≥50-close synthetic-label path.

## Weather / sports paper adapters

- Resolution parser extensions: weather city/station/metric/unit/window/
  timezone/rounding/threshold/comparison/source; sports league/teams plus official
  Sports WS `live`/`ended`/`score`/`period` when present. Timezone is stored
  only when IANA/UTC appears — never invented.
- Weather FV consumes a labeled forecast distribution vs implied. Forecasts
  are never the official resolver. No invented weather API. Real market text
  comes from public Gamma (`hotflow weather-fixtures`); pytest uses those
  fixtures plus `source=fixture` forecasts.
- Sports: official WS URL + server-`ping`/client-`pong`. Mock frames in
  pytest. Optional short public collect (`PublicSportsSubscriber`) is
  default-off. `SportsGameCache` keys official-shape updates by `gameId`.
  Fresh cache → score; missing/stale → skip. `NBABasketballModel` ≠
  `SoccerModel`. Unsupported sports refuse.
- Esports: parse Gamma match text (game/teams/BO/source). Per-title stubs
  (`cs2`/`lol`/`dota2`/`val`) refuse other titles. No invented live feed.
  Toggle: `esports.enabled` (live client off).
- Wired into discovery → HMS → fair value → risk → paper. Crypto TWAP path
  unchanged. Toggles: `weather.enabled`, `sports.enabled` (live sports
  client off).
- Backtest: `hotflow backtest --fixture` replays time-ordered book/trade/state
  events through the same FV/risk path. No look-ahead. SHADOW soak logs
  complete `would_*` / prices / unsent `simulated_fill` and never transmits.
- Recorder: `hotflow record-stream --mock` (default) or optional `--live`
  public CLOB book poll + optional RTDS. Tuner: suggestion JSON/YAML only.

## Scaffolded (interfaces tested; adapters incomplete)

- Market / user / RTDS reconnect + heartbeat  
- TWAP-aware crypto paper FV + public RTDS print cache (official 30s/60s only)  
- Esports skip-heavy parser + Gamma fixtures (no invented live model)  
- Prometheus metrics + redacted JSON logs + `/metrics` `/health` `/ready`
  (localhost, default-off) + alert callbacks (kill, drawdown, stale WS, …)
- Failure injection soak (`hotflow failure-soak`) — mocked WS/HTTP/event faults;
  fail-safe skip/kill, no invented prints, LIVE still gated  
- Offline tuner suggestions (`hotflow tune`; never auto-applies)  
- Strategy experiment tracking fields
