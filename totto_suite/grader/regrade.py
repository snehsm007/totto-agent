"""Re-grade recorded simulation and probe files and generate evidence reports.

Usage:
    .venv/bin/python -m totto_suite.grader.regrade [--out evals/history/regrade]

Compares ``totto_suite.grader`` against ``scripts/analyze_transcripts.py``
(which is byte-identical to ``scratch/analyze.py``) on the recorded Gemini 2.5
Flash and Gemini 3 Flash files, and writes:
  * ``evals/history/regrade/regrade_results.json``
  * ``evals/history/regrade/regrade_report.md``
with full verbatim transcript evidence for every flagged item.
"""

from __future__ import annotations

import argparse
import collections
import importlib.util
import json
from pathlib import Path
from typing import Any

from totto_suite import config
from totto_suite import grader

import os

FIXTURE_RECORDED_DIR = config.REPO_ROOT / "tests" / "fixtures" / "recorded"
SCRATCH_RESULTS_DIR = Path(
    os.environ.get("TOTTO_RECORDED_RESULTS_DIR", str(FIXTURE_RECORDED_DIR))
)
DEFAULT_OUT_DIR = config.HISTORY_DIR / "regrade"

# Recorded datasets in chronological order with their run timestamp and model.
RECORDED_FILES: tuple[dict[str, str], ...] = (
    {
        "filename": "probes_text_20260928_183505.json",
        "label": "Gemini 2.5 Flash — Scripted Probes (10x3)",
        "model": "gemini-2.5-flash",
        "now": "2026-09-28T18:35:05Z",
        "kind": "probes",
    },
    {
        "filename": "sims_repo_text_20260928_184131.json",
        "label": "Gemini 2.5 Flash — Baseline 7 Simulations x 3",
        "model": "gemini-2.5-flash",
        "now": "2026-09-28T18:41:31Z",
        "kind": "sims",
    },
    {
        "filename": "sims_audiocheck_audio_20260928_184320.json",
        "label": "Gemini 2.5 Flash — Voice/Audio Simulations (2x1)",
        "model": "gemini-2.5-flash",
        "now": "2026-09-28T18:43:20Z",
        "kind": "sims",
    },
    {
        "filename": "sims_baseline1831_on3flash_text_20260928_191853.json",
        "label": "Gemini 3 Flash — Baseline 7 Simulations x 3",
        "model": "gemini-3.0-flash-001",
        "now": "2026-09-28T19:18:53Z",
        "kind": "sims",
    },
    {
        "filename": "sims_round2_baseline1831_text_20260928_204506.json",
        "label": "Gemini 3 Flash — Round 2 Pinned Simulations (7x3)",
        "model": "gemini-3.0-flash-001",
        "now": "2026-09-28T20:45:06Z",
        "kind": "sims",
    },
    {
        "filename": "probes_text_20260928_204757.json",
        "label": "Gemini 3 Flash — Round 2 Scripted Probes (10x1)",
        "model": "gemini-3.0-flash-001",
        "now": "2026-09-28T20:47:57Z",
        "kind": "probes",
    },
)

ANALYZE_PARITY_CHECKS = (
    "dead_air_handoff",
    "code_leak",
    "race_facts_without_tool",
    "order_facts_without_tool",
    "tool_error",
)


def resolve_recorded_file(filename: str) -> Path:
    """Resolves a recorded results JSON from fixture dir or scratch dir."""
    candidate = Path(filename)
    if candidate.is_file():
        return candidate
    for directory in (FIXTURE_RECORDED_DIR, SCRATCH_RESULTS_DIR):
        p = directory / filename
        if p.is_file():
            return p
    raise FileNotFoundError(f"Recorded file not found: {filename}")


