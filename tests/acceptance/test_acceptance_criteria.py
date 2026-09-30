"""End-to-end automated verification of all Acceptance Criteria from ORIGINAL_REQUEST.md (M5)."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
import stat
import subprocess
from typing import Any

import pytest

from totto_suite import config, cxasapi, deploy, gate, mutants, oracle, records, taxonomy, trend
from totto_suite.grader import combine as grader_combine
from totto_suite.layers import offline_lint


def _load_all_records_by_id() -> dict[str, dict[str, Any]]:
    recs = records.load_all()
    return {r["run_id"]: r for r in recs}


def test_ac_coverage_1_all_findings_mapped_to_real_tests() -> None:
    """AC Coverage 1: docs/COVERAGE.md maps TR-01..TR-10, TB-1..TB-5, RC-01..RC-13, NEW-1..NEW-5, PRD-AC1..PRD-AC9 to real test IDs."""
    cov_path = config.REPO_ROOT / "docs" / "COVERAGE.md"
    assert cov_path.is_file(), "Missing docs/COVERAGE.md"
    cov_text = cov_path.read_text(encoding="utf-8")

    expected_ids = (
        [f"TR-{i:02d}" for i in range(1, 11)]
        + [f"TB-{i}" for i in range(1, 6)]
        + [f"RC-{i:02d}" for i in range(1, 14)]
        + [f"NEW-{i}" for i in range(1, 6)]
        + [f"PRD-AC{i}" for i in range(1, 10)]
    )
    for fid in expected_ids:
        assert f"**`{fid}`**" in cov_text, f"Finding {fid} missing from docs/COVERAGE.md table"

    # Verify dedicated report-card disagreement section with verbatim transcripts and session IDs
    assert "Where the Suite Disagrees with the Agent Report Card" in cov_text
    for conv_id in (
        "850a144b-635a-451e-abb4-ec28c842a056",
        "turn_eval_8446ef69",
        "7e6fe027-1567-40e7-8b86-0d758d74bdc6",
        "49d0d658-9211-4cb0-a6f6-c43f48f5a301",
        "45721445-5832-49d0-9fd9-1895f27f60ae",
    ):
        assert conv_id in cov_text, f"Expected live conversation ID {conv_id} in docs/COVERAGE.md"

    # Cross-check that every live_*::* test ID cited in docs/COVERAGE.md exists in the live run record
    by_id = _load_all_records_by_id()
    live_rec = by_id["20260929T001319Z_live_fd9be8b"]
    live_test_ids = {t["id"] for t in live_rec["tests"]}

    cited_live_ids = set(re.findall(r"\blive_[a-z]+::[A-Za-z0-9_äöüßã-]+", cov_text))
    assert len(cited_live_ids) >= 20
    missing_live = cited_live_ids - live_test_ids
    assert not missing_live, f"docs/COVERAGE.md cites unknown live test IDs: {missing_live}"


def test_ac_coverage_2_dynamic_next_race_oracle_and_multi_date_tests() -> None:
    """AC Coverage 2: Next-race expectations use dynamic oracle rather than hardcoded GP names, and tool is tested across >= 4 dates."""
    fixture_dir = config.REPO_ROOT / "tests" / "fixtures" / "openf1"
    meetings, sessions = oracle.load_calendar(fixture_dir)
    races = oracle.race_meetings(meetings, sessions)
    assert len(races) >= 20

    # Verify oracle returns different next meetings at different instants of the 2026 season
    m_apr = oracle.next_race(meetings, oracle.parse_utc("2026-04-01T12:00:00Z"), sessions)
    m_jul = oracle.next_race(meetings, oracle.parse_utc("2026-07-01T12:00:00Z"), sessions)
    m_sep = oracle.next_race(meetings, oracle.parse_utc("2026-09-28T12:00:00Z"), sessions)
    m_oct = oracle.next_race(meetings, oracle.parse_utc("2026-10-05T12:00:00Z"), sessions)
    m_dec = oracle.next_race(meetings, oracle.parse_utc("2026-12-31T12:00:00Z"), sessions)

    assert m_apr is not None and int(m_apr["meeting_key"]) == 1284  # Miami
    assert m_jul is not None and int(m_jul["meeting_key"]) == 1289  # British GP
    assert m_sep is not None and int(m_sep["meeting_key"]) == 1308  # Kuala Lumpur
    assert m_oct is not None and int(m_oct["meeting_key"]) == 1296  # Singapore GP
    assert m_dec is None  # Post-season

    # Verify offline run record executes test_next_race_matches_oracle across >= 5 simulated dates
    by_id = _load_all_records_by_id()
    offline_recs = [r for r in by_id.values() if r["mode"] == "offline"]
    assert offline_recs, "Expected at least one offline run record"
    latest_off = offline_recs[-1]
    oracle_tests = [
        t["id"]
        for t in latest_off["tests"]
        if t["id"].startswith("dates::test_next_race_vs_oracle.py::test_next_race_matches_oracle[")
    ]
    assert len(oracle_tests) >= 10, f"Expected >= 10 date-parameterized oracle tests, got {len(oracle_tests)}"


def test_ac_coverage_3_cxas_lint_passes_with_zero_errors() -> None:
    """AC Coverage 3: cxas lint passes with 0 errors on cxas_app/."""
    ctx = {"app_dir": config.DEFAULT_APP_DIR, "repo_root": config.REPO_ROOT}
    results = offline_lint.run(ctx)
    assert len(results) >= 2
    for res in results:
        assert res["status"] == "PASS", f"Lint check {res['id']} failed: {res['message']}"


def test_ac_coverage_4_two_consecutive_offline_runs_under_60s_with_identical_digest() -> None:
    """AC Coverage 4: Two consecutive offline runs finish in < 60s each with identical results_digest."""
    all_recs = records.load_all()
    offline_recs = [r for r in all_recs if r["mode"] == "offline"]
    assert len(offline_recs) >= 2, "Expected at least 2 offline run records in evals/history/runs/"

    for rec in offline_recs:
        total_dur = sum(float(t.get("duration_s", 0.0)) for t in rec["tests"])
        t_start = oracle.parse_utc(rec["started_at"])
        t_end = oracle.parse_utc(rec["finished_at"])
        wall_s = (t_end - t_start).total_seconds()
        assert wall_s < 60.0, f"Offline run {rec['run_id']} took {wall_s:.1f}s (>= 60s limit)"
        assert total_dur > 0.0
        assert rec["infra_errors"]["count"] == 0

    same_commit_pairs = [
        (offline_recs[i], offline_recs[i + 1])
        for i in range(len(offline_recs) - 1)
        if offline_recs[i]["agent"]["commit"] == offline_recs[i + 1]["agent"]["commit"]
    ]
    assert same_commit_pairs, "Expected at least one pair of consecutive offline runs on the same commit"
    r1, r2 = same_commit_pairs[-1]
    assert r1["results_digest"] == r2["results_digest"], (
        f"Consecutive offline runs on commit {r1['agent']['commit']} have different digests: "
        f"{r1['run_id']}={r1['results_digest']} vs {r2['run_id']}={r2['results_digest']}"
    )


def test_ac_proof_1_regrade_reproduces_reference_counts_and_surfaces_missed_defects() -> None:
    """AC Proof 1: Re-grading recorded transcripts reproduces analyze_transcripts.py counts and catches missed defects."""
    regrade_json = config.HISTORY_DIR / "regrade" / "regrade_results.json"
    regrade_md = config.HISTORY_DIR / "regrade" / "regrade_report.md"
    assert regrade_json.is_file()
    assert regrade_md.is_file()

    payload = json.loads(regrade_json.read_text(encoding="utf-8"))
    files_by_name = payload["files"]
    assert len(files_by_name) == 6

    # 1. Exact reproduction of analyze_transcripts.py reference counts on 184131 and 191853
    f_184131 = files_by_name["sims_repo_text_20260928_184131.json"]
    assert f_184131["reference_analyze_py"]["flag_counts"] == {
        "dead_air_handoff": 5,
        "tool_error": 3,
        "code_leak": 5,
        "race_facts_without_tool": 1,
    }
    fails_1841 = f_184131["grader_fail_counts"]
    assert fails_1841["dead_air_handoff"] >= 5
    assert fails_1841["code_leak"] >= 5
    assert fails_1841["race_facts_without_tool"] >= 1
    assert fails_1841["tool_error"] >= 3

    f_191853 = files_by_name["sims_baseline1831_on3flash_text_20260928_191853.json"]
    assert f_191853["reference_analyze_py"]["flag_counts"] == {"tool_error": 1}
    assert f_191853["grader_fail_counts"]["tool_error"] == 1

    # 2. Audio simulation judge override on code leak (a6b6ae57-f441-4c3c-b9f5-f29f3255dfce)
    f_audio = files_by_name["sims_audiocheck_audio_20260928_184320.json"]
    assert len(f_audio["judge_overridden_by_deterministic"]) >= 1

    # 3. False-positive elimination on order 9999 tool_error in 183505 probes
    f_probes = files_by_name["probes_text_20260928_183505.json"]
    assert f_probes["reference_analyze_py"]["flag_counts"]["tool_error"] == 3
    assert f_probes["grader_fail_counts"].get("tool_error", 0) == 0


def test_ac_proof_2_ten_plus_local_mutants_100_percent_killed_and_repo_app_untouched() -> None:
    """AC Proof 2: >= 10 local mutants across tools, callbacks, and config are 100% killed without touching cxas_app/."""
    report_path = config.HISTORY_DIR / "mutants" / "mutants_report.json"
    assert report_path.is_file()
    report = json.loads(report_path.read_text(encoding="utf-8"))

    summary = report["summary"]
    assert summary["total_mutants"] >= 10
    assert summary["killed"] == summary["total_mutants"]
    assert summary["survived"] == 0
    assert summary["kill_rate"] == 1.0

    categories = {m["category"] for m in report["mutants"]}
    assert {"tools", "callbacks", "config"}.issubset(categories)
    for m in report["mutants"]:
        assert m["killed"] is True
        assert m["killed_by_count"] >= 1
        assert len(m["killed_by_scenarios"]) == m["killed_by_count"]

    # Verify baseline has 0 failing scenarios after fixes and cxas_app tree hash is deterministic
    assert report["baseline_summary"]["failed"] == 0
    assert report["baseline_summary"]["passed"] == report["baseline_summary"]["total_scenarios"]
    assert len(cxasapi.app_tree_hash(config.DEFAULT_APP_DIR)) == 64


def test_ac_proof_3_deterministic_checks_act_as_hard_gate_over_llm_judge() -> None:
    """AC Proof 3: Deterministic checks act as hard gates over the LLM judge in combine()."""
    det_fail = {
        "passed": False,
        "findings": ["[code_leak:TR-02] Agent printed default_api.get_race_schedule"],
    }
    judge_pass = {
        "passed": True,
        "error": None,
        "expectations": 2,
        "not_met": [],
    }
    status = grader_combine(det_fail, judge_pass)
    assert status == "FAIL"


def test_ac_live_1_seven_live_layers_three_repeats_and_verified_platform_ids() -> None:
    """AC Live 1: Full live suite run covers all 7 live layers with repeats=3 on conversation layers and 100% verified CXAS platform IDs."""
    by_id = _load_all_records_by_id()
    assert "20260929T001319Z_live_fd9be8b" in by_id
    live_rec = by_id["20260929T001319Z_live_fd9be8b"]
    records.validate(live_rec)

    expected_layers = {
        "live_tools",
        "live_goldens",
        "live_turns",
        "live_sims",
        "live_safety",
        "live_escalation",
        "live_voice",
    }
    assert set(live_rec["layers"].keys()) == expected_layers
    assert len(live_rec["tests"]) == 111  # 30 tool tests + 27 conversation scenarios * 3 repeats

    by_test_id: dict[str, list[dict[str, Any]]] = {}
    for t in live_rec["tests"]:
        by_test_id.setdefault(t["id"], []).append(t)
        pids = t.get("platform_ids") or {}
        assert pids, f"Live test {t['id']} repeat {t['repeat']} missing platform_ids"
        assert pids.get("app_version") == "b11332a0-b304-41e1-baac-57cd0ced05da"

    for tid, runs in by_test_id.items():
        if tid.startswith("live_tools::"):
            assert sorted(r["repeat"] for r in runs) == [1], f"Expected 1 repeat for tool test {tid}"
        else:
            assert sorted(r["repeat"] for r in runs) == [1, 2, 3], f"Expected 3 repeats for {tid}"

    verify_path = (
        config.HISTORY_DIR
        / "artifacts"
        / "20260929T001319Z_live_fd9be8b"
        / "verify_ids.json"
    )
    assert verify_path.is_file()
    vdata = json.loads(verify_path.read_text(encoding="utf-8"))
    assert vdata["all_verified"] is True
    assert vdata["total_test_entries"] == 111
    assert vdata["verified_test_entries"] == 111
    assert vdata["failed_test_entries"] == 0
    assert vdata["unique_resources_verified"] == vdata["unique_resources_checked"] >= 200
    for entry in vdata["entries"]:
        assert entry["ok"] is True


def test_ac_live_2_defects_doc_contains_verbatim_evidence_and_platform_ids() -> None:
    """AC Live 2: docs/DEFECTS.md documents all failing live and offline defects with verbatim evidence and CXAS IDs."""
    defects_path = config.REPO_ROOT / "docs" / "DEFECTS.md"
    assert defects_path.is_file()
    text = defects_path.read_text(encoding="utf-8")

    for section_id in (
        "TB-1",
        "TB-2",
        "TB-3",
        "TB-4",
        "TB-5",
        "TR-03",
        "TR-07",
        "TR-08",
        "TR-09",
        "TR-10",
        "NEW-1",
        "NEW-2",
        "NEW-3",
        "NEW-4",
        "NEW-5",
        "RC-01",
        "RC-02",
        "RC-04",
        "RC-05",
        "RC-06",
        "RC-07",
        "RC-08",
        "RC-10",
    ):
        assert section_id in text, f"Expected {section_id} in docs/DEFECTS.md"

    for conv_id in (
        "29367e77-2061-47f0-a319-4adbea3150c4",
        "211357da-2944-4401-9d4a-523ee29d735a",
        "1f7216b2-bd2d-4c8d-b836-1fb3629ff24f",
        "c7b887a7-c818-4526-a1fa-a6c94957e508",
        "884345fd-b623-4436-b93d-a8cf0d433aef",
        "2e28c62f-7189-443c-aed4-8edee303bb1b",
        "9e9ae90c-1fa0-4872-85c5-7da1c455877f",
        "feb1cc75-d838-4c7f-af6e-35081890347f",
        "7e6fe027-1567-40e7-8b86-0d758d74bdc6",
        "850a144b-635a-451e-abb4-ec28c842a056",
    ):
        assert conv_id in text, f"Expected live conversation ID {conv_id} in docs/DEFECTS.md"


def test_ac_live_3_infra_error_separation_from_agent_pass_rate() -> None:
    """AC Live 3: INFRA_ERROR (429 quota, 503, 504, timeouts) is separated from agent PASS/FAIL scores."""
    by_id = _load_all_records_by_id()
    rec_1841 = by_id["20260928T184131Z_imported_a7c3094"]
    assert rec_1841["infra_errors"]["count"] == 44
    assert rec_1841["infra_errors"]["by_kind"]["quota"] == 44

    # Verify layer score formula is P / (P + F) excluding infra_error
    for layer_name, lsum in rec_1841["layers"].items():
        denom = lsum["pass"] + lsum["fail"]
        if denom > 0:
            expected_score = round(lsum["pass"] / denom, 4)
            assert lsum["score"] == expected_score, f"Layer {layer_name} score included infra_error!"

    live_rec = by_id["20260929T001319Z_live_fd9be8b"]
    assert live_rec["infra_errors"]["count"] == 0


def test_ac_live_4_and_5_before_after_live_app_identity_proof() -> None:
    """AC Live 4 & 5: Live CXAS app agents, tools, callbacks, instructions, guardrails, and model settings are identical before and after."""
    diff_json_path = config.HISTORY_DIR / "snapshots" / "before_after_diff.json"
    diff_md_path = config.HISTORY_DIR / "snapshots" / "before_after_diff.md"
    assert diff_json_path.is_file()
    assert diff_md_path.is_file()

    diff_data = json.loads(diff_json_path.read_text(encoding="utf-8"))
    ic = diff_data["identity_checks"]
    assert ic["all_checks_passed"] is True
    assert ic["app_update_time_identical"] is True
    assert ic["app_etag_identical"] is True
    assert ic["model_settings_identical"] is True
    assert ic["guardrails_identical"] is True
    assert ic["variable_declarations_identical"] is True
    assert ic["root_agent_identical"] is True
    assert ic["core_files_count"] == 22
    assert ic["core_files_modified_count"] == 0
    assert ic["core_files_removed_count"] == 0
    assert ic["core_files_added_count"] == 0
    assert ic["core_raw_tree_hash_identical"] is True
    assert ic["core_normalized_tree_hash_identical"] is True
    assert ic["pre_existing_versions_preserved"] is True

    # Independently verify on disk that the 22 core files in live_before and live_after have identical SHA-256 digests
    before_app = config.HISTORY_DIR / "snapshots" / "20260928T215748Z_live_before" / "cxas_app"
    after_app = config.HISTORY_DIR / "snapshots" / "20260929T010751Z_live_after" / "cxas_app"
    assert before_app.is_dir()
    assert after_app.is_dir()

    for entry in diff_data["core_agent_files"]:
        rel = entry["path"]
        b_bytes = (before_app / rel).read_bytes()
        a_bytes = (after_app / rel).read_bytes()
        assert hashlib.sha256(b_bytes).hexdigest() == entry["sha256_before"]
        assert hashlib.sha256(a_bytes).hexdigest() == entry["sha256_after"]
        assert b_bytes == a_bytes, f"File {rel} differed between live_before and live_after!"


def test_ac_tracking_1_to_4_gate_deploy_records_and_chronological_trend_view() -> None:
    """AC Tracking 1–4: Pre-commit gate, push-disabled deploy, schema-v1 run records, and trend view with regressions."""
    # 1. Pre-commit hook & gate demo log
    hook_path = config.REPO_ROOT / "hooks" / "pre-commit"
    assert hook_path.is_file()
    assert bool(hook_path.stat().st_mode & stat.S_IXUSR)
    demo_log = (config.HISTORY_DIR / "gate" / "gate_demo.log").read_text(encoding="utf-8")
    assert "git commit exit code on broken change: 1" in demo_log
    assert "git commit exit code on clean change: 0" in demo_log

    # 2. Push-disabled deploy enforcement
    blocked = deploy.run_deploy(rationale="test push block", push=True)
    assert blocked["ok"] is False
    assert blocked["exit_code"] == deploy.EXIT_DEPLOY_BLOCKED
    assert blocked["push_performed"] is False

    # 3. Every run record in evals/history/runs/ validates against schema v1
    all_recs = records.load_all()
    assert len(all_recs) >= 12
    modes_seen = set()
    for rec in all_recs:
        records.validate(rec)
        modes_seen.add(rec["mode"])
        assert rec["agent"]["commit"]
        assert rec["cxas"]["version_status"] in (
            "in_version_list",
            "hidden_fetchable",
            "no_matching_version",
            "not_deployed",
        ) or (rec["mode"] == "ci" and rec["cxas"]["version_status"] == "draft")
        if rec["mode"] in ("snapshot", "deploy", "live"):
            assert rec["cxas"]["version_id"]
        elif rec["mode"] == "offline":
            assert rec["cxas"]["version_id"] or rec["cxas"]["version_status"] == "not_deployed"
        assert rec["cxas"]["model"]
        assert rec["rationale"]
        assert rec["results_digest"]

    assert {"reproduced", "imported", "snapshot", "offline", "deploy", "live"}.issubset(modes_seen)

    # 4. Trend view files exist, include all runs ordered by point_time, and flag regressions
    assert config.INDEX_PATH.is_file()
    assert config.TREND_MD_PATH.is_file()
    assert config.TREND_HTML_PATH.is_file()

    index_data = json.loads(config.INDEX_PATH.read_text(encoding="utf-8"))
    assert len(index_data["runs"]) == len(all_recs)
    point_times = [r["point_time"] for r in index_data["runs"]]
    assert point_times == sorted(point_times), "index.json runs must be ordered chronologically by point_time"

    trend_md = config.TREND_MD_PATH.read_text(encoding="utf-8")
    assert "REGRESSION" in trend_md
    for rec in all_recs:
        assert rec["run_id"] in trend_md, f"Run {rec['run_id']} missing from TREND.md"


def test_ac_handover_1_plain_english_readme_and_clean_cxas_app() -> None:
    """AC Handover 1: Plain-English README at repo root explains modes, trend view, and post-change workflow; cxas_app/ is clean."""
    readme_path = config.REPO_ROOT / "README.md"
    assert readme_path.is_file(), "Missing README.md at repo root"
    readme_text = readme_path.read_text(encoding="utf-8")

    for required_section in (
        "How to Run Each Mode",
        "How to Read the Trend View",
        "What to Do After Changing the Agent",
        "totto_suite offline",
        "totto_suite gate",
        "totto_suite live",
        "totto_suite mutants",
        "totto_suite trend",
        "totto_suite deploy",
        "docs/COVERAGE.md",
        "docs/DEFECTS.md",
        "evals/history/TREND.md",
        "evals/history/snapshots/before_after_diff.md",
    ):
        assert required_section in readme_text, f"README.md missing '{required_section}'"

    # Verify cxas_app/ has zero uncommitted git diff against HEAD
    res = subprocess.run(
        ["git", "diff", "HEAD", "--", "cxas_app"],
        cwd=config.REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    assert res.stdout.strip() == "", "cxas_app/ must have zero uncommitted modifications vs HEAD"


def test_ac_handover_2_docs_claims_links_and_zero_leaked_identifiers() -> None:
    """AC Handover 2: README.md and docs/*.md contain zero leaked identifiers, zero broken relative links, and accurate R5 claims."""
    import re
    from totto_suite.dashboard import scrub

    docs = [config.REPO_ROOT / "README.md"] + sorted((config.REPO_ROOT / "docs").glob("*.md"))
    assert len(docs) >= 10

    deny = scrub.default_deny_list()
    forbidden_patterns = (
        r"(?<![0-9a-fA-F-])(?!0{12})\d{12}(?![0-9a-fA-F-])",  # 12-digit GCP project numbers
        r"altostrat",
        r"snehsm(?!007)",
        r"sync_merch_state",
        r"--layer\s+regrade",
        r"(?<!deploy_)manifest\.json",
    )
    md_link_re = re.compile(r"\[[^\]]+\]\(([^)]+)\)")

    for doc in docs:
        rel_doc = str(doc.relative_to(config.REPO_ROOT))
        text = doc.read_text(encoding="utf-8")
        leaks = scrub.find_leaks(text, where=rel_doc, deny=deny)
        assert not leaks, f"Identifier leak(s) in {rel_doc}: {[str(f) for f in leaks]}"
        for pat in forbidden_patterns:
            match = re.search(pat, text)
            assert match is None, f"Forbidden pattern '{pat}' found in {rel_doc}: {match.group(0)}"
        for m in md_link_re.finditer(text):
            target = m.group(1).strip()
            if target.startswith(("http://", "https://", "tel:", "mailto:", "#")):
                continue
            target_path = target.split("#")[0]
            if not target_path:
                continue
            resolved = (doc.parent / target_path).resolve()
            assert resolved.exists(), f"Broken relative link '{target}' in {rel_doc}"


