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

Stub only (`UNSUPPORTED_STRUCTURE`). No invented live feeds or shared sports
model.

## Signal contract (Parte 46)

Every decision persists `signal_quality`: fair probability, costs, half-life,
HMS, opportunity, style, `TRADE|SKIP`, reason codes.

## Sizing (Parte 22)

Capped fractional Kelly from edge, confidence, liquidity, and hard risk caps.
No martingale. No auto risk-up after losses.
