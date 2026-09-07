# Strategy notes (aligned to `docs/MISSION-FULL.md`)

Source of truth: **Parte 7–17, 22–25, 45–47, 64**.

## Principle

HOT ≠ EDGE. HMS spends compute. Opportunity + fair value decide whether a trade
exists. **NO TRADE is valid.**

## Crypto (highest paper priority)

- Discover BTC/ETH/SOL Up/Down (5m / 15m / 4h) dynamically — no fixed whitelist.
- Fair value is `P(outcome|info)`, not momentum > threshold.
- TWAP-aware paper path accepts **only** official Chainlink/RTDS windows 30s
  and 60s parsed from market metadata (`docs/research-current.md`). Do not
  invent a TWAP, a window default, or a homemade remaining-average.
- Computed fields: `current_twap`, `projected_twap` (persistence of the
  official print), `distance_to_strike`, `time_remaining`,
  `required_future_price` (= parsed strike / required official TWAP at expiry),
  `probability_of_finish_above` / `below` (paper heuristic). These feed
  `P(outcome|info)` → RAW_EDGE → NET after fetched fees.
- Paper scan reads `TwapPrintCache` (injected JSON, `--mock` fixtures, or an
  optional public RTDS subscriber). Stale/missing official prints skip; they
  are never invented.
- Maker vs taker: compare `EV_maker` vs `EV_taker`; taker only if half-life is
  short and NET edge remains positive after fetched fees.

## Weather (PAPER)

Parse resolution rules **before** scoring. Required structured fields: city or
station, metric, unit, window, threshold, **official source**. Timezone and
rounding are recorded when the official text states them; they are never
invented (real Gamma city markets often omit an IANA zone). Low parse
confidence, missing source, or an unparseable structure (e.g. global rank /
hottest-year) → `WEATHER_RULES_UNKNOWN` / `DO_NOT_TRADE`. Never guess the
official observation source.

External forecasts (fixture ensembles in pytest / `paper-run --mock`) are
**features only**: `forecast mean/median/std`, labeled `p_above_threshold`,
or labeled `p_yes` (`WeatherForecast.source=fixture`). They are never
substituted for the official resolver. Fair value compares that forecast
to Polymarket implied via the same NET-edge path (fetched fees).
Missing forecast → `WEATHER_FORECAST_MISSING`. Toggle: `weather.enabled`.

## Sports (PAPER)

Use official Sports WS field names only (`wss://sports-api.polymarket.com/ws`,
server `ping` / client `pong`). Parse league/teams from Gamma; attach
`live` / `ended` / `score` / `period` when those official fields are present.

**Per-sport models.** NBA/CBB basketball (quarters) and Soccer (halves) are
distinct. Tennis, NFL, esports live models, etc. return `UNSUPPORTED_SPORT`
instead of reusing basketball/soccer math. Missing rules or game state →
`SPORTS_RULES_UNKNOWN` / `SPORTS_STATE_MISSING`.

Live public client is **default-off** (`sports.live_public_client: false`,
`feeds.sports_ws.subscriber_enabled: false`). pytest injects official-shape
frames. Paper scan can read `SportsGameCache` (injected JSON, `--mock`
fixtures, or an optional public Sports WS collect). Stale/missing official
frames skip (`SPORTS_STATE_STALE` / `SPORTS_STATE_MISSING`). Toggle:
`sports.enabled`.

## Esports

Skip-heavy PAPER path. Official Gamma has CS2/LoL/Dota2/Valorant match text
and `GET /sports` title ids. Sports WS documents Esports statuses and a CS2
example score string, but **not** map/economy math or a parseable series
grammar. Per-title adapters refuse other games. Missing rules →
`ESPORTS_RULES_UNKNOWN`. Missing official-shape state →
`ESPORTS_STATE_MISSING`. Unparseable live score → `UNSUPPORTED_STRUCTURE`.
Live Sports WS client stays off. Toggle: `esports.enabled`.

## News / event engine (Parte 15, PAPER)

News never goes to BUY/SELL. Flow:

```text
new information → classification → source validation → impact estimation
      → quant model (p_info / confidence) → risk engine
```

Hot path is deterministic. Items are **labeled fixtures or injected
`NewsItem`s**. The engine does not invent headlines, sources, or market moves.
Missing labeled `claimed_p_shift` / `claimed_p_after` → `NEWS_UNVALIDATED`.

Checks: source authority table, publication time, duplicate `event_key`,
relevance to exact resolution wording, recency confidence, already-repriced
(mid already at the labeled post-event probability).

Kimi `NEWS_CLASSIFIER` is a **cold-path stub** (`hotflow.news.cold`). It is
not imported by `evaluate_market`. Public news fetch is default-off and not
implemented (`news.public_fetch: false`).

`hotflow news-fixtures` writes a report. `paper-run --mock --news-fixtures`
and `shadow --mock --news-fixtures` attach the same fixtures; shadow still
logs `would_*` with `sent=false`.

## Backtest / shadow (Parte 26–28)

