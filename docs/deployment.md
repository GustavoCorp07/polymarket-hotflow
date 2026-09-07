# Deployment

Paper Docker:

```bash
docker compose up --build
```

CI (`.github/workflows/ci.yml`): lint, typecheck, pytest, mock paper-run,
backtest smoke, secret-hygiene grep.

Optional localhost metrics (`hotflow serve-metrics`, port 9108): `/metrics`,
`/health`, `/ready`. Default-off. Bind `127.0.0.1`. Not a venue API.

LIVE deploy is a **release gate**, not a compose default. Do not put credentials
in images or git. Promote only after paper → shadow → human review
(Parte 29 / 59).
