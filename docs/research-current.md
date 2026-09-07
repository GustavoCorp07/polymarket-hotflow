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
| Sports WS | **Server** sends text `ping` every **5 seconds**; client replies `pong` within **10 seconds** ([realtime-data](https://docs.polymarket.com/market-data/realtime-data)). Opposite of CLOB/RTDS client-`PING`. |

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

**PAPER RTDS cache subscriber** (`PublicRtdsSubscriber` + `TwapPrintCache`):

- Default `feeds.rtds.subscriber_enabled: false` — paper-run/scan do **not**
  open a socket unless `--rtds-live` or that flag is set
- Caches latest official prints keyed by `(symbol, window)` with ingest
  timestamps; stale/missing → `TWAP_OBSERVATION_STALE` /
  `TWAP_OBSERVATION_MISSING` (no invented print)
- Subscribe frames use official topics only; undocumented symbols are dropped
- `hotflow rtds-cache` defaults to `--mock` (official-shape fixtures on disk);
  `--live` is the optional unauthenticated collect
- `hotflow paper-run --twap-cache data/rtds_twap_cache.json` injects a cache
  for a Gamma/paper cycle without a socket

### Sports WebSocket (do not invent fields)

Re-verified **2026-09-07** from
[Realtime data](https://docs.polymarket.com/market-data/realtime-data).

| Item | Official value |
| --- | --- |
| URL | `wss://sports-api.polymarket.com/ws` (public, **no subscribe frame**) |
| Heartbeat | server `ping` every **5s**; reply `pong` within **10s** |
| Raw WS | **no envelope** — each message is the game object |
| SDK envelope | `topic: sports`, `type: sport_result` |
| Fields | `gameId`, `leagueAbbreviation`, `homeTeam`, `awayTeam`, `status`, `live`, `ended`, `score` (combined `"-"`), `period`, `elapsed`, `slug`, `turn` (NFL/CFB), `finishedAt` / `finished_timestamp`, `sportradarGameId` |
| Documented leagues | `NFL`, `NHL`, `MLB`, `NBA`, `CBB`, `CFB`, `Soccer`, `Esports`, `Tennis` |
| Periods | `1H`/`2H`, `1Q`–`4Q`, `HT`, `FT`, `FT OT`, `FT NR`, MLB `End N`, maps `1/3`… (example payload also uses `Q4`) |
| Status | **case-sensitive and sport-specific** (do not reuse NBA statuses on Soccer/Tennis/Esports) |

HOTFLOW paper sports path:

- parses league/teams from Gamma metadata using only documented league names
- never maps `football` → `Soccer`
- injects official-shape game frames in pytest; live client stays **off**
  (`sports.live_public_client: false`, `feeds.sports_ws.subscriber_enabled: false`)
- per-sport models: NBA/CBB basketball ≠ Soccer; Tennis/NFL/… → `UNSUPPORTED_SPORT`
- missing / stale official-shape state → `SPORTS_STATE_MISSING` /
  `SPORTS_STATE_STALE` (never invent a score)
- unparseable rules → `SPORTS_RULES_UNKNOWN`

**PAPER Sports WS cache subscriber** (`PublicSportsSubscriber` + `SportsGameCache`):

- Default `feeds.sports_ws.subscriber_enabled: false` — paper-run/scan do **not**
  open a socket unless `--sports-live` or that flag is set
- Caches latest official-shape game objects keyed by `gameId`; undocumented
  leagues are dropped. Live `leagueAbbreviation` is case-folded onto the
  documented set only (`mlb` → `MLB`). Names such as `spl` or `challenger`
  are not invented into Soccer/Tennis.
- **No subscribe frame** (official). Server `ping` → client `pong`. After
  disconnect: reconnect only (no snapshot / replay)
- `hotflow sports-cache` defaults to `--mock` (official-shape fixtures on disk);
  `--live --seconds N` is the optional unauthenticated collect
- `hotflow paper-run --sports-cache data/sports_ws_cache.json` injects a cache
  without a socket
- pytest uses `InjectedFrameTransport` only — never opens the Sports WS

A short PAPER live collect from this environment **did connect** to
`wss://sports-api.polymarket.com/ws`. The wire also emits
`leagueAbbreviation` values that are **not** in the documented set
(`spl`, `challenger`, `tur`, …); those are dropped. Documented names may
arrive lowercase (`mlb`) and are case-folded only. A redacted official-field
sample is in `tests/fixtures/sports_ws_live_sample.json`. Extra wire keys
such as `eventState` are ignored. Data remains informational.

### Esports (official Gamma text exists; live model does not)

Retrieved **2026-09-07**.

**What exists (official):**

| Surface | Finding |
| --- | --- |
| Gamma `GET /sports` | Title ids `cs2`, `lol`, `dota2`, `val` (plus `lol-wild-rift`). Resolution URLs: hltv.org, liquipedia LoL/Dota2/Valorant. Copied, not scraped. |
| Gamma `GET /sports/market-types` | Includes `esports_match_result`, `moneyline`, `child_moneyline`, plus CS2/LoL/Dota2-named types. No published settlement math. |
| Gamma `GET /events?tag_slug=` | `esports`, `cs2`, `lol`, `league-of-legends`, `dota-2`, `valorant` all return real events. |
| Sports WS status table | Esports row: `not_started`, `running`, `finished`, `postponed`, `canceled` ([realtime-data](https://docs.polymarket.com/market-data/realtime-data)). Do not reuse NBA statuses. |
| Sports WS CS2 example | [websocket/sports](https://docs.polymarket.com/market-data/websocket/sports) publishes a finished CS2 object: `leagueAbbreviation: "cs2"`, `score: "000-000\|2-0\|Bo3"`, `period: "2/3"`. Grammar of that score string is **not** specified. |

**What does not exist (do not invent):**

- AsyncAPI sports channel (`asyncapi-sports.json`) lists NFL, soccer, NBA, MLB, NHL, cricket — **not** esports titles. Score examples are soccer-style `2-1`.
- No official map/economy/round-differential stream.
- No documented mapping from `000-000\|2-0\|Bo3` to series/map wins.
- Sports WS live collect in this repo still drops `cs2`/`lol`/`dota2`/`val` because the **documented league set** used by the sports cache is `NFL`…`Esports`…`Tennis`, not Gamma `/sports` title ids. We do not invent that mapping on the live reader.

`hotflow esports-fixtures` stores public Gamma text only (`tests/fixtures/esports/`). Preferred ids captured 2026-09-07:

| id | Market | Official source in Gamma |
| --- | --- | --- |
| `1923406` | Dota 2 Shizageddon vs Nemiga (BO3) moneyline | `https://www.dotabuff.com` |
| `2268716` | LoL T1 vs Kiwoom DRX (BO3) | `https://gol.gg/esports/home` |
| `2308640` | Valorant TEC vs All Gamers (BO5) | `https://vlr.gg` |
| `536506` | CS2 PGL Bucharest Falcons vs FaZe | empty field; description names PGL |
| `693580` | LCK 2026 season playoffs (KT) | futures / one team → `ESPORTS_RULES_UNKNOWN` |

HOTFLOW paper esports path is **skip-heavy**:

- parse game / teams / BO / source from Gamma text
- per-title adapters (`cs2` ≠ `lol` ≠ `dota2` ≠ `val`); other titles → `UNSUPPORTED_SPORT`
- missing official-shape state → `ESPORTS_STATE_MISSING`
- injected CS2 docs-example score is stored but **not** parsed → `UNSUPPORTED_STRUCTURE`
- the only numeric `p_home_win` is ended + documented simple `N-M` pair (AsyncAPI score form). Live Sports WS client stays **off** (`esports.live_public_client: false`)
- pytest uses committed Gamma fixtures + injected official-shape rows — no unofficial scrapers

### Weather (no official Polymarket observation API)

Official Polymarket docs do **not** publish a weather observation WebSocket or
resolution-observation endpoint. Do **not** invent one.

**Public Gamma collect (PAPER metadata only), retrieved 2026-09-07:**

| Item | Official value |
| --- | --- |
| List events | `GET https://gamma-api.polymarket.com/events?tag_slug=weather` ([list-events](https://docs.polymarket.com/api-reference/events/list-events) documents `tag_slug`) |
| One market | `GET https://gamma-api.polymarket.com/markets/{id}` — same public host/fields as list-markets |
| Event by slug | `GET https://gamma-api.polymarket.com/events/slug/{slug}` |

The weather tag is broad (climate, disasters, city temperature/precip). The
fetcher keeps public fields only: `id`, `conditionId`, `slug`, `question`,
`description`, `resolutionSource`, `outcomes`, `endDate`, `closed`, `active`,
`groupItemTitle`, `line`, tag labels. **No** `clobTokenIds`, fees, or secrets.

CLI / script (writes `tests/fixtures/weather/`; optional gitignored `data/weather`):

```bash
hotflow weather-fixtures
python scripts/fetch_weather_gamma_fixtures.py --out tests/fixtures/weather --data-out data/weather
```

Preferred public ids captured 2026-09-07 (text copied, not invented):

| id | Question (Gamma) | Official `resolutionSource` / source sentence |
| --- | --- | --- |
| `2290078` | Jinan highest temp 15°C or below May 20 | `https://www.wunderground.com/history/daily/cn/jinan/ZSJN` |
| `4238333` | London lowest temp 13°C or below Sep 7 | `https://www.weather.gov/wrh/timeseries?site=eglc` |
| `4027989` | Seoul precip less than 75mm September | empty field; description names Korea Meteorological Administration |
| `678686` | Will 2026 be the hottest year on record? | empty field; rank/GLOTI wording is **not** a simple city threshold → `WEATHER_RULES_UNKNOWN` |

Limitations:

- Timezone is recorded only when an IANA/UTC token is present. City markets
  often omit it; **do not invent** `Asia/Shanghai` / `Europe/London`. Deadline
  text such as `11:59 PM ET` is a fallback clock, not the observation zone.
- Forecasts used in `paper-run --mock` are **labeled `source=fixture`**
  synthetic features for scoring demos. They are not live NWS/KMA/NOAA.
- If Gamma returns no weather markets at collect time, the fetcher stays and
  writes an empty bundle. Parser regressions use previously captured public
  Gamma text only.

HOTFLOW paper weather path:

- parses city / station / metric / unit / window / timezone / rounding /
  threshold / comparison / **source** from market text
- if the official source is missing, rules are incomplete, or confidence is
  low → `WEATHER_RULES_UNKNOWN` (never guess the resolver)
- external forecasts are **features only** (`WeatherForecast.source=fixture` in
  tests). They are never a substitute for the official resolution source
- missing forecast distribution → `WEATHER_FORECAST_MISSING`
- pytest uses committed Gamma fixtures + labeled forecasts only — no paid
  weather APIs, no live collect required

### Official Python SDK (optional)

Package `polymarket-client` ≥ 0.3.0 —
[Python SDK](https://docs.polymarket.com/getting-started/python).
Paper scan uses public HTTP so tests do not require the SDK.

---

### Event-driven backtest (no new endpoints)

Retrieved **2026-09-07**. Parte 26/27 runs **offline** on recorded official-shape
streams (`tests/fixtures/backtest/`). It does **not** invent Gamma/CLOB/RTDS
URLs, live fees, or TWAP values.

| Item | Rule |
| --- | --- |
| Fees | Dated fixture copy of official CLOB fee-rate fields (`as_of` marked). Formula remains `fee = C × feeRate × p × (1-p)`. Unmarked historical params are refused. |
| Books / trades | Replay time-ordered `book` / `trade` events. Candle-only streams → `CANDLE_ONLY_REFUSED`. |
| TWAP / sports / weather | Injected only when the fixture includes official-shape rows. No live sockets. |
| Look-ahead | Decisions see events at or before `ts`. Fill time is `ts + latency_ms [+ taker_delay_ms]` (documented paper assumption). |
| Selection | Reports record `abs_pnl` but refuse ranking by max absolute PnL. |

`hotflow backtest --fixture PATH` writes `reports/backtest-*.json`.
`hotflow shadow --mock` logs `would_buy` / `would_sell` and never sends orders.

### Official-shape stream recorder + offline tuner

Retrieved **2026-09-07**.

| Item | Official / policy |
| --- | --- |
| CLOB book | `GET https://clob.polymarket.com/book?token_id=` (public). Recorder polls this only. |
| CLOB fee-rate | `GET /fee-rate` → `base_fee` bp stored as `clob_base_fee_bp`. Curve `rate` copied from `clob-markets` `fd.r` when present — **not** `bp/10000`. |
| RTDS TWAP | Optional `--rtds` uses existing public RTDS 30s/60s client. Default off. |
| Defaults | `hotflow record-stream --mock` writes a **SYNTHETIC** multi-minute official-shape fixture. `--live` is optional. |
| Tuner | `hotflow tune --report` suggests bounded threshold/weight changes. `applied: false`. Refuses abs-PnL. `--write-suggestion` only under `reports/`. Never writes `configs/`. |

A short redacted live CLOB collect from this environment is in
`tests/fixtures/backtest/clob_book_live_sample.json` (token ids stripped).
The longer pytest stream `crypto_longer_synthetic.json` is labeled
`origin=synthetic_official_shape` — not a live archive.

---

## 3. What we deliberately do **not** invent

- Extra CLOB/Gamma paths beyond those listed above  
- Category fee constants (e.g. “crypto is always 0.07”)  
- Homegrown TWAP or “last price = fill” rules  
- User-WS without L2 credentials  
- LIVE transmit without the acceptance gates in `docs/architecture.md`
- A Polymarket weather observation API or unofficial weather station  
- Sports leagues, odds, or period/status values outside the official Sports WS schema  
- One probabilistic sports model reused across football / basketball / tennis / soccer