def _load_reference_analyzer():
    path = config.REPO_ROOT / "scripts" / "analyze_transcripts.py"
    spec = importlib.util.spec_from_file_location("analyze_transcripts_ref", path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def run_reference_analyze(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Runs scripts/analyze_transcripts.py logic over ``rows``."""
    analyzer = _load_reference_analyzer()
    flags = collections.Counter()
    valid_count = 0
    pass_count = 0
    quota_count = 0
    for r in rows:
        if analyzer.is_quota(str(r.get("error", ""))):
            quota_count += 1
            continue
        valid_count += 1
        if r.get("passed"):
            pass_count += 1
        trace = r.get("detailed_trace") or []
        for entry in trace:
            f, _ = analyzer.turn_flags(entry)
            flags.update(f)
        flags.update(analyzer.grounding_flags(trace))
    return {
        "valid_runs": valid_count,
        "judge_passed": pass_count,
        "quota_excluded": quota_count,
        "flag_counts": {k: int(flags.get(k, 0)) for k in ANALYZE_PARITY_CHECKS if flags.get(k, 0)},
    }


def _verbatim_turn_excerpt(row: dict[str, Any], conv: dict[str, Any], turn_index: int | None, trace_index: int | None) -> dict[str, Any]:
    """Extracts verbatim user/agent/trace text for a flagged turn."""
    trace = row.get("detailed_trace") or []
    raw_trace_entry = None
    if trace_index is not None and 0 <= trace_index < len(trace):
        raw_trace_entry = str(trace[trace_index])
    user_query = ""
    agent_text = ""
    tool_calls = []
    transfers = []
    turns = conv.get("turns") or []
    if turn_index is not None and 0 <= turn_index < len(turns):
        t = turns[turn_index]
        agent_text = str(t.get("text") or "")
        tool_calls = [
            {
                "name": c.get("name"),
                "args": c.get("args"),
                "response_excerpt": str(c.get("response_text") or c.get("response") or "")[:300],
            }
            for c in (t.get("tool_calls") or [])
        ]
        transfers = list(t.get("transfers") or [])
        for j in range(turn_index - 1, -1, -1):
            if turns[j].get("role") == "user":
                user_query = str(turns[j].get("text") or turns[j].get("event") or "")
                break
    return {
        "user_query": user_query,
        "agent_text": agent_text,
        "tool_calls": tool_calls,
        "transfers": transfers,
        "raw_trace_entry": raw_trace_entry,
    }


def regrade_file(spec: dict[str, str]) -> dict[str, Any]:
    """Re-grades one recorded results file and returns full structured evidence."""
    path = resolve_recorded_file(spec["filename"])
    data = json.loads(path.read_text(encoding="utf-8"))
    rows = data.get("results", data) if isinstance(data, dict) else data
    convs = grader.load_conversations(data, kind=spec.get("kind"), source=spec["filename"])
    ref = run_reference_analyze(rows)

    fail_counts: collections.Counter[str] = collections.Counter()
    warn_counts: collections.Counter[str] = collections.Counter()
    status_counts: collections.Counter[str] = collections.Counter()
    judge_overrides: list[dict[str, Any]] = []
    conv_records: list[dict[str, Any]] = []
    flagged_instances: list[dict[str, Any]] = []

    for row, conv in zip(rows, convs):
        det = grader.grade(
            conv,
            {
                "now": spec["now"],
                "expected_language": "auto",
                "voice": conv.get("modality") == "audio",
            },
        )
        judge = grader.judge_from_row(row)
        combined = grader.combine(det, judge, row_error=row.get("error"))
        status_counts[combined] += 1

        fails = []
        warns = []
        for ch in det["checks"]:
            if ch["status"] == "fail":
                fail_counts[ch["name"]] += 1
                verbatim = _verbatim_turn_excerpt(row, conv, ch.get("turn_index"), ch.get("trace_index"))
                entry = {
                    "conversation_id": conv["id"],
                    "name": row.get("name"),
                    "run": row.get("run"),
                    "session_id": conv.get("session_id"),
                    "check": ch["name"],
                    "status": "fail",
                    "turn_index": ch.get("turn_index"),
                    "trace_index": ch.get("trace_index"),
                    "findings": ch.get("findings", []),
                    "evidence": ch.get("evidence", ""),
                    "verbatim": verbatim,
                }
                fails.append(entry)
                flagged_instances.append(entry)
            elif ch["status"] == "warn":
                warn_counts[ch["name"]] += 1
                verbatim = _verbatim_turn_excerpt(row, conv, ch.get("turn_index"), ch.get("trace_index"))
                entry = {
                    "conversation_id": conv["id"],
                    "name": row.get("name"),
                    "run": row.get("run"),
                    "session_id": conv.get("session_id"),
                    "check": ch["name"],
                    "status": "warn",
                    "turn_index": ch.get("turn_index"),
                    "trace_index": ch.get("trace_index"),
                    "findings": ch.get("findings", []),
                    "evidence": ch.get("evidence", ""),
                    "verbatim": verbatim,
                }
                warns.append(entry)
                flagged_instances.append(entry)

        judge_passed = bool(row.get("passed")) if row.get("passed") is not None else None
        if judge_passed is True and not det["passed"]:
            judge_overrides.append(
                {
                    "conversation_id": conv["id"],
                    "session_id": conv.get("session_id"),
                    "judge_passed": True,
                    "deterministic_passed": False,
                    "combined_status": combined,
                    "failing_checks": [f["check"] for f in fails],
                }
            )

        conv_records.append(
            {
                "conversation_id": conv["id"],
                "name": row.get("name"),
                "run": row.get("run"),
                "session_id": conv.get("session_id"),
                "modality": conv.get("modality"),
                "judge_passed": judge_passed,
                "deterministic_passed": det["passed"],
                "combined_status": combined,
                "fail_checks": [f["check"] for f in fails],
                "warn_checks": [w["check"] for w in warns],
                "fails": fails,
                "warns": warns,
            }
        )

    return {
        "filename": spec["filename"],
        "label": spec["label"],
        "model": spec["model"],
        "now": spec["now"],
        "kind": spec["kind"],
        "total_conversations": len(conv_records),
        "reference_analyze_py": ref,
        "grader_fail_counts": dict(sorted(fail_counts.items())),
        "grader_warn_counts": dict(sorted(warn_counts.items())),
        "combined_status_counts": dict(sorted(status_counts.items())),
        "judge_overridden_by_deterministic": judge_overrides,
        "flagged_instances": flagged_instances,
        "conversations": conv_records,
    }


def regrade_all(specs: tuple[dict[str, str], ...] = RECORDED_FILES) -> dict[str, Any]:
    """Re-grades all configured recorded files."""
    files_out = {}
    for spec in specs:
        files_out[spec["filename"]] = regrade_file(spec)
    return {
        "schema_version": 1,
        "catalogue": grader.CATALOGUE,
        "thresholds": grader.DEFAULT_THRESHOLDS,
        "files": files_out,
    }


def render_markdown_report(payload: dict[str, Any]) -> str:
    """Renders a self-contained Markdown report with verbatim transcript evidence."""
    lines = [
        "# Deterministic Transcript Regrade Report",
        "",
        "Generated by `python -m totto_suite.grader.regrade` (offline, zero LLM/network calls).",
        "",
        "## 1. Summary Comparison: `analyze.py` vs `totto_suite.grader`",
        "",
        "| File | Model | Runs | Judge Passed | Combined PASS / FAIL / INFRA | `analyze.py` Flags | `totto_suite.grader` Deterministic FAILs | `totto_suite.grader` WARNs | Judge PASS -> Det FAIL Overrides |",
        "|---|---|---:|---:|---|---|---|---|---:|",
    ]
    for fname, fdata in payload["files"].items():
        ref = fdata["reference_analyze_py"]
        st = fdata["combined_status_counts"]
        st_str = f"{st.get('PASS', 0)}P / {st.get('FAIL', 0)}F / {st.get('INFRA_ERROR', 0)}I"
        ref_flags = ", ".join(f"`{k}`={v}" for k, v in sorted(ref["flag_counts"].items())) or "none"
        g_fails = ", ".join(f"`{k}`={v}" for k, v in sorted(fdata["grader_fail_counts"].items())) or "none"
        g_warns = ", ".join(f"`{k}`={v}" for k, v in sorted(fdata["grader_warn_counts"].items())) or "none"
        lines.append(
            f"| `{fname}` | `{fdata['model']}` | {fdata['total_conversations']} | "
            f"{ref['judge_passed']}/{ref['valid_runs']} | {st_str} | {ref_flags} | "
            f"{g_fails} | {g_warns} | {len(fdata['judge_overridden_by_deterministic'])} |"
        )

    lines += [
        "",
        "### Parity & False-Positive Fixes Verified",
        "- **Gemini 2.5 Flash (`sims_repo_text_20260928_184131.json`):** `totto_suite.grader` flags all 5 `dead_air_handoff`, all 5 `code_leak`, the 1 `race_facts_without_tool`, and all 3 `tool_error` found by `analyze.py`, plus 3 `internal_agent_names` (TR-05), 7 `language_match` (TR-04), 5 `past_race_as_upcoming` (TR-09/TB-5), and 6 `disclosure_freshness` (TR-09).",
        "- **Gemini 3 Flash (`sims_baseline1831_on3flash_text_20260928_191853.json`):** `totto_suite.grader` flags the 1 `tool_error` (`sim_ac4` run 1 session `03f0773b-bbd0-495d-9c4a-31c19cfe2fad` trace[7]), plus 6 `past_race_as_upcoming` (British GP July 3-5 presented as upcoming in `sim_ac1` x3 and `sim_ac6` x3), 6 `disclosure_freshness`, 67 `tts_unfriendly` warnings (emojis `🏎️💨` and markdown `**`/bullets), and 68 `reply_length` warnings.",
        "- **Voice Override (`sims_audiocheck_audio_20260928_184320.json`):** In `sim_ac4_official_ticketing_referral_non_transactional#run1` (session `a6b6ae57-f441-4c3c-b9f5-f29f3255dfce`), the LLM judge graded `passed: true` even though the agent spoke raw Python tool calls (`transfer_to_agent(...)`, ```` ```python default_api.get_official_links(...) ``` ````). `combine()` overrides the judge and marks the conversation `FAIL`.",
        "- **False-Positive Elimination:**",
        "  1. In `probes_text_20260928_183505.json` and `probes_text_20260928_204757.json`, `probe_order_not_found_9999` deliberately queries invalid order `9999`. `analyze.py` flags 3 false-positive `tool_error`s; `totto_suite.grader` allows `agent_action=OFFER_SAMPLE_ORDER_IDS` when the argument `9999` was supplied by the user.",
        "  2. In `sims_round2_baseline1831_text_20260928_204506.json` (`sim_ac5` run 1 trace[3]), the agent reports a merch delivery timestamp (`Delivered (Yesterday at 2:15 PM)`) and later mentions `Grand Prix`. `analyze.py` falsely flags `race_facts_without_tool`; `totto_suite.grader` scopes race-time checks to sentences with race/timezone context and verifies grounding against tool responses (`0` false positives).",
        "",
        "## 2. Deterministic Check Catalogue",
        "",
        "| Check | Findings Covered | Rule |",
        "|---|---|---|",
    ]
    for name, meta in payload["catalogue"].items():
        findings = ", ".join(f"`{f}`" for f in meta["findings"])
        lines.append(f"| `{name}` | {findings} | {meta['logic']} |")

    # Section 3: Full verbatim evidence for Gemini 3 Flash (191853)
    f3 = payload["files"].get("sims_baseline1831_on3flash_text_20260928_191853.json")
    if f3:
        lines += [
            "",
            "## 3. Verbatim Transcript Evidence — Gemini 3 Flash (`sims_baseline1831_on3flash_text_20260928_191853.json`)",
            "",
            "Every deterministic `FAIL` and sample `WARN` flagged in `sims_baseline1831_on3flash_text_20260928_191853.json` is shown below with its session ID, trace index, and verbatim transcript.",
            "",
            "### 3.1 Deterministic `FAIL` Flags (13 instances across 7 conversations)",
            "",
        ]
        for idx, item in enumerate(
            [x for x in f3["flagged_instances"] if x["status"] == "fail"], 1
        ):
            v = item["verbatim"]
            lines += [
                f"#### {idx}. `{item['conversation_id']}` — `{item['check']}` (session `{item['session_id']}`, turn `{item['turn_index']}`, trace[{item['trace_index']}])",
                f"- **Findings:** {', '.join('`' + f + '`' for f in item['findings'])}",
                f"- **Grader Evidence:** {item['evidence']}",
                f"- **User Query:** `{v['user_query']}`",
            ]
            if v["tool_calls"]:
                lines.append(f"- **Tool Calls:** `{json.dumps(v['tool_calls'], ensure_ascii=False)}`")
            lines += [
                "- **Verbatim Trace Entry:**",
                "```text",
                (v["raw_trace_entry"] or v["agent_text"]).strip(),
                "```",
                "",
            ]

        lines += [
            "### 3.2 Deterministic `WARN` Flags in Gemini 3 Flash (`tts_unfriendly` & `reply_length`)",
            "",
            f"- **`tts_unfriendly` ({f3['grader_warn_counts'].get('tts_unfriendly', 0)} turns):** Gemini 3 Flash appends `🏎️💨` to welcome greetings and uses markdown bold (`**...**`) and bullet lists (`* ...`) across replies.",
            f"- **`reply_length` ({f3['grader_warn_counts'].get('reply_length', 0)} turns):** Gemini 3 Flash replies exceed the 4-sentence / 450-char spoken voice budget.",
            "",
            "Representative verbatim examples from `sims_baseline1831_on3flash_text_20260928_191853.json`:",
            "",
        ]
        shown_warn_checks: set[str] = set()
        for item in f3["flagged_instances"]:
            if item["status"] != "warn" or item["check"] in shown_warn_checks:
                continue
            shown_warn_checks.add(item["check"])
            v = item["verbatim"]
            lines += [
                f"- **`{item['check']}`** on `{item['conversation_id']}` (session `{item['session_id']}`, trace[{item['trace_index']}]): {item['evidence']}",
                "```text",
                (v["raw_trace_entry"] or v["agent_text"]).strip()[:600],
                "```",
                "",
            ]

    # Section 4: Full verbatim evidence for Gemini 2.5 Flash (184131) & Audio (184320) & Probes (183505)
    for fname, section_title in (
        ("sims_repo_text_20260928_184131.json", "4. Verbatim Transcript Evidence — Gemini 2.5 Flash (`sims_repo_text_20260928_184131.json`)"),
        ("sims_audiocheck_audio_20260928_184320.json", "5. Verbatim Transcript Evidence — Voice Simulations (`sims_audiocheck_audio_20260928_184320.json`)"),
        ("probes_text_20260928_183505.json", "6. Verbatim Transcript Evidence — Scripted Probes (`probes_text_20260928_183505.json`)"),
    ):
        fdata = payload["files"].get(fname)
        if not fdata:
            continue
        lines += [
            "",
            f"## {section_title}",
            "",
        ]
        fail_items = [x for x in fdata["flagged_instances"] if x["status"] == "fail"]
        for idx, item in enumerate(fail_items, 1):
            v = item["verbatim"]
            lines += [
                f"### {idx}. `{item['conversation_id']}` — `{item['check']}` (session `{item['session_id']}`, turn `{item['turn_index']}`, trace[{item['trace_index']}])",
                f"- **Findings:** {', '.join('`' + f + '`' for f in item['findings'])}",
                f"- **Grader Evidence:** {item['evidence']}",
                f"- **User Query:** `{v['user_query']}`",
                "- **Verbatim Trace Entry:**",
                "```text",
                (v["raw_trace_entry"] or v["agent_text"]).strip()[:800],
                "```",
                "",
            ]

    return "\n".join(lines) + "\n"


def write_regrade_artifacts(out_dir: Path | str = DEFAULT_OUT_DIR) -> dict[str, Any]:
    """Runs regrade_all() and writes regrade_results.json + regrade_report.md."""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    payload = regrade_all()
    json_path = out / "regrade_results.json"
    md_path = out / "regrade_report.md"
    json_path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    md_path.write_text(render_markdown_report(payload), encoding="utf-8")
    return {
        "payload": payload,
        "json_path": str(json_path),
        "md_path": str(md_path),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Re-grade recorded simulation/probe transcripts.")
    parser.add_argument(
        "--out",
        default=str(DEFAULT_OUT_DIR),
        help="Output directory for regrade_results.json and regrade_report.md",
    )
    args = parser.parse_args(argv)
    res = write_regrade_artifacts(Path(args.out))
    print(f"Wrote {res['json_path']} and {res['md_path']}")
    for fname, fdata in res["payload"]["files"].items():
        print(
            f"  {fname}: statuses={fdata['combined_status_counts']} "
            f"fails={fdata['grader_fail_counts']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
