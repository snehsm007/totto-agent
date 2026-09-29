# Makefile for Totto, Mercedes F1 Fan Agent (totto-mercedes-f1-fan-agent)
# Thin wrapper around `python -m totto_suite <command>` and scripts/ci/*.
# The LIVE CXAS app is changed only by the gated `deploy-live` job in
# .github/workflows/ci.yml (main branch, after the staging eval gate passes),
# so there is deliberately no target that pushes to live.

ENV ?= dev-totto-gecx
MODE ?= offline
ENV_DIR := environments/$(ENV)
APP_DIR := cxas_app
EVALS_DIR := evals
CONFIG_FILE := $(if $(wildcard $(ENV_DIR)/gecx-config.json),$(ENV_DIR)/gecx-config.json,$(if $(wildcard gecx-config.json),gecx-config.json,$(ENV_DIR)/gecx-config.example.json))
PYTHON := .venv/bin/python
CXAS := .venv/bin/cxas
PYTEST := .venv/bin/pytest
# Interpreter used to create .venv when uv is not installed (needs >= 3.11).
BOOTSTRAP_PYTHON ?= python3

.PHONY: help setup hooks install-hooks check-config bundle lint diff-check test offline live trend gate backfill mutants verify-ids acceptance push-staging eval ci ci-offline

help:
	@echo "Totto, Mercedes F1 Fan Agent — Verification, Gate & History Suite"
	@echo "  make setup         - Create .venv, install deps (pip install -e .), activate the pre-commit gate"
	@echo "  make hooks         - Activate the pre-commit gate only (git config core.hooksPath hooks)"
	@echo "  make offline       - Run fast hermetic offline layers (<15s) and record run"
	@echo "  make gate          - Run automatic pre-commit regression gate"
	@echo "  make mutants       - Run >=10 local mutants in temp copies and verify 100% kill rate"
	@echo "  make ci-offline    - Same checks as the CI 'offline' job (bundle, lint, pytest, offline, mutants)"
	@echo "  make push-staging  - Push cxas_app to the STAGING CXAS app (never live)"
	@echo "  make backfill      - Backfill reproduced historical commits and imported live runs"
	@echo "  make trend         - Regenerate evals/history/{index.json,TREND.md,trend.html}"
	@echo "  make live          - Run live verification against the deployed CXAS app"
	@echo "  make verify-ids    - Verify recorded platform session/version/evaluation IDs against CXAS"
	@echo "  make lint          - Run non-mutating cxas lint + bundle_shared_imports --check"
	@echo "  make test          - Run full pytest suite (offline + selftest + ci)"
	@echo "  make acceptance    - Run offline gate + selftest + trend verification"

# One command after a fresh clone: venv + deps + pre-commit gate.
setup:
	@if command -v uv >/dev/null 2>&1; then \
	  [ -x "$(PYTHON)" ] || uv venv .venv; \
	  uv pip install --python "$(PYTHON)" -e .; \
	else \
	  [ -x "$(PYTHON)" ] || $(BOOTSTRAP_PYTHON) -m venv .venv; \
	  "$(PYTHON)" -m pip install --upgrade pip && "$(PYTHON)" -m pip install -e .; \
	fi
	@$(MAKE) --no-print-directory hooks
	@echo "Setup complete: .venv ready ($$($(PYTHON) --version)), cxas CLI at $(CXAS)."

# Git cannot enable hooks on clone, so setup does it explicitly.
hooks:
	git config core.hooksPath hooks
	chmod +x hooks/*
	@echo "Pre-commit gate active: core.hooksPath=$$(git config --get core.hooksPath)"

install-hooks: hooks

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

backfill:
	$(PYTHON) -m totto_suite backfill

mutants:
	$(PYTHON) -m totto_suite mutants

verify-ids:
	$(PYTHON) -m totto_suite verify-ids

acceptance: gate trend
	$(PYTEST) tests/selftest
	$(PYTEST) tests/acceptance -v

# Staging only (refuses unless the target app's name ends with -staging).
push-staging:
	$(PYTHON) scripts/ci/push_app.py --target staging

eval: offline

# The same steps, in the same order, as the CI `offline` job.
ci-offline: lint
	$(PYTEST) -q
	$(PYTHON) -m totto_suite offline --no-record
	$(PYTHON) -m totto_suite mutants

ci: ci-offline
