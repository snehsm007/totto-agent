# Inspecting Conversations, Transcripts & Cloud Snapshots (`docs/conversation_inspection.md`)

This guide explains how to inspect multi-turn conversations, understand how our **18-check deterministic transcript grader** scores agent responses, verify cloud resource IDs (`evaluationRuns/<uuid>`, `conversations/<uuid>`, and `versions/<uuid>`), and compare before/after deployment snapshots.

---

## 1. Where Conversation Transcripts & Run Records Live

All evaluation history and captured transcripts are stored in [`evals/history/`](../evals/history) and [`evals/results/`](../evals/results) so you can inspect every past test run offline:

| Path | What It Contains |
| :--- | :--- |
| [`evals/history/index.json`](../evals/history/index.json) | Master chronological index of all recorded runs (pre-CI local runs + cloud staging `ci` runs), with commit SHAs, timestamps, overall pass rates, and per-layer counts. |
| [`evals/history/runs/`](../evals/history/runs) | Schema-v1 JSON run records (`<run_id>.json`), including per-layer pass rates, gate status (`PASS`/`FAIL`/`INCONCLUSIVE`), individual check results, latencies, and scrubbed app-relative resource IDs. |
| [`evals/history/artifacts/`](../evals/history/artifacts) | Per-run detailed cloud artifacts (`evals/history/artifacts/<run_id>/`), including `verify_ids.json` and raw per-scenario evaluation outputs. |
| [`evals/history/regrade/regrade_report.md`](../evals/history/regrade/regrade_report.md) | Side-by-side re-grade report across all **6 recorded transcript files** (**101 conversations** total in [`evals/results/`](../evals/results)), comparing `scripts/analyze_transcripts.py` against our 18-check deterministic grader (`evals/history/regrade/regrade_results.json`). |
| [`evals/results/`](../evals/results) | The 6 historical multi-turn transcript JSON archives (`probes_text_20260928_183505.json`, `sims_repo_text_20260928_184131.json`, `sims_audiocheck_audio_20260928_184320.json`, `sims_baseline1831_on3flash_text_20260928_191853.json`, `goldens_3flash_text_20260928_205030.json`, and `probes_text_20260928_202346.json` in `scripts/results/`). |

---

## 2. How App-Relative Resource IDs & `verify-ids` Work

To keep Google Cloud project IDs and app UUIDs out of git while preserving a verifiable audit trail back to the cloud server, run records in [`evals/history/runs/`](../evals/history/runs) store **app-relative resource IDs** alongside an `"app_ref"` field (`"staging"` or `"live"`):

- **Stored in `evals/history/runs/<run_id>.json`**:
  - `"app_ref": "staging"` (or `"live"`)
  - `"evaluation_run": "evaluationRuns/<uuid>"`
  - `"conversation": "conversations/<uuid>"`
  - `"app_version": "<version_uuid>"` (or `"versions/<uuid>"`)

### Rehydrating and Verifying IDs Against the Cloud (`totto_suite verify-ids`)
When you (or the `staging-gate` CI job) run:
```bash
.venv/bin/python -m totto_suite verify-ids \
  --app-name "$STAGING_APP_NAME" \
  --run-id "$GATE_RUN_ID"
```
[`totto_suite/verify_ids.py`](../totto_suite/verify_ids.py) combines `--app-name` (`projects/<PROJECT>/locations/us/apps/<APP_UUID>`, or the default app from local config if `--app-name` is omitted) with each app-relative ID (`evaluationRuns/<uuid>`, `conversations/<uuid>`, `versions/<uuid>`) and queries the CXAS API to verify the resource exists on the server:
- **Cloud Live & Staging Runs (`verified`)**: Every recorded `evaluationRuns/<uuid>`, `conversations/<uuid>`, and `versions/<uuid>` is confirmed live on the server and recorded in `evals/history/artifacts/<run_id>/verify_ids.json`.
- **Pre-R5 Legacy / Offline Runs (`legacy_unverifiable`)**: Historical imported or offline runs that do not reference live cloud `evaluationRuns/<uuid>` resources are explicitly classified as `legacy_unverifiable` so the dashboard distinguishes verified cloud runs from older local captures.

> [!IMPORTANT]
> **Why `verify-ids` Must Run Immediately After `ci-gate`**: In CXAS, running `cxas push --overwrite` against the staging app replaces the staging app state. Always run `verify-ids` right after `ci-gate` (as [`.github/workflows/ci.yml`](../.github/workflows/ci.yml) does automatically) before pushing a new change to staging.

