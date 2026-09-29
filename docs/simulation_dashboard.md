# Simulation & Evaluation Trend Dashboard (`TREND.md` & `trend.html`)

## 1. Overview

Every run of `totto_suite` (`reproduced`, `imported`, `snapshot`, `offline`, `deploy`, `live`) writes a schema-v1 JSON record into [`evals/history/runs/`](../evals/history/runs) and regenerates three synchronized views:

1. **[`evals/history/index.json`](../evals/history/index.json)**: Machine-readable index of all 19 chronological points (`point_time`-ordered) and all detected `[REGRESSION]` flags.
2. **[`evals/history/TREND.md`](../evals/history/TREND.md)**: Markdown timeline showing per-layer pass rates (`P/(P+F)`), `INFRA_ERROR` counts, flakiness (`k/N`), git commits, CXAS version IDs, and regression deltas.
3. **[`evals/history/trend.html`](../evals/history/trend.html)**: Self-contained HTML dashboard with interactive tables and visual pass-rate badges.

---

## 2. Regenerating & Viewing the Dashboard

```bash
# Regenerate index.json, TREND.md, and trend.html from evals/history/runs/
.venv/bin/python -m totto_suite trend

# Or via Makefile:
make trend
```

---

## 3. How Scoring & Regression Detection Work

- **Quota-Safe Layer Score Formula**:
  $$\text{Layer Score} = \frac{\text{PASS}}{\text{PASS} + \text{FAIL}}$$
  Platform/infrastructure errors (`HTTP 429 RESOURCE_EXHAUSTED`, `503`, `504`, socket timeouts) are recorded in `infra_errors` and excluded from the denominator so quota exhaustion never distorts agent quality trends.
- **Hard Deterministic Gate over LLM Judge**:
  In [`totto_suite/grader/`](../totto_suite/grader/__init__.py), 17 deterministic transcript checks (`code_leak`, `dead_air_handoff`, `race_facts_without_tool`, `merch_facts_without_tool`, `agent_name_leak`, `toto_impersonation`, `tts_hostile_formatting`, `abrupt_escalation_drop`, `credit_card_echo`, etc.) run on every conversation transcript. Any deterministic failure forces `status="FAIL"` even if the LLM judge returned `passed=True` (verified in [`evals/history/regrade/regrade_report.md`](../evals/history/regrade/regrade_report.md)).
- **Automatic `[REGRESSION]` Flagging**:
  [`totto_suite/trend.py`](../totto_suite/trend.py) compares each run against the previous comparable run and flags any layer score drop, `PASS -> FAIL` scenario flip, or newly flaky (`0 < pass_count < repeats`) scenario.
