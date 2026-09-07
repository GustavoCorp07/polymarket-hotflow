# Deployment

Paper Docker:

```bash
docker compose up --build
```

CI source of truth is local: `make ci` / `scripts/ci_local.sh` / `hotflow ci`
(lint, typecheck, pytest, mock paper-run, backtest smoke, secret-hygiene).
GitHub-hosted `ubuntu-latest` is billing-locked — see [`docs/ci.md`](ci.md).
Free remote: GitLab.com shared runners via `.gitlab-ci.yml`.

Optional localhost metrics + paper UI (`hotflow dashboard`, port 9109;
`hotflow serve-metrics`, port 9108): `/`, `/api/state`, `/events`, `/metrics`,
`/health`, `/ready`. Default-off. Bind `127.0.0.1`. Not a venue API.

Public static demo (GitHub Pages, no Actions deploy):
[https://GustavoCorp07.github.io/polymarket-hotflow/](https://GustavoCorp07.github.io/polymarket-hotflow/).
See [`github-pages.md`](github-pages.md). Keep the repo public.

LIVE deploy is a **release gate**, not a compose default. Do not put credentials
in images or git. Promote only after paper → shadow → human review
(Parte 29 / 59).
