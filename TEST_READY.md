# TEST_READY: Totto, Mercedes F1 Fan Agent (`totto-mercedes-f1-fan-agent`)

## 1. Status Summary
- **Lint Status (`.venv/bin/cxas lint`)**: **PASSED** (`0 errors, 0 warnings`)
- **Pytest Suite (`.venv/bin/pytest`)**: **PASSED** (`31/31` tests in `< 0.5s`)
- **Multi-Layer Evaluation Suite (`scripts/local_eval_runner.py`)**: **PASSED** (`42/42` = **100.0%** across Tool Tests `8/8`, Public Evals `18/18`, and 4-Bucket Secret Holdout `16/16`)
- **3-Iteration Hill-Climbing Trajectory (`results.tsv` & `experiment_log.md`)**:
  - **Iteration 1 (`[BASELINE]`)**: `26/42 (61.9%)` — Initial 4-agent scaffold & 4 Python tools (`evals/results/iteration-1.md`)
  - **Iteration 2 (`[KEPT]`)**: `42/42 (100.0%)` — Full PIF instructions, timezone clarification gate, rival-respect & PCI guardrails, damaged-item flows, and cross-agent topic-switch routing (`evals/results/iteration-2.md` + automated Git commit)
  - **Iteration 3 (`[REVERTED]`)**: `34/42 (81.0%)` -> Auto-reverted to `100.0%` via `--auto-revert` after simulated prompt compaction removed Toto Wolff non-impersonation and mock-order disclosure rules (`evals/results/iteration-3.md`)

## 2. Verification Commands

```bash
# 1. Lint GECX application (0 errors, 0 warnings)
.venv/bin/cxas lint

# 2. Run deterministic unit & contract tests (< 1s)
.venv/bin/pytest -v

# 3. Verify shared prompt synchronization
.venv/bin/python scripts/bundle_shared_imports.py --check

# 4. Run full 3-layer evaluation runner (Tool Tests + Public Evals + 4-Bucket Secret Holdout)
.venv/bin/python scripts/local_eval_runner.py
```
