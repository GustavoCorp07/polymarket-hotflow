# Default source of truth for lint / types / tests / paper smoke.
# GitHub-hosted ubuntu-latest is billing-locked; do not wait on Actions minutes.
.PHONY: ci lint typecheck test paper-smoke secret-hygiene dashboard pages-demo

PYTHON ?= python3

ci:
	bash scripts/ci_local.sh

lint:
	$(PYTHON) -m ruff check src tests scripts

typecheck:
	$(PYTHON) -m mypy src/hotflow

test:
	$(PYTHON) -m pytest -q

paper-smoke:
	mkdir -p reports
	$(PYTHON) -m hotflow paper-run --mock --no-hold --out reports/ci-paper.json

secret-hygiene:
	test ! -f .env
	@if git grep -nE -e '-----BEGIN ([A-Z0-9]+ )?PRIVATE KEY-----' \
	  -- ':!.github' ':!docs' ':!tests/test_kimi.py' ':!src/hotflow/ai_research/kimi_client.py'; then \
	  echo "secret hygiene failed: PEM header found" >&2; exit 1; \
	fi

dashboard:
	$(PYTHON) -m hotflow dashboard --mock

pages-demo:
	$(PYTHON) scripts/export_pages_demo.py --out docs/pages --cycles 2
