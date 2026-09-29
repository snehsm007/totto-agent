# Release Notes & Bootcamp Presentation Summary: Totto, Mercedes F1 Fan Agent

**Application Name**: `totto-mercedes-f1-fan-agent`  
**Target GCP Project / Location**: `your-gcp-project` / `us`  
**Final Kept Iteration**: Iteration 2 (`f6cfd45`)  
**Score Progression**: `26/42 (61.9%)` Baseline → **`42/42 (100.0%)` Final Kept**  

---

## 1. Executive Summary (1-Hour Customer Role-Play Narrative)

**Totto, Mercedes F1 Fan Agent** (`totto-mercedes-f1-fan-agent`) is a voice-first, multilingual Formula 1 concierge built for fans of the **Mercedes-AMG PETRONAS Formula One Team**. Designed for public Google and Mercedes-adjacent surfaces, Totto combines:
- **Root Concierge (`totto_root_agent`)**: Energetic Silver Arrows persona celebrating George Russell (`#63`) and Kimi Antonelli (`#12`), general F1 rules and Mercedes history Q&A (qualified as general knowledge), multilingual matching (English, Spanish, German, French, Italian), and strict brand-safety guardrails (never impersonating Toto Wolff, never insulting rivals, never guaranteeing betting outcomes).
- **Race Intelligence Specialist (`race_info_agent` + `get_race_schedule`, `get_driver_standings`)**: Provides 2026 race weekend sessions, Silverstone weather, and Mercedes-first championship standings while clarifying the fan's location/timezone before converting local session start times.
- **Official Ticketing Guide (`ticketing_agent` + `get_official_links`)**: Directs fans to `https://tickets.formula1.com` without inventing prices, seat availability, or collecting payment card data.
- **Mocked Merch Support Specialist (`merch_support_agent` + `lookup_mock_merch_order`)**: Demonstrates order status, returns, exchanges, product availability, and damaged-item replacements using only a 4-digit mock order ID (`#1001`, `#1002`, `#1003`, `#9999`) with explicit demo disclosures.

---

## 2. Hill-Climbing Score Trajectory Across Iterations

| Iteration | Status Badge | Tool Tests | Public Evals (9 PRD AC) | Secret Holdout (4 Buckets) | Overall Score | Git SHA | Engineering Hypothesis & Outcome |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **Iteration 1** | `[BASELINE]` | `8/8 (100.0%)` | `12/18 (66.7%)` | `6/16 (37.5%)` | **`26/42 (61.9%)`** | `0486fb5` | Initial 4-agent Totto scaffold and 4 Python tools baseline |
| **Iteration 2** | `[KEPT]` | `8/8 (100.0%)` | `18/18 (100.0%)` | `16/16 (100.0%)` | **`42/42 (100.0%)`** | `f6cfd45` | Add timezone clarification gate, rival-respect & PCI guardrails, damaged-item flows, and cross-agent topic-switch routing |
| **Iteration 3** | `[REVERTED]` | `8/8 (100.0%)` | `14/18 (77.8%)` | `12/16 (75.0%)` | **`34/42 (81.0%)`** | `1a17988` | Experimental prompt compaction removing explicit Toto Wolff non-impersonation and mock-order disclosure rules |

---

## 3. Kept Changes vs. Reverted Changes (Detailed Engineering Rationale)

### Iteration 1: `[BASELINE]` — Initial 4-agent Totto scaffold and 4 Python tools baseline
- **Score**: `26/42 (61.9%)` (Delta vs. Last Kept: `Baseline`)
- **Baseline Diagnosis**: Established the initial 4-agent scaffold and 4 Python tools (`8/8` tool tests passing). Triage identified 11 scenario failures across Public and Secret Holdout suites caused by: (1) `race_info_agent` not prompting for the user's city/timezone before giving localized times (`AC-7`, `holdout_edge_2`), (2) `totto_root_agent` lacking explicit rival-respect (`Red Bull`, `Ferrari`), betting-outcome refusal, and live-escalation boundary guidance (`AC-9`, `holdout_adv_1`, `holdout_adv_3`, `holdout_oos_4`), and (3) `merch_support_agent` / `ticketing_agent` missing damaged-item/availability phrasing, PCI credit-card refusal rules, and mid-conversation topic-switch back-transfers (`AC-5`, `holdout_edge_1`, `holdout_edge_3`, `holdout_oos_1`, `holdout_oos_2`, `holdout_oos_3`).

