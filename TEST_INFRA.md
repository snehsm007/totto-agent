# Test Infrastructure Specification (`TEST_INFRA.md`)

## Overview
This document defines the multi-layer verification and testing infrastructure for **Totto, the Mercedes F1 Fan Agent** (`totto-mercedes-f1-fan-agent`).

## Verification Layers

### Layer 1: Static CXAS Linter & Protobuf Schema Gate (`cxas lint`)
- **Command**: `.venv/bin/cxas lint` (or `make lint`)
- **Scope**:
  - Instruction PIF XML structure (`I001`–`I016`): `<role>`, `<persona>`, `<constraints>`, `<taskflow>`, `<subtask>`, `<step>`, `<examples>`, `{current_date}`, valid `{@AGENT: ...}` and `{@TOOL: ...}` references, and zero banned XML tags (`<context>`, `<state>`, etc.).
  - Python Tool contracts (`T001`–`T014`): `"agent_action"` error recovery keys, docstrings, type annotations, non-`None` defaults, no `**kwargs`, and `snake_case` naming.
  - App, Agent, and Tool Protobuf schemas (`A001`–`A006`, `S002`–`S008`, `V001`–`V007`, `V100`–`V104`).
  - Evaluation YAML schemas (`E001`–`E012`) across `evals/tool_tests/`, `evals/goldens/`, `evals/simulations/`, and `evals/secret_holdout/`.
- **Pass Criterion**: `0 errors, 0 warnings`.

### Layer 2: Deterministic Unit, Contract & Static Prompt Suite (`pytest`)
- **Command**: `.venv/bin/pytest` (or `make test`)
- **Test Files**:
  - `tests/test_tools.py`: Direct unit and boundary tests for `get_race_schedule`, `get_driver_standings`, `lookup_mock_merch_order` (`1001`, `1002`, `1003`, `9999`, empty, prefixed), and `get_official_links`.
  - `tests/test_agent_instructions_and_contracts.py`: Verifies PIF XML tags, `{current_date}`, `@AGENT` and `@TOOL` bidirectional sync, variable declarations, YAML evaluation schemas, coverage of all 9 PRD acceptance criteria, and >=12 scenarios across the 4 secret holdout buckets.
  - `tests/test_hill_climb_harness.py`: Verifies `bundle_shared_imports.py`, `diff_check.py`, `local_eval_runner.py`, and `hill_climb.py` regression detection and auto-revert logic.
- **Pass Criterion**: 100% pass rate (exit code 0) in `< 5 seconds`.

### Layer 3: Multi-Layer Conversational Evaluations (`evals/`)
- **Public Evals**:
  - `evals/tool_tests/totto_tool_tests.yaml`: Deterministic CXAS YAML tool tests.
  - `evals/goldens/totto_goldens.yaml`: Multi-turn golden conversations covering all 9 official PRD acceptance criteria.
  - `evals/simulations/totto_simulations.yaml`: Multi-turn user simulations covering all 9 official PRD acceptance criteria.
- **4-Bucket Secret Holdout Evals**:
  - `evals/secret_holdout/totto_secret_holdout.yaml`: 16 multi-turn robustness scenarios (4 per bucket) across:
    1. `happy_path` (Happy Path Variations)
    2. `edge_ambiguous` (Ambiguous / Multi-Intent Edge Cases)
    3. `adversarial_brand_safety` (Adversarial & Brand-Safety Traps)
    4. `out_of_scope_guardrails` (Out-of-Scope & Policy Guardrails)

### Layer 4: Automated Hill-Climbing & Auto-Revert Pipeline (`scripts/hill_climb.py`)
- **Command**: `.venv/bin/python scripts/hill_climb.py --iteration <N> --message "<rationale>" [--auto-revert] [--only-failing]`
- **Outputs**:
  - `evals/results/iteration-1.md`, `evals/results/iteration-2.md`, `evals/results/iteration-3.md`
  - `evals/results/dashboard.html`
  - `release-notes.md`
  - `experiment_log.md`
  - `results.tsv`
