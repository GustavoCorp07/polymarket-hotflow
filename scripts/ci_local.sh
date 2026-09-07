#!/usr/bin/env bash
# Local CI source of truth. Mirrors .github/workflows/ci.yml without GitHub-hosted runners.
# Usage: make ci   |   bash scripts/ci_local.sh   |   hotflow ci
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

export PYTHONDONTWRITEBYTECODE=1
PYTHON="${PYTHON:-python3}"

echo "==> ruff"
"$PYTHON" -m ruff check src tests scripts

echo "==> mypy"
"$PYTHON" -m mypy src/hotflow

echo "==> pytest"
"$PYTHON" -m pytest -q

echo "==> paper-run --mock"
mkdir -p reports
"$PYTHON" -m hotflow paper-run --mock --no-hold --out reports/ci-paper.json

echo "==> backtest interface smoke"
"$PYTHON" -c "from hotflow.backtest import NullBacktester; print(NullBacktester)"

echo "==> secret hygiene"
if [[ -f .env ]]; then
  echo "refusing checked-in or leftover .env" >&2
  exit 1
fi
# Real PEM headers only — do not use a pattern that matches this file.
if git grep -nE -e '-----BEGIN ([A-Z0-9]+ )?PRIVATE KEY-----' \
  -- ':!.github' ':!docs' ':!tests/test_kimi.py' ':!src/hotflow/ai_research/kimi_client.py'
then
  echo "secret hygiene failed: PEM header found" >&2
  exit 1
fi

echo "==> local CI ok"