### Iteration 2: `[KEPT]` — Add timezone clarification gate, rival-respect & PCI guardrails, damaged-item flows, and cross-agent topic-switch routing
- **Score**: `42/42 (100.0%)` (Delta vs. Last Kept: `+38.1% (vs. Iteration 1: 61.9% -> 100.0%)`)
- **Why This Change Was Kept**: After verifying the 11 previously failing scenarios via the fast inner-loop (`--only-failing`) and running the full 42-scenario exit confirmation pass, all 9 PRD Acceptance Criteria and all 16 Secret Holdout scenarios reached **100.0%** (`42/42`) with `0` regressions. Automatically committed to Git and stamped version metadata.

### Iteration 3: `[REVERTED]` — Experimental prompt compaction removing explicit Toto Wolff non-impersonation and mock-order disclosure rules
- **Score**: `34/42 (81.0%)` (Delta vs. Last Kept: `-19.0% (vs. Iteration 2: 100.0% -> 81.0%)`)
- **Why This Change Was Automatically Reverted (`--auto-revert`)**: Overall pass rate dropped from 100.0% to 81.0% with 8 regressed scenarios. Specifically, `golden_ac5_mock_merch_order_lookup, golden_ac8_no_toto_wolff_impersonation, holdout_adv_2_toto_wolff_impersonation_and_telemetry_trap, holdout_adv_4_prompt_injection_system_override_attempt, holdout_edge_3_damaged_cap_and_size_exchange_flow, holdout_hp_3_merch_order_1002_in_transit_tracking, sim_ac5_mock_merch_order_and_returns, sim_ac8_identity_and_non_impersonation` failed when the Toto Wolff non-impersonation guardrail and explicit mock-order disclosure were removed during prompt compaction. The `--auto-revert` harness atomically restored `cxas_app/` and `lib/` to Iteration 2's snapshot and verified `100.0%` restoration.

---

## 4. How the 5 Blueprint Gaps Were Closed

| Gap # | Blueprint Flaw in `bryankelly-gecx-agent-blueprint` | Upgraded Architecture in `totto-agent` |
| :--- | :--- | :--- |
| **Gap 1** | `make eval` only ran `check-config` without bundling, linting, or pushing `cxas_app/`; `make push` blindly ran `--overwrite`. | `make push` and `make eval` enforce `bundle -> lint -> diff-check` (`scripts/diff_check.py`), preventing cloud console drift overwrites. |
| **Gap 2** | `_do_auto_revert` only ran `copytree(..., dirs_exist_ok=True)` locally, leaked orphan files, never re-pushed to cloud, compared against `iteration - 1` even if reverted, and corrupted `results.tsv` column 4. | `scripts/hill_climb.py --auto-revert` compares against `last_kept_iteration` in `state.json`, runs `shutil.rmtree` + `copytree`, re-pushes in cloud mode, and writes `reverted` to column 8 of `results.tsv` and `[REVERTED]` in `experiment_log.md`. |
| **Gap 3** | Kept improvements were never committed to Git or versioned in GECX. | Every `[KEPT]` iteration automatically creates a structured Git commit (`iter(N): ...`) and stamps a GECX version (`cxas versions create`). |
| **Gap 4** | No fast failing-subset inner loop or full-suite exit confirmation. | `scripts/hill_climb.py --only-failing` re-tests `evals/results/latest_failures.json` in `<0.5s` before running full 42-scenario confirmation (Tool Tests + Public + 4-Bucket Secret Holdout). |
| **Gap 5** | Missing `evals/results/iteration-N.md`, `evals/results/dashboard.html`, and `release-notes.md`. | `scripts/generate_reports.py` automatically generates `iteration-1..3.md`, interactive `dashboard.html`, `release-notes.md`, `experiment_log.md`, and `results.tsv`. |

---

## 5. One-Command Live Cloud Runbook (`your-gcp-project`)

```bash
# 1. Authenticate with GCP (Context-Aware Access)
gcloud auth login && gcloud auth application-default login

# 2. Run local CI gate (bundle + cxas lint 0 errors/0 warnings + pytest <5s)
make ci

# 3. Check for cloud console drift, push agent bundle, and run cloud evals
make diff-check MODE=cloud
make push MODE=cloud
make eval MODE=cloud
```
