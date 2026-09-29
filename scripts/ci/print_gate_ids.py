#!/usr/bin/env python3
"""Print the gate's CXAS platform IDs (app-relative) as a Markdown table.

Usage: python scripts/ci/print_gate_ids.py gate_summary.json

Used by the CI "Platform IDs (app-relative)" step so the public run log and
job summary show real ``evaluationRuns/<uuid>`` / ``sessions/<uuid>`` IDs from
the staging app without project or app IDs. Full resource names, if any slip
into the summary, are shortened to their app-relative part.
"""

from __future__ import annotations

import json
from pathlib import Path
import re
import sys

_FULL = re.compile(r"projects/[^/\s]+/locations/[^/\s]+/apps/[^/\s]+/")


def app_relative(value: str) -> str:
    return _FULL.sub("", value)


def _flatten(ids) -> list[str]:
    if isinstance(ids, dict):
        out = []
        for key, val in ids.items():
            for item in _flatten(val):
                out.append(item if "/" in item else f"{key}={item}")
        return out
    if isinstance(ids, (list, tuple)):
        return [x for v in ids for x in _flatten(v)]
    if ids in (None, ""):
        return []
    return [app_relative(str(ids))]


def render(summary: dict) -> str:
    lines = [
        f"### CXAS eval gate: {summary.get('verdict', '?')}",
        "",
        f"- commit `{str(summary.get('commit', ''))[:7]}`, run id `{summary.get('run_id', '')}`,"
        f" tool mode `{summary.get('tool_mode', '')}`, fake verified `{summary.get('fake_verified')}`",
        f"- pass rate {summary.get('pass_rate')} (baseline {summary.get('baseline_pass_rate')})",
    ]
    for reason in summary.get("reasons") or []:
        lines.append(f"- {reason}")
    lines += ["", "| test | layer | status | tool mode | platform IDs (app-relative) |", "|---|---|---|---|---|"]
    count = 0
    for test in summary.get("tests") or []:
        ids = sorted(set(_flatten(test.get("platform_ids"))))
        count += len(ids)
        lines.append(
            f"| {test.get('id', '')} | {test.get('layer', '')} | {test.get('status', '')} |"
            f" {test.get('tool_mode', '')} | {'<br>'.join(ids)} |"
        )
    lines += ["", f"{count} platform IDs recorded."]
    return "\n".join(lines) + "\n"


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(__doc__, file=sys.stderr)
        return 2
    summary = json.loads(Path(argv[1]).read_text(encoding="utf-8"))
    sys.stdout.write(render(summary))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
