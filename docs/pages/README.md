# Static paper dashboard (GitHub Pages)

Offline **PAPER** watch UI for
[https://GustavoCorp07.github.io/polymarket-hotflow/](https://GustavoCorp07.github.io/polymarket-hotflow/).

GitHub Pages serves **static files only**. It cannot run `hotflow dashboard`,
Python, or SSE against a live process. This folder is the publishable tree.

## What you see

Same look as the localhost UI (`src/hotflow/monitoring/static/dashboard.html`):
KPIs from the paper ledger, feed health, last-cycle hot markets, TRADE/SKIP
with `reason_codes` / `spread_regime`, **mode paper**, **live gates CLOSED**.

The gold banner is intentional:

> Static GitHub Pages demo — for live local ledger use `hotflow dashboard`

Numbers come from committed `paper-run --mock` snapshots (FILL/MARK/FLATTEN).
They are **not** venue balances and **not** LIVE.

## Files

| Path | Role |
| --- | --- |
| `index.html` | Static page (no Python) |
| `assets/dashboard.css` | Same palette as the live dashboard |
| `assets/pages.js` | Poll `state.json` + rotate snapshots |
| `demo-bundle.js` | Embedded frames so the page works if a fetch fails |
| `demo-state.json` | Canonical latest `/api/state` shape |
| `state.json` | Poll target (same payload as `demo-state.json`) |
| `snapshots.json` | Manifest (`poll`, `rotate`, interval) |
| `snapshots/01-*.json` … | 2–3 rotating mock-run frames |

## Regenerate

```bash
python scripts/export_pages_demo.py
# or: python scripts/export_pages_demo.py --out docs/pages --cycles 2
```

That rebuilds JSON + `demo-bundle.js` from a real mock paper session. It does
not change the localhost `hotflow dashboard` server.

## Live local ledger (not Pages)

```bash
hotflow dashboard --mock
# http://127.0.0.1:9109/   SSE /events + poll /api/state
```

## Publish

See [`docs/github-pages.md`](../github-pages.md). GitHub Actions is
billing-locked — do not use `actions/deploy-pages`. Push this directory to the
`gh-pages` branch root (`git subtree` or orphan branch). Keep the repo
**public** (Pages free tier).
