# Security (aligned to `docs/MISSION-FULL.md` Parte 37, 60, 62)

- Ship `.env.example` only. Never commit `.env`, keys, or passphrases.
- Do not put secrets in logs, prompts, reports, alerts, or stack traces.
  JSON logs and alert callbacks run through `hotflow.monitoring.redact`.
- Kimi/Grok never receive private keys, seed phrases, or withdrawal credentials.
- `hotflow.execution` / `hotflow.risk` do not import `hotflow.ai_research`.
- LIVE needs YAML accept flags **and** `HOTFLOW_ACCEPT_LIVE=1`. This pass
  freezes those gates **CLOSED**. Check with `hotflow live-gates` (exit 1 if
  any acceptance gate is open).
- Narrow executor only: `place_order` / `cancel_order` / `get_positions` /
  `get_orders`. Those methods **raise** in PAPER/SHADOW and still refuse if
  gates are forced open — signing is not implemented. There is no
  `execute_arbitrary_transaction()`.
- AI components must never withdraw.
- Shared bot VMs are **not** credential isolation.

## Env vars (placeholders only in git)

| Variable | Path | Notes |
| --- | --- | --- |
| `HOTFLOW_ACCEPT_LIVE` | LIVE gate | Must stay `0` / unset |
| `KIMI_API_KEY` / `MOONSHOT_API_KEY` | **Cold path only** | Research client. Never on decide/transmit. Empty in `.env.example` |
| `POLYMARKET_PRIVATE_KEY` / `POLY_*` | LIVE only | Unused. Empty placeholders. Never load in paper |
| `CHAINLINK_CLIENT_*` | optional | Not used by paper RTDS path |

Never ask for a seed phrase. Never log these values.

```bash
hotflow live-gates
# trading.mode=CLOSED …
# live_gates_open=False freeze_ok=True signing_implemented=False
```
