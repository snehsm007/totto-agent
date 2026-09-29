# Makefile for Totto, Mercedes F1 Fan Agent (totto-mercedes-f1-fan-agent)
# Safe wrapper around `python -m totto_suite <command>` enforcing R5 (push-disabled).

ENV ?= dev-totto-gecx
MODE ?= offline
ENV_DIR := environments/$(ENV)
APP_DIR := cxas_app
EVALS_DIR := evals
CONFIG_FILE := $(if $(wildcard $(ENV_DIR)/gecx-config.json),$(ENV_DIR)/gecx-config.json,$(if $(wildcard gecx-config.json),gecx-config.json,$(ENV_DIR)/gecx-config.example.json))
PYTHON := .venv/bin/python
CXAS := .venv/bin/cxas
PYTEST := .venv/bin/pytest
RATIONALE ?= Manual deploy/eval run from Makefile

.PHONY: help check-config bundle lint diff-check test offline live trend gate deploy backfill mutants verify-ids acceptance install-hooks push pull eval ci

help:
	@echo "Totto, Mercedes F1 Fan Agent — Verification, Gate & History Suite"
	@echo "  make offline       - Run fast hermetic offline layers (<15s) and record run"
	@echo "  make gate          - Run automatic pre-commit regression gate"
	@echo "  make mutants       - Run >=10 local mutants in temp copies and verify 100% kill rate"
	@echo "  make deploy        - Run push-disabled deploy (gate + fetchable CXAS version snapshot + record)"
	@echo "  make backfill      - Backfill reproduced historical commits and imported live runs"
	@echo "  make trend         - Regenerate evals/history/{index.json,TREND.md,trend.html}"
	@echo "  make live          - Run read-only live verification against the deployed CXAS app"
	@echo "  make verify-ids    - Verify recorded platform session/version/evaluation IDs against CXAS"
	@echo "  make lint          - Run non-mutating cxas lint + bundle_shared_imports --check"
	@echo "  make test          - Run full pytest suite (offline + selftest)"
	@echo "  make acceptance    - Run offline gate + selftest + trend verification"
	@echo "  make install-hooks - Configure git core.hooksPath to hooks/ (pre-commit gate)"
	@echo "  make push          - R5 GUARDED: refuses cxas push; directs to 'make deploy'"

check-config:
	@test -f "$(CONFIG_FILE)" || (echo "Missing $(CONFIG_FILE)" && exit 1)
	@$(PYTHON) -c "import json; d=json.load(open('$(CONFIG_FILE)')); assert d.get('gcp_project_id') and d.get('app_id')"

bundle:
	$(PYTHON) scripts/bundle_shared_imports.py --check

lint: bundle
	$(CXAS) lint --app-dir $(APP_DIR)

diff-check: check-config bundle
	$(PYTHON) scripts/diff_check.py --mode offline

test:
	$(PYTEST)

offline:
	$(PYTHON) -m totto_suite offline

live:
	$(PYTHON) -m totto_suite live

trend:
	$(PYTHON) -m totto_suite trend

gate:
	$(PYTHON) -m totto_suite gate

deploy:
	$(PYTHON) -m totto_suite deploy --no-push --rationale "$(RATIONALE)"

backfill:
	$(PYTHON) -m totto_suite backfill

mutants:
	$(PYTHON) -m totto_suite mutants

verify-ids:
	$(PYTHON) -m totto_suite verify-ids

install-hooks:
	git config core.hooksPath hooks
	chmod +x hooks/pre-commit
	@echo "Installed git pre-commit hook (core.hooksPath=hooks)."

acceptance: gate trend
	$(PYTEST) tests/selftest
	$(PYTEST) tests/acceptance -v

push:
	@echo "[R5 SAFETY BLOCK] Direct 'cxas push' to the shared live CXAS app is prohibited."
	@echo "Use 'make deploy RATIONALE=\"...\"' to run the pre-commit gate and record a fetchable CXAS version snapshot with --no-push."
	@exit 2

pull:
	@echo "[R5 SAFETY BLOCK] Overwriting $(APP_DIR)/ in-place via 'cxas pull' is disabled."
	@echo "Use '$(PYTHON) -m totto_suite snapshot --label <label>' to export the live app into evals/history/snapshots/."
	@exit 2

eval: offline

ci: gate trend
