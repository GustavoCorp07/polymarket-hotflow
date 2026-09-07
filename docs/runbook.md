# Runbook

## Paper (supported)

```bash
pip install -e ".[dev]"
hotflow paper-run --mock    # TWAP + Chicago + Gamma weather texts + NBA, PAPER only
hotflow weather-fixtures    # public Gamma weather-tag text → tests/fixtures/weather/
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
pytest -q tests/test_twap.py tests/test_rtds_cache.py tests/test_weather_sports.py tests/test_weather_gamma_fixtures.py tests/test_esports.py tests/test_sports_cache.py tests/test_backtest.py tests/test_recorder.py tests/test_tuner.py
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
```

Or set `trading.mode: shadow` / `trading.shadow: true`. Decisions and
`would_buy` / `would_sell` / `expected_price` audits are written; **no orders**.

## LIVE

Do not enable until Parte 59 LIVE gates: shadow consistency, failure injection,
reconciled accounting, isolated secrets, tested kill switch. Then all of:

- `trading.mode: live`
- `live.accept_*` flags true
- `HOTFLOW_ACCEPT_LIVE=1`

## Cold-path skills (do not mutate production)

```bash
python scripts/hotflow_daily_review.py
python scripts/hotflow_experiment.py
python scripts/hotflow_incident.py
```

## Kill switch recovery

Inspect logs and SQLite `risk_decisions`. Call
`KillSwitchBoard.reset(acknowledge="operator confirmed recover")` only after
the cause is understood. There is no silent auto-reset.
