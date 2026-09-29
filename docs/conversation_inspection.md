# Live Session Diagnostics, Transcript Re-Grading & Platform ID Verification

## 1. Verifying Live CXAS Platform Resource IDs (`verify-ids`)

Every live evaluation run (`totto_suite live`) records platform resource IDs (`app_version`, `tools`, `evaluations`, `evaluation_runs`, `evaluation_results`, `conversations`) inside [`evals/history/runs/`](../evals/history/runs). You can independently verify that every recorded ID resolves on the live Google Cloud CES API:

```bash
# Verify all platform resource IDs in the latest live run against the CXAS API
.venv/bin/python -m totto_suite verify-ids

# Or via Makefile:
make verify-ids
```

See [`evals/history/artifacts/20260929T001319Z_live_fd9be8b/verify_ids.json`](../evals/history/artifacts/20260929T001319Z_live_fd9be8b/verify_ids.json) (`202/202` unique CXAS resources verified across `111` test entries).

---

## 2. Inspecting & Re-Grading Recorded Conversation Transcripts

`totto_suite` includes two transcript inspection and diagnostic tools:

1. **17-Check Deterministic Grader & Re-Grader ([`totto_suite/grader/`](../totto_suite/grader/__init__.py))**:
   - Inspects multi-turn simulator and live transcripts for dead-air handoffs (`TR-03`), spoken raw code leaks (`TR-02`), ungrounded race/order facts (`TR-01`), internal agent name leaks (`TR-05`), language drift (`TR-04`), abrupt `end_session` calls on supervisor requests (`RC-02` / `RC-10`), and voice TTS markdown/emoji artifacts (`RC-06` / `RC-07`).
   - Run the offline re-grader across all 6 historical transcript files (`101` transcripts):
     ```bash
     .venv/bin/python -m totto_suite offline --layer regrade --no-record
     ```
   - Full side-by-side comparison report: [`evals/history/regrade/regrade_report.md`](../evals/history/regrade/regrade_report.md).

2. **Reference Transcript Analyzer ([`scripts/analyze_transcripts.py`](../scripts/analyze_transcripts.py))**:
   ```bash
   .venv/bin/python scripts/analyze_transcripts.py
   ```

---

## 3. Comparing Live CXAS App Snapshots (`totto_suite snapshot`)

To capture an immutable export of the live CXAS app, create a fetchable CXAS `Version`, and diff every agent, tool, callback, and instruction file against your Git commit history:

```bash
.venv/bin/python -m totto_suite snapshot --label <label>
```

- Pre-work baseline snapshot (`b11332a0-b304-41e1-baac-57cd0ced05da`): [`evals/history/snapshots/20260928T215748Z_live_before/`](../evals/history/snapshots/20260928T215748Z_live_before/manifest.json)
- Post-fix deployed snapshot (`365b82de-16af-4acf-bfb0-8298f1c1c01e`): [`evals/history/snapshots/20260929T150532Z_live_fixed/`](../evals/history/snapshots/20260929T150532Z_live_fixed/manifest.json)
- Cryptographic SHA-256 diff report: [`evals/history/snapshots/before_after_diff.md`](../evals/history/snapshots/before_after_diff.md)
