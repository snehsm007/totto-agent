"""Deterministic transcript grader (M2b).

    from totto_suite import grader
    conv = grader.from_sim_row(row)                    # or any adapter
    det = grader.grade(conv, {"now": "2026-09-28T18:41:31Z", "voice": False,
                              "expected_language": "auto"})
    status = grader.combine(det, grader.judge_from_row(row), row_error=row.get("error"))

See checks.CATALOGUE for every check, the finding IDs it covers and its rule.
"""

from totto_suite.grader.adapters import (
    from_conversation_history,
    from_harness_probes,
    from_harness_sims,
    from_probe_row,
    from_scrapi_sim_result,
    from_scrapi_sim_results,
    from_sim_row,
    load_conversations,
    parse_blocks,
    turns_from_trace,
)
from totto_suite.grader.checks import CATALOGUE, DEFAULT_THRESHOLDS, failing, grade
from totto_suite.grader.combine import (
    FAIL,
    INFRA_ERROR,
    PASS,
    SKIPPED,
    combine,
    infra_kind,
    judge_from_row,
)

__all__ = [
    "CATALOGUE",
    "DEFAULT_THRESHOLDS",
    "FAIL",
    "INFRA_ERROR",
    "PASS",
    "SKIPPED",
    "combine",
    "failing",
    "from_conversation_history",
    "from_harness_probes",
    "from_harness_sims",
    "from_probe_row",
    "from_scrapi_sim_result",
    "from_scrapi_sim_results",
    "from_sim_row",
    "grade",
    "infra_kind",
    "judge_from_row",
    "load_conversations",
    "parse_blocks",
    "turns_from_trace",
]
