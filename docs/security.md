# Security (aligned to `docs/MISSION-FULL.md` Parte 37, 60, 62)

- Ship `.env.example` only. Never commit `.env`, keys, or passphrases.
- Do not put secrets in logs, prompts, reports, or stack traces.
- Kimi/Grok never receive private keys, seed phrases, or withdrawal credentials.
- `hotflow.execution` / `hotflow.risk` do not import `hotflow.ai_research`.
- LIVE needs YAML accept flags **and** `HOTFLOW_ACCEPT_LIVE=1`.
- Prefer a narrow signer API later (`place_order` / `cancel_order` / positions).
  Do not expose `execute_arbitrary_transaction()`.
- AI components must never withdraw.
- Shared bot VMs are **not** credential isolation.

Required later (not in git): `KIMI_API_KEY` or `MOONSHOT_API_KEY`,
`POLYMARKET_WALLET_ADDRESS`, L2 `POLY_*` only behind LIVE gates.
Never ask for a seed phrase.
