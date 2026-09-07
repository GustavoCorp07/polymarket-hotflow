# Runbook

## Paper (supported)

```bash
pip install -e ".[dev]"
hotflow paper-run --mock    # TWAP + weather + NBA sports fixtures, PAPER only
hotflow rtds-cache --mock   # write official-shape cache (no socket)
hotflow paper-run --twap-cache data/rtds_twap_cache.json --mock
hotflow sports-cache --mock # write official-shape Sports WS cache (no socket)
hotflow paper-run --sports-cache data/sports_ws_cache.json --mock
hotflow scan
pytest -q tests/test_twap.py tests/test_rtds_cache.py tests/test_weather_sports.py tests/test_sports_cache.py
pytest -q
```

`weather.enabled` / `sports.enabled` default on for paper scoring. They never
open paid weather APIs. `feeds.sports_ws.subscriber_enabled` and
`--sports-live` stay off unless you want a brief unauthenticated Sports WS
collect (`hotflow sports-cache --live --seconds 12`). They never enable LIVE
CLOB orders. Live Sports frames are informational and may be delayed or wrong. Unparseable rules or
missing/stale forecast/game state skip (`WEATHER_*` / `SPORTS_*` /
`UNSUPPORTED_SPORT`).

`feeds.rtds.subscriber_enabled` and `--rtds-live` stay off unless you want a
brief unauthenticated RTDS collect. They never enable LIVE CLOB orders.

## Shadow

Set `trading.mode: shadow` or `trading.shadow: true`. Decisions and
`would_buy` audits are written; **no orders**.

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
