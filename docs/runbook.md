# Runbook

## Paper (supported)

```bash
pip install -e ".[dev]"
hotflow paper-run --mock
hotflow scan
pytest -q
```

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
