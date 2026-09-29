# Bootcamp Presentation & Live Demo Guide — Totto, Mercedes F1 Fan Agent

## 1. 5-Minute Executive Pitch (Why This Architecture Matters)

**Totto, Mercedes F1 Fan Agent** (`totto-mercedes-f1-fan-agent`) is a production-grade 4-agent conversational assistant built on **Google Cloud CX Agent Studio (CES / GECX)** for the Mercedes-AMG Petronas Formula One Team, paired with **`totto_suite`**—an automated offline + live evaluation, mutation-testing, and version-tracking pipeline.

### Key Engineering Highlights to Share
1. **4-Agent Seamless Persona (`totto_root_agent` + 3 Specialists)**:
   - Handles 2026 F1 race schedules with `zoneinfo` seasonal DST conversion (`get_race_schedule`), Mercedes-first WDC/WCC standings (`get_driver_standings`), mock merchandise order support (`lookup_mock_merch_order`), and non-transactional ticket referrals (`get_official_links`).
   - All 4tools include native **`toolFakeConfig` mock tool fakes** (`fake_tool_call`) for deterministic offline testing.
2. **Fast Hermetic Offline Gate (`313/313 PASS` in `< 12s`)**:
   - Runs 8 offline layers (`lint`, `config`, `callbacks`, `tools`, `dates`, `grader`, `regrade`, `selftest`) with zero network calls and a runtime date oracle ([`totto_suite/oracle.py`](../totto_suite/oracle.py)) that tests `"next race"` across 5 different dates in the 2026 season.
3. **Proof the Tests Catch Real Bugs (`11/11` Mutants Killed + 17 Deterministic Checks)**:
   - `totto_suite mutants` injects 11 realistic defects into temporary copies of `cxas_app/` and verifies a **100% kill rate** ([`evals/history/mutants/mutants_report.md`](../evals/history/mutants/mutants_report.md)).
   - A 17-check deterministic transcript grader overrides lenient LLM judge passes whenever an agent leaks raw code, drops a supervisor escalation call, or invents ungrounded facts ([`evals/history/regrade/regrade_report.md`](../evals/history/regrade/regrade_report.md)).
4. **Git Commit ↔ CXAS Version Traceability (`TREND.md` & `trend.html`)**:
   - Every run record ties `agent.commit` (`34b0af4`) to the exact deployed CXAS `Version` (`365b82de-16af-4acf-bfb0-8298f1c1c01e`), separates `INFRA_ERROR` (`HTTP 429` quota) from agent pass rates, and flags regressions automatically across 19 chronological points.

---

## 2. Step-by-Step Live Demo Script (10 Minutes)

### Step 1: Show the Fast Offline Suite & Pre-Commit Gate (`~12s`)
```bash
.venv/bin/python -m totto_suite gate
```
- **Talking Point**: *"In 12 seconds with zero cloud calls, `totto_suite gate` runs `cxas lint`, verifies PIF XML contracts and `toolFakeConfig` across all 4 tools, tests callbacks in 4 languages, tests timezone/DST math across 5 frozen 2026 dates, and runs 313 checks (`100% PASS`)."*

### Step 2: Prove the Tests Catch Real Bugs (`make mutants`)
```bash
.venv/bin/python -m totto_suite mutants
```
- **Talking Point**: *"How do we know our tests aren't rubber-stamping the agent? `totto_suite mutants` creates 11 broken copies of `cxas_app/` in temp folders—breaking timezone DST, order-ID regex, unknown-race error handling, and Toto Wolff non-impersonation—and kills `11/11 (100%)` of them without touching the working tree."*

### Step 3: Show How We Disagreed with External Grader False Positives (`docs/COVERAGE.md`)
- Open [`docs/COVERAGE.md`](COVERAGE.md) ("Where the Suite Disagrees with the Agent Report Card").
- **Talking Point**: *"An external report card penalized Totto (`RC-04`, `RC-05`) for refusing political questions and direct ticket sales. Our suite proves with verbatim transcripts and PRD citations (`PRD-AC4`, `PRD-AC9`) that those refusals are required product guardrails—while fixing the real escalation bug (`RC-02`) where asking for a supervisor used to call `end_session`."*

### Step 4: Show the Chronological Trend & Live CXAS Version Snapshot
- Open [`evals/history/TREND.md`](../evals/history/TREND.md) (or [`evals/history/trend.html`](../evals/history/trend.html)) and the **Evaluations** tab in CX Agent Studio (`5/5 = 100% PASS` on `evaluationRuns/a7ba2b79-737d-40b8-ba89-2062702be834`).
- **Talking Point**: *"Every point in `TREND.md` links a Git commit to a fetchable CXAS `Version` (`365b82de-16af-4acf-bfb0-8298f1c1c01e`), tracks `INFRA_ERROR` separately from agent failures, and shows the progression from `90.7%` (`283/312`) before fixes to `100.0%` (`313/313`) after fixes."*
