# Deployment

Paper Docker:

```bash
docker compose up --build
```

CI (`.github/workflows/ci.yml`): lint, typecheck, pytest, mock paper-run,
backtest smoke, secret-hygiene grep.

LIVE deploy is a **release gate**, not a compose default. Do not put credentials
in images or git. Promote only after paper → shadow → human review
(Parte 29 / 59).
