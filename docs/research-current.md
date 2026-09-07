# Research notes — current official sources

**Retrieved:** 2026-09-07  
**Rule:** Do not invent Polymarket endpoints, fees, TWAP values, or prices. Re-check
[docs.polymarket.com](https://docs.polymarket.com) and
[platform.kimi.ai](https://platform.kimi.ai/docs/guide/kimi-k3-quickstart.md)
before changing clients.

---

## 1. Kimi K3 (cold-path research only)

**Primary source:** [Kimi K3 Quickstart](https://platform.kimi.ai/docs/guide/kimi-k3-quickstart.md)  
**Index:** [platform.kimi.ai/docs/llms.txt](https://platform.kimi.ai/docs/llms.txt)

| Item | Official value |
| --- | --- |
| Base URL | `https://api.moonshot.ai/v1` |
| Model id | `kimi-k3` |
| Auth header | `Authorization: Bearer $MOONSHOT_API_KEY` |
| Compatibility | OpenAI Chat Completions (`openai>=1.0`) |
| `reasoning_effort` | `low` \| `high` \| `max` (default `max`) |
| Context | Up to 1,048,576 tokens when the plan allows (`max_completion_tokens` default 131072, max 1048576) |
| Thinking | Always on; cannot disable chain-of-thought — use `low` to shorten it |

Official Python init (docs):

```python
from openai import OpenAI
import os

client = OpenAI(
    api_key=os.environ["MOONSHOT_API_KEY"],
    base_url="https://api.moonshot.ai/v1",
)
```

HOTFLOW also accepts `KIMI_API_KEY` as an alias for the same secret. The client
never sends private keys, CLOB credentials, or `.env` contents to the model.

**HOTFLOW policy:** Kimi is **cold path only** (research, critique, post-trade
analysis). It is not imported by decide/transmit code.

Documented extras used by the client (optional): structured output via
`response_format.json_schema` with `strict: true`; streaming exposes
`reasoning_content` separately from `content`. Temperature / top_p are fixed
server-side — omit them.

---

## 2. Polymarket public surfaces (re-verified)

**Primary index:** [docs.polymarket.com/llms.txt](https://docs.polymarket.com/llms.txt)  
**API overview:** [docs.polymarket.com/getting-started/api](https://docs.polymarket.com/getting-started/api)

| Surface | Official URL | Role |
| --- | --- | --- |
| Gamma REST | `https://gamma-api.polymarket.com` | Events, markets, tags, resolution + fee metadata |
| CLOB REST | `https://clob.polymarket.com` | Books, tick/min size, fee-rate, orders (auth for private) |
| Data API | `https://data-api.polymarket.com` | Positions, activity, public analytics (cold-path / future P&L) |
| Market WS | `wss://ws-subscriptions-clob.polymarket.com/ws/market` | Public book / price / lifecycle |
| User WS | `wss://ws-subscriptions-clob.polymarket.com/ws/user` | Authenticated order/trade updates |
| RTDS | `wss://ws-live-data.polymarket.com` | Public reference prices, comments, trades, Chainlink TWAP relay |
| Sports WS | `wss://sports-api.polymarket.com/ws` | Public live game status / scores |

### Heartbeats (do not invent intervals)

| Feed | Official heartbeat |
| --- | --- |
| CLOB Market WS | Text frame `PING` every **10 seconds**; server replies `PONG` ([realtime-data](https://docs.polymarket.com/market-data/realtime-data), [user channel](https://docs.polymarket.com/api-reference/wss/user)) |
| CLOB User WS | Same: `PING` every **10 seconds** |
| RTDS | Text frame `PING` every **5 seconds** ([chainlink-twap](https://docs.polymarket.com/market-data/chainlink-twap), [realtime-data](https://docs.polymarket.com/market-data/realtime-data)) |

### Discovery (Gamma)

Documented public list (no auth):

```bash
curl -G "https://gamma-api.polymarket.com/markets" \
  --data-urlencode "closed=false" \
  --data-urlencode "limit=5"
```

Event by id / slug:

- `GET https://gamma-api.polymarket.com/events/{id}`
- `GET https://gamma-api.polymarket.com/events/slug/{slug}`

Gamma market fields used by the scanner (OpenAPI +
[market-details](https://docs.polymarket.com/market-data/market-details),
[list-markets](https://docs.polymarket.com/api-reference/markets/list-markets)):

- Identity: `id`, `conditionId`, `slug`, `question`, `clobTokenIds`
- State: `active`, `closed`, `archived`, `enableOrderBook`, `acceptingOrders`
- Book-ish: `bestBid`, `bestAsk`, `spread`, `lastTradePrice`
- Liquidity / volume: `liquidity`, `liquidityNum`, `volume`, `volumeNum`, `volume24hr`
- Fees: `feesEnabled`, `feeSchedule.{rate,exponent,takerOnly,rebateRate}`, `makerBaseFee`, `takerBaseFee`
- Size/tick (Gamma): `orderMinSize`, `orderPriceMinTickSize`
- Resolution: `resolutionSource`, `umaResolutionStatus`, `endDate`, `resolvedBy`
- Taxonomy: `category`, `tags`, `events`, `sportsMarketType`

Scanner is **dynamic** (filters on live fields). It is not a fixed category whitelist.

### CLOB public market data (no auth)

Documented production host: `https://clob.polymarket.com`

| Purpose | Official path |
| --- | --- |
| Order book | `GET /book?token_id=` — includes `bids`, `asks`, `min_order_size`, `tick_size`, `timestamp` ([get-order-book](https://docs.polymarket.com/api-reference/market-data/get-order-book)) |
| Tick size | `GET /tick-size?token_id=` → `{ "minimum_tick_size": 0.01 }` |
| Fee rate | `GET /fee-rate?token_id=` → `{ "base_fee": <int bp> }` |
| CLOB market bundle | `GET /clob-markets/{condition_id}` — `mos` min order size, `mts` tick, `mbf`/`tbf` maker/taker base fee bp, `fd` fee details `{r,e,to}`, `itode` 250 ms taker delay |

**Fee / tick / min size are always fetched from these current APIs (or Gamma
`feesEnabled` / `feeSchedule` on the same market).** They are never hardcoded
by category.

### Official fee formula

[Fees](https://docs.polymarket.com/trading/fees):

```text
fee = C × feeRate × p × (1 - p)
```

- `C` = shares traded, `p` = share price  
- Makers are never charged; only takers pay  
- Fees rounded to 5 decimal places  
- Category table on that page is **documentation of typical schedules**, not a
  substitute for per-market `feesEnabled` / `feeSchedule.rate` / CLOB `fee-rate`

If fee flags cannot be fetched, HOTFLOW **skips** the market (`UNKNOWN_FEES`).
It does not assume 0 or a category default.

### Auth (LIVE only; unused in paper)

[API authentication](https://docs.polymarket.com/getting-started/api):

- **L1:** EIP-712 `ClobAuthDomain` / `ClobAuth` on Polygon `chainId` 137  
- Create: `POST https://clob.polymarket.com/auth/api-key`  
- Derive: `GET https://clob.polymarket.com/auth/derive-api-key`  
- Headers: `POLY_ADDRESS`, `POLY_SIGNATURE`, `POLY_TIMESTAMP`, `POLY_NONCE`  
- **L2 HMAC:** message = `timestamp + METHOD + path + exact_body`;
  `urlsafeBase64WithPadding(HMAC-SHA256(base64Decode(secret), message))`  
- L2 headers: `POLY_ADDRESS`, `POLY_SIGNATURE`, `POLY_TIMESTAMP`,
  `POLY_API_KEY`, `POLY_PASSPHRASE`

Paper mode never signs or transmits live orders.

### Official order model (do not invent statuses)

[Order lifecycle](https://docs.polymarket.com/concepts/order-lifecycle):

- Venue order types: GTC, GTD, FOK, FAK; optional post-only  
- Venue placement statuses: `live`, `matched`, `delayed`, `unmatched`  
- Venue trade statuses: `MATCHED` → `MINED` → `CONFIRMED` / `RETRYING` / `FAILED`  
- Taker delay: 250 ms when `GET /clob-markets/{condition_id}` has `itode: true`  
- Never infer a fill from book level disappearance alone (HOTFLOW rule + venue
  settlement is async)

HOTFLOW’s **internal** paper state machine (`CREATED` → `SUBMITTED` → …) is
ours. It maps to venue statuses only when a live adapter exists and is gated.

### Chainlink TWAP (do not invent a TWAP)

Re-verified **2026-09-07** from
[Chainlink TWAP](https://docs.polymarket.com/market-data/chainlink-twap)
and [Realtime data](https://docs.polymarket.com/market-data/realtime-data).

| Item | Official value |
| --- | --- |
| RTDS URL | `wss://ws-live-data.polymarket.com` (public, **no credentials**) |
| Heartbeat | text `PING` every **5 seconds** |
| Lookback windows | **30** and **60** seconds only (not publication cadence) |
| Raw topics | `crypto_prices_twap_thirty`, `crypto_prices_twap_sixty` |
| SDK topic | `prices.crypto.chainlink.twap` with `windowSeconds` / `window_seconds` 30\|60 |
| Symbol form | lowercase slash, e.g. `btc/usd` |
| Documented Chainlink symbols | `btc/usd`, `eth/usd`, `sol/usd`, `xrp/usd` |
| Raw `filters` | exact compact JSON, no spaces: `{"symbol":"btc/usd"}` |
| Payload | `value` (display), `full_accuracy_value` (E18), `payload.timestamp` = Chainlink observation time |
| After disconnect | **no snapshot / history / replay** — reconnect and resubscribe |
| Homemade TWAP | **forbidden** — sampling/weighting unpublished |

[Liquidity rewards](https://docs.polymarket.com/market-makers/liquidity-rewards)
says crypto **5-minute, 15-minute, and 4-hour** markets **settle on TWAP**.
That is **market duration**, not the Chainlink 30s/60s lookback. Official docs
do **not** map 5m/15m/4h → 30 vs 60, and do **not** publish the start-vs-end /
strike settlement formula for Up/Down markets.

HOTFLOW therefore:

- parses 30 or 60 **only** from market resolution metadata/text
- skips (`TWAP_WINDOW_UNKNOWN`) when the market says TWAP/Chainlink but the
  lookback is missing or both 30 and 60 appear
- never defaults the window to 60
- uses the official RTDS observation (or an official-shape fixture) as
  `current_twap`; `projected_twap` is persistence of that official print
- treats `required_future_price` as the **required official TWAP at expiry**
  (the parsed strike). It does not reconstruct a remaining in-window average
- uses a documented **paper heuristic** for `probability_of_finish_above/below`
  (r=0 digital around the official observation). That is not venue math

Optional live public RTDS client: `PublicRtdsTwapClient` (off by default,
`feeds.rtds.live_public_client: false`). pytest never opens the socket.

### Official Python SDK (optional)

Package `polymarket-client` ≥ 0.3.0 —
[Python SDK](https://docs.polymarket.com/getting-started/python).
Paper scan uses public HTTP so tests do not require the SDK.

---

## 3. What we deliberately do **not** invent

- Extra CLOB/Gamma paths beyond those listed above  
- Category fee constants (e.g. “crypto is always 0.07”)  
- Homegrown TWAP or “last price = fill” rules  
- User-WS without L2 credentials  
- LIVE transmit without the acceptance gates in `docs/architecture.md`
