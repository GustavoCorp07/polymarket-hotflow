# GitHub Pages (static paper dashboard)

Public demo URL (after the coordinator publishes `gh-pages`):

**https://GustavoCorp07.github.io/polymarket-hotflow/**

GitHub Pages serves **static files only**. It cannot run `hotflow dashboard`,
a Python process, or SSE. The live paper watch UI stays local:

```bash
hotflow dashboard --mock          # http://127.0.0.1:9109/
hotflow paper-run --mock --dashboard
```

The Pages site is the committed tree under [`docs/pages/`](pages/README.md)
(same look as `src/hotflow/monitoring/static/dashboard.html`, paper ledger
only, live gates CLOSED).

## Why not GitHub Actions?

This account’s GitHub-hosted runners are **billing-locked**. Do **not** use
`actions/deploy-pages`, `peaceiris/actions-gh-pages`, or any workflow that
needs Actions minutes. Deploy is `git push` of the static tree.

Keep the repository **public**. Free GitHub Pages requires a public repo.

## Enable Pages (once)

In the GitHub repo: **Settings → Pages**

1. Source: **Deploy from a branch**
2. Branch: **`gh-pages`**
3. Folder: **`/ (root)`**
4. Save

Do **not** point Pages at `/docs` on `main` — that folder is operator
markdown (`MISSION-FULL.md`, runbook, …), not the dashboard root.

## Publish without Actions

The publishable files are exactly:

```text
docs/pages/index.html
docs/pages/assets/dashboard.css
docs/pages/assets/pages.js
docs/pages/demo-bundle.js
docs/pages/demo-state.json
docs/pages/state.json
docs/pages/snapshots.json
docs/pages/snapshots/*.json
docs/pages/.nojekyll
docs/pages/README.md
```

On Pages they must sit at the **branch root** so
`https://GustavoCorp07.github.io/polymarket-hotflow/` serves `index.html`.

### Option A — `git subtree` (from `main` after merge)

```bash
git checkout main
git pull origin main
git subtree split --prefix docs/pages -b gh-pages-split
git push origin gh-pages-split:gh-pages --force
git branch -D gh-pages-split
```

`--force` is required when rewriting the orphan-style `gh-pages` tip. Only
the coordinator should run that.

### Option B — orphan `gh-pages` branch

```bash
git checkout main
git pull origin main
git checkout --orphan gh-pages
git reset --hard
git checkout main -- docs/pages
mkdir -p /tmp/hotflow-pages
cp -a docs/pages/. /tmp/hotflow-pages/
git rm -rf .
cp -a /tmp/hotflow-pages/. .
touch .nojekyll
git add -A
git commit -m "Publish static paper dashboard to GitHub Pages"
git push -u origin gh-pages
git checkout main
```

After the first push, later updates can reuse option A or:

```bash
git checkout gh-pages
git checkout main -- docs/pages
cp -a docs/pages/. .
git add -A
git commit -m "Refresh Pages demo from docs/pages"
git push origin gh-pages
git checkout main
```

## Refresh the demo JSON

```bash
python scripts/export_pages_demo.py --out docs/pages --cycles 2
git add docs/pages
git commit -m "Refresh paper Pages demo snapshots"
```

Then republish `gh-pages` with option A or B. Do not invent venue PnL by
hand-editing JSON.

## Local preview of the static tree

```bash
python -m http.server 8080 --directory docs/pages
# open http://127.0.0.1:8080/
```

That is still static (poll + rotate). For the live in-process ledger use
`hotflow dashboard`.

## Out of scope

- LIVE trading
- Invented venue balances
- GitHub Actions deploy
- Changing the localhost `hotflow dashboard` / SSE server
