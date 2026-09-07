# CI (free paths)

GitHub-hosted `ubuntu-latest` jobs **cannot start** on this account (Actions
billing lock). Do not treat a green GitHub check as required.

## Default: local `make ci`

Same smoke as the historical `.github/workflows/ci.yml` (ruff, mypy, pytest,
`paper-run --mock`, backtest import, secret-hygiene grep):

```bash
pip install -e ".[dev]"
make ci
# or:
bash scripts/ci_local.sh
hotflow ci
```

That script is the **source of truth**.

## Free remote: GitLab.com shared runners

`.gitlab-ci.yml` runs `make ci` on GitLab’s free shared runners (not GitHub
minutes).

Mirror options:

1. GitLab → **New project** → **Import repository** → GitHub URL, or
2. `git remote add gitlab https://gitlab.com/<you>/polymarket-hotflow.git && git push gitlab main`

Then enable the pipeline on the GitLab project. No extra paid minutes.

## GitHub Actions (kept, not relied on)

The workflow file is preserved so history is not deleted. Push/PR triggers are
off (`workflow_dispatch` only). The hosted job is `if: false` so it cannot
queue `ubuntu-latest`. A commented `runs-on: self-hosted` job is in the file
if you later attach a runner **and** the account can still dispatch workflows.

Trade-off: GitLab shared runners are the practical free remote. A self-hosted
GitHub runner avoids GH minutes but still depends on Actions being allowed to
dispatch. Local `make ci` always works.

Optional one-liners if you already run them: Woodpecker or Forgejo Actions can
call `bash scripts/ci_local.sh` the same way. Not shipped as extra config.

## What CI does **not** do

- No LIVE transmit
- No hardcoded venue fees
- No LLM on the hot path