---

## 3. Regrading Captured Transcripts Offline (18 Deterministic Checks)

Every conversation turn is graded by [`totto_suite/grader/checks.py`](../totto_suite/grader/checks.py) and [`totto_suite/grader/regrade.py`](../totto_suite/grader/regrade.py) across **18 deterministic checks** (covering code leaks `TR-02`, dead-air handoffs `TR-03`, ungrounded race/order facts `TR-01`, internal agent name leaks `TR-05`, language drift `TR-04`, Toto Wolff impersonation `AC-8`, rival insults `AC-9`, PCI credit card echoes `NEW-3`, past-race tense `TB-5`, data freshness disclosures `TR-09`, repetitive boilerplate mantras/self-introductions `NEW-2`/`RC-06`, and official ticketing/merch links `AC-4`/`RC-01`).

In [`totto_suite/grader/combine.py`](../totto_suite/grader/combine.py), these deterministic checks act as a **hard gate over the LLM judge**: even if the platform's LLM judge marks an expectation as `PASS`, any deterministic failure overrides the turn status to `FAIL`.

### Commands to Run the Offline Grader & Transcript Analyzer
```bash
# 1. Run all 8 offline verification layers (421 checks, including 'grader' and 'regrade' across all 101 transcripts)
.venv/bin/python -m totto_suite offline --no-record

# 2. Run ONLY the fast pytest unit tests for the 18-check grader and 101-transcript regrade layer
.venv/bin/pytest tests/grader tests/regrade -q

# 3. Print a human-readable diagnostic summary of a specific transcript archive file
.venv/bin/python scripts/analyze_transcripts.py evals/results/sims_repo_text_20260928_184131.json
```

---

## 4. Inspecting Cloud Deployment Snapshots (`evals/history/snapshots/`)

Whenever [`scripts/ci/deploy_live.py`](../scripts/ci/deploy_live.py) deploys to the Live App (or when you run `python -m totto_suite snapshot --label <label>`), it saves structured point-in-time snapshots under [`evals/history/snapshots/`](../evals/history/snapshots):

### Snapshot Directories & Audit Files
- **Baseline Pre-Work Live State (`20260928T215748Z_live_before`)**:
  - [`evals/history/snapshots/20260928T215748Z_live_before/inventory.json`](../evals/history/snapshots/20260928T215748Z_live_before/inventory.json) — Complete pre-remediation agent, tool, and callback inventory captured from the cloud app before our fixes.
  - [`evals/history/snapshots/20260928T215748Z_live_before/version.json`](../evals/history/snapshots/20260928T215748Z_live_before/version.json) — Version metadata (`b11332a0-b304-41e1-baac-57cd0ced05da`) at baseline capture time.
  - [`evals/history/snapshots/20260928T215748Z_live_before/diff_vs_commits.md`](../evals/history/snapshots/20260928T215748Z_live_before/diff_vs_commits.md) — Detailed audit comparing the pre-work cloud app against repository commits.
- **Post-Audit Snapshot (`20260929T010751Z_live_after`)**:
  - [`evals/history/snapshots/20260929T010751Z_live_after/inventory.json`](../evals/history/snapshots/20260929T010751Z_live_after/inventory.json) — Cloud inventory proving zero unrecorded changes during the baseline audit (`version.json`: [`evals/history/snapshots/20260929T010751Z_live_after/version.json`](../evals/history/snapshots/20260929T010751Z_live_after/version.json)).
  - [`evals/history/snapshots/before_after_diff.md`](../evals/history/snapshots/before_after_diff.md) — Cryptographic SHA-256 comparison of `live_before` vs `live_after`.
- **Remediated Live State (`20260929T150532Z_live_fixed`)**:
  - [`evals/history/snapshots/20260929T150532Z_live_fixed/inventory.json`](../evals/history/snapshots/20260929T150532Z_live_fixed/inventory.json) — Remediated cloud app inventory (`4` agents, `4` tools with `toolFakeConfig`).
  - [`evals/history/snapshots/20260929T150532Z_live_fixed/version.json`](../evals/history/snapshots/20260929T150532Z_live_fixed/version.json) — Immutable cloud version record (`e2d87687-f844-48ba-959d-dc7ef43a813c`).
  - [`evals/history/snapshots/20260929T150532Z_live_fixed/diff_vs_commits.md`](../evals/history/snapshots/20260929T150532Z_live_fixed/diff_vs_commits.md) — Verification diff confirming zero drift between git and the deployed cloud app.
