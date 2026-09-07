# Strategy notes (aligned to `docs/MISSION-FULL.md`)

Source of truth: **Parte 7–17, 22–25, 45–47, 64**.

## Principle

HOT ≠ EDGE. HMS spends compute. Opportunity + fair value decide whether a trade
exists. **NO TRADE is valid.**

## Crypto (highest paper priority)

- Discover BTC/ETH/SOL Up/Down (5m / 15m / 4h) dynamically — no fixed whitelist.
- Fair value is `P(outcome|info)`, not momentum > threshold.
- TWAP-aware hooks accept **only** official Chainlink/RTDS windows 30s and 60s
  (`docs/research-current.md`). Do not invent a TWAP.
- Maker vs taker: compare `EV_maker` vs `EV_taker`; taker only if half-life is
  short and NET edge remains positive after fetched fees.

## Weather / sports / esports

Adapters exist with tested `accepts()` / `experiment_fields()`. They do **not**
trade until resolution rules are parsed with confidence. Missing live data ⇒
low confidence or NO TRADE (Parte 12–14).

## Signal contract (Parte 46)

Every decision persists `signal_quality`: fair probability, costs, half-life,
HMS, opportunity, style, `TRADE|SKIP`, reason codes.

## Sizing (Parte 22)

Capped fractional Kelly from edge, confidence, liquidity, and hard risk caps.
No martingale. No auto risk-up after losses.