Event-driven replay only. Book/trade events are required when HMS uses book
features — candle-only fixtures are refused. Fill simulation applies documented
paper latency, queue penalty, maker fill probability, and taker delay. Fees
come from the dated fixture schedule via the official taker formula.
Train / validation / OOS splits plus `hotflow walk-forward` on existing
closed trades (expanding or rolling; fold-size caveats). Mixed soak JSON
(`paper-soak --mixed`) splits by **detected** detector labels on proposals,
not the `--long` synthetic `regime=` notes. A 5-cycle fixture is too small
for strong folds; the report says so instead of inventing significance.
Do not pick a strategy by max absolute walk-forward PnL.
Do not pick a strategy by max absolute backtest PnL.

`hotflow tune` may suggest bounded threshold/weight changes from expectancy,
drawdown, and skip codes. It never writes `configs/default.yaml` and never
uses abs PnL as an objective.

SHADOW scores the same path and records `would_buy` / `would_sell` /
`expected_price` / `actual_price_after_signal` / `simulated_fill` without
sending orders (`sent=false`). Stale / `MAX_DATA_AGE` skips have no `would_*`
intent. `hotflow shadow-soak` writes a multi-cycle report.

## Signal contract (Parte 46)

Every decision persists `signal_quality`: fair probability, costs, half-life,
HMS, opportunity, style, `TRADE|SKIP`, reason codes.

## Sizing (Parte 22)

Capped fractional Kelly from edge, confidence, liquidity, and hard risk caps.
No martingale. No auto risk-up after losses.

## Portfolio allocation (Parte 24)

When several markets are hot in the same scan, capital is **not** first-come.
`evaluate_markets` (paper-run / shadow / `run_scan`) scores the batch, then
`PortfolioAllocator` ranks by a weighted mix of opportunity score, risk-adjusted
PnL velocity, net edge, and liquidity. Velocity is never maximized alone.

The allocator **proposes** TAKE / DOWNSIZE / SKIP. Risk VETO remains absolute
and can still block a TAKE (spread, kill switch, category/total caps, …).

Correlations are never estimated from prints. A pair is linked only when an
explicit rule fires:

| Rule | When it fires | Documented assumption |
| --- | --- | --- |
| Same underlying | Shared official Chainlink symbol or documented alias (`btc/usd`, …) | Same parsed underlying |
| Same category + window | Both have a parsed window (5m / 15m / 4h / official 30s/60s) | Same category and window can be the same horizon bet |
| Tag overlap | ≥ `portfolio.tag_overlap_min` tags after dropping generics | Shared specific tags only |
| YAML group | Named group in `configs/default.yaml` | Group `assumption` string |

Default groups: `crypto_short_window` (5m/15m and official 30s/60s TWAP across
BTC/ETH/SOL — **not** a measured rho), `weather_city`, `sports_game`,
`esports_match`. Weather/sports/esports buckets are keyed by parsed city/game/
match, so Chicago vs London can both pass.

Detected regime labels (Parte 25) and optional fixture stamp
`raw_gamma.hotflow_regime` may **scale** a group's cap. They do not invent a
new correlation link. Skip reason: `CORRELATED_EXPOSURE`. Partial room:
`PORTFOLIO_DOWNSIZED` (still goes to risk). Concentration vs open/category/total:
`PORTFOLIO_CONCENTRATION`.

## Regime detection (Parte 25)

Labels are attached on evaluate / scan (`extras.regime`). Detectors use
**explicit features only**. Missing spread, TTR, news apply, forecast
dispersion, or sports period → that rule does not fire; primary is `N/A`
(`invented: false`).

| Category | Labels | Features |
| --- | --- | --- |
| Crypto | `low_volatility` / `normal` / `high_volatility` / `trend` / `mean_reversion` / `news_shock` / `liquidity_vacuum` / `near_resolution` | book spread, TTR, validated news apply+class, liquidity, imbalance+last trade vs mid |
| Sports | `pre_game` / `early_live` / `mid_game` / `late_game` / `overtime` | official Sports WS `live` / `ended` / `period` / `status` |
| Weather | `forecast_uncertainty_high` / `forecast_converging` / `observation_phase` / `near_resolution` | TTR + labeled forecast std or ensemble_spread |

YAML `regimes.strategies.<category>.disabled_regimes` (or a non-empty
`enabled_regimes` allow-list) can skip with `REGIME_DISABLED`. That is a
strategy gate. **Risk VETO is unchanged** and still runs on every TAKE.

`portfolio.regimes` maps a detected label id (e.g. `news_shock`) to group-cap
scales. No learned ML regimes in this pass.

## Mixed paper soak

`hotflow paper-soak --mixed` is PAPER-only and **fixture-driven** (not a live
Gamma scan). One book includes BTC+ETH 5m, BTC+ETH 15m, Chicago weather, and
NBA, plus a labeled news-shock recipe. It measures how often
`CORRELATED_EXPOSURE` / `PORTFOLIO_DOWNSIZED` / regime overlays fire.

5m vs 15m is not a free extra slot: `same_category_window` links equal
windows only; `same_underlying` links BTC 5m↔15m; YAML `crypto_short_window`
joins all short windows (`max_markets: 1` by default). That is an explicit
group, not a measured rho. `--long` remains the labeled ≥50-close ledger soak
and does not go through the allocator.
