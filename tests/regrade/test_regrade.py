"""Regrade verification tests on recorded CXAS results JSON fixtures."""

from __future__ import annotations

import json

from totto_suite.grader.regrade import (
    DEFAULT_OUT_DIR,
    RECORDED_FILES,
    regrade_file,
)


def _spec_for(filename: str) -> dict[str, str]:
    return next(s for s in RECORDED_FILES if s["filename"] == filename)


class TestRecordedRegrade:
    def test_25flash_sims_regrade_catches_all_known_failure_classes(self):
        spec = _spec_for("sims_repo_text_20260928_184131.json")
        res = regrade_file(spec)
        assert res["model"] == "gemini-2.5-flash"
        assert res["total_conversations"] == 21
        fails = res["grader_fail_counts"]
        assert fails.get("dead_air_handoff", 0) >= 5
        assert fails.get("code_leak", 0) >= 5
        assert fails.get("race_facts_without_tool", 0) >= 1
        assert fails.get("tool_error", 0) >= 3
        assert fails.get("internal_agent_names", 0) >= 3
        assert fails.get("language_match", 0) >= 5
        assert fails.get("past_race_as_upcoming", 0) >= 5
        assert fails.get("disclosure_freshness", 0) >= 5

    def test_30flash_sims_regrade_catches_tool_error_and_deterministic_defects(self):
        spec = _spec_for("sims_baseline1831_on3flash_text_20260928_191853.json")
        res = regrade_file(spec)
        assert res["model"] == "gemini-3.0-flash-001"
        assert res["total_conversations"] == 21
        fails = res["grader_fail_counts"]
        assert fails.get("tool_error", 0) == 1
        assert fails.get("past_race_as_upcoming", 0) == 6
        assert fails.get("disclosure_freshness", 0) == 6
        warns = res["grader_warn_counts"]
        assert warns.get("tts_unfriendly", 0) > 0
        assert warns.get("reply_length", 0) > 0

        # Verify verbatim transcript evidence is captured on the tool_error flag
        tool_err_flags = [
            f
            for f in res["flagged_instances"]
            if f["check"] == "tool_error" and f["status"] == "fail"
        ]
        assert len(tool_err_flags) == 1
        flag = tool_err_flags[0]
        assert flag["session_id"] == "03f0773b-bbd0-495d-9c4a-31c19cfe2fad"
        assert flag["trace_index"] == 7
        assert "category': 'both'" in (flag["verbatim"]["raw_trace_entry"] or "")

    def test_audio_sims_judge_override_on_code_leak(self):
        spec = _spec_for("sims_audiocheck_audio_20260928_184320.json")
        res = regrade_file(spec)
        assert res["grader_fail_counts"].get("code_leak", 0) >= 3
        assert len(res["judge_overridden_by_deterministic"]) == 1

        ac4 = next(
            c
            for c in res["conversations"]
            if c["session_id"] == "a6b6ae57-f441-4c3c-b9f5-f29f3255dfce"
        )
        assert ac4["judge_passed"] is True
        assert ac4["deterministic_passed"] is False
        assert ac4["combined_status"] == "FAIL"

    def test_false_positive_elimination_vs_analyze_py(self):
        probes = regrade_file(_spec_for("probes_text_20260928_183505.json"))
        assert probes["reference_analyze_py"]["flag_counts"].get("tool_error") == 3
        assert probes["grader_fail_counts"].get("tool_error", 0) == 0

        round2 = regrade_file(_spec_for("sims_round2_baseline1831_text_20260928_204506.json"))
        assert round2["reference_analyze_py"]["flag_counts"].get("race_facts_without_tool") == 1
        assert round2["grader_fail_counts"].get("race_facts_without_tool", 0) == 0

    def test_regrade_artifacts_generated_and_match(self):
        results_json = DEFAULT_OUT_DIR / "regrade_results.json"
        report_md = DEFAULT_OUT_DIR / "regrade_report.md"
        assert results_json.is_file(), f"Missing {results_json}"
        assert report_md.is_file(), f"Missing {report_md}"

        data = json.loads(results_json.read_text(encoding="utf-8"))
        assert len(data["files"]) == 6
        md = report_md.read_text(encoding="utf-8")
        assert "03f0773b-bbd0-495d-9c4a-31c19cfe2fad" in md
        assert "a6b6ae57-f441-4c3c-b9f5-f29f3255dfce" in md
        assert "Verbatim Trace Entry:" in md
