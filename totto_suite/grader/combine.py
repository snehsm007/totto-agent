"""combine(deterministic, judge) -> status (plan.md decision D3).

    row infra error (429/quota, 5xx, deadline/timeout, auth, network, bidi)
        -> INFRA_ERROR (never PASS/FAIL)
    deterministic FAIL                       -> FAIL (no judge can override it)
    deterministic PASS + judge FAIL          -> FAIL
    deterministic PASS + judge error, or no judge verdict while expectations
        exist                                -> INFRA_ERROR
    deterministic PASS + judge PASS / no judge needed -> PASS
"""

from __future__ import annotations

import re
from typing import Any

PASS = "PASS"
FAIL = "FAIL"
INFRA_ERROR = "INFRA_ERROR"
SKIPPED = "SKIPPED"

_INFRA_KINDS = [
    ("quota", re.compile(r"\b429\b|RESOURCE[_ ]EXHAUSTED|ResourceExhausted|quota|rate.?limit", re.I)),
    ("deadline", re.compile(r"DEADLINE_EXCEEDED|DeadlineExceeded|timed? ?out|timeout|\b504\b", re.I)),
    ("server", re.compile(r"\b5\d\d\b|UNAVAILABLE|ServiceUnavailable|InternalServerError|\bINTERNAL\b|BadGateway", re.I)),
    ("auth", re.compile(r"\b401\b|\b403\b|UNAUTHENTICATED|PERMISSION_DENIED|PermissionDenied|credential|reauth", re.I)),
    ("network", re.compile(r"ConnectionError|Connection (?:reset|refused|aborted)|socket|SSL|DNS|getaddrinfo|network", re.I)),
    ("bidi", re.compile(r"BidiSession\w*|websocket", re.I)),
    ("judge", re.compile(r"judge|evaluate_expectations|json.?decode|empty (?:judge|response)", re.I)),
]


def infra_kind(error: Any) -> str | None:
    """Kind of infrastructure error in an error string (None if no error).

    Any error recorded on a result row means the conversation did not run to
    completion, so it can't be an agent PASS/FAIL; unknown texts are 'other'."""
    if error in (None, "", False):
        return None
    text = str(error)
    for kind, rx in _INFRA_KINDS:
        if rx.search(text):
            return kind
    return "other"


def judge_from_row(row: dict[str, Any], *, expected_expectations: int | None = None) -> dict[str, Any] | None:
    """Judge verdict recorded on a harness/SCRAPI result row.

    SCRAPI drops expectations whose judge call raised, so fewer expectation
    results than defined (``expected_expectations``) is a judge error."""
    if not isinstance(row, dict):
        return None
    details = row.get("expectation_details") or []
    steps = row.get("step_details") or []
    if expected_expectations is None:
        m = re.match(r"^\s*\d+\s*/\s*(\d+)\s*$", str(row.get("expectations") or ""))
        expected_expectations = int(m.group(1)) if m else None
    error = None
    if expected_expectations is not None and len(details) < expected_expectations:
        error = f"judge returned {len(details)} of {expected_expectations} expectation results"
    if "passed" not in row and not details and not steps:
        return None
    passed = row.get("passed")
    if passed is None and not error:
        error = "empty judge output"
    return {
        "passed": None if error else bool(passed),
        "error": error,
        "expectations": len(details),
        "not_met": [d.get("expectation") for d in details if d.get("status") not in ("Met", "MET", "met")],
    }


def combine(
    deterministic: dict[str, Any] | None,
    judge: dict[str, Any] | None,
    *,
    row_error: Any = None,
    expectations_exist: bool | None = None,
) -> str:
    """Overall status per D3 (see module docstring)."""
    if infra_kind(row_error):
        return INFRA_ERROR
    det_failed = deterministic is not None and not deterministic.get("passed", False)
    if det_failed:
        return FAIL  # deterministic FAIL wins over any judge verdict or judge error
    judge = judge or None
    if expectations_exist is None:
        expectations_exist = judge is not None
    if judge is not None and judge.get("error"):
        return INFRA_ERROR
    verdict = judge.get("passed") if judge is not None else None
    if verdict is False:
        return FAIL
    if verdict is None and expectations_exist:
        return INFRA_ERROR  # the judge had work to do and produced nothing
    if deterministic is None and verdict is None:
        return SKIPPED
    return PASS
