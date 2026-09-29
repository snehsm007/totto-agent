"""ci-gate: gate rule, app-relative IDs, fake evidence and gate helpers (R5)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from totto_suite import ci_gate, fakes, gate_rule, ids, records
from totto_suite.cli import hidden_version_ids

APP = "projects/proj-x/locations/us/apps/app-uuid-123"


def _t(tid, status, layer="live_goldens", repeat=1, **kw):
    return {"id": tid, "layer": layer, "status": status, "repeat": repeat, **kw}


def _agg(*rows):
    return gate_rule.aggregate_repeats(list(rows))


# --------------------------------------------------------------------------
# aggregation of repeats
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("statuses", "expected"),
    [
        (["PASS", "PASS"], "PASS"),
        (["PASS", "FAIL"], "FAIL"),  # tie -> FAIL
        (["PASS", "PASS", "FAIL"], "PASS"),  # flaky repeat out-voted
        (["PASS", "INFRA_ERROR"], "PASS"),  # infra repeat is not a verdict
        (["INFRA_ERROR", "INFRA_ERROR"], "INFRA_ERROR"),
        (["SKIPPED", "SKIPPED"], "SKIPPED"),
        (["SKIPPED", "INFRA_ERROR"], "INFRA_ERROR"),
    ],
)
def test_aggregate_status_is_strict_majority_of_decided_repeats(statuses, expected):
    assert gate_rule.aggregate_status(statuses) == expected


def test_aggregate_repeats_groups_by_id_and_merges_tool_mode_and_fake_verified():
    agg = _agg(
        _t("a", "PASS", repeat=2, tool_mode="fake", fake_verified=True),
        _t("a", "PASS", repeat=1, tool_mode="fake", fake_verified=None),
        _t("b", "FAIL", tool_mode="fake", fake_verified=False),
    )
    assert [t["id"] for t in agg] == ["a", "b"]
    assert agg[0]["repeat_statuses"] == ["PASS", "PASS"]
    assert agg[0]["fake_verified"] is True and agg[0]["tool_mode"] == "fake"
    assert agg[1]["fake_verified"] is False


# --------------------------------------------------------------------------
# gate rule
# --------------------------------------------------------------------------


def test_gate_passes_when_floors_met_without_baseline():
    agg = _agg(_t("a", "PASS"), _t("b", "PASS"), _t("c", "FAIL"))
    res = gate_rule.evaluate(agg, {"overall_floor": 0.6})
    assert res["verdict"] == "PASS" and res["exit_code"] == 0
    assert res["pass_rate"] == pytest.approx(2 / 3, abs=1e-4)
    assert res["baseline_pass_rate"] is None


def test_gate_fails_below_overall_floor():
    agg = _agg(_t("a", "PASS"), _t("b", "FAIL"), _t("c", "FAIL"))
    res = gate_rule.evaluate(agg, {"overall_floor": 0.5})
    assert res["verdict"] == "FAIL" and res["exit_code"] == 1
    assert any("floor" in r for r in res["reasons"])


def test_gate_fails_below_a_layer_floor_even_if_overall_is_fine():
    agg = _agg(
        _t("g1", "PASS"),
        _t("g2", "PASS"),
        _t("g3", "PASS"),
        _t("s1", "FAIL", layer="live_sims"),
    )
    res = gate_rule.evaluate(agg, {"overall_floor": 0.5, "layer_floors": {"live_sims": 0.5}})
    assert res["verdict"] == "FAIL"
    assert any("live_sims" in r for r in res["reasons"])


def test_gate_fails_on_regression_beyond_baseline_tolerance():
    baseline = {"schema": ci_gate.SCHEMA, "tool_mode": "fake", "pass_rate": 1.0, "tests": []}
    agg = _agg(*[_t(f"t{i}", "PASS") for i in range(8)], _t("x", "FAIL"), _t("y", "FAIL"))
    res = gate_rule.evaluate(agg, {"baseline_tolerance_pp": 10}, baseline, "fake")
    assert res["verdict"] == "FAIL"  # 80% < 100% - 10pp
    ok = gate_rule.evaluate(agg, {"baseline_tolerance_pp": 20}, baseline, "fake")
    assert ok["verdict"] == "PASS"  # 80% >= 100% - 20pp (boundary inclusive)


def test_gate_fails_when_too_many_baseline_passes_now_fail():
    baseline = {
        "tool_mode": "fake",
        "pass_rate": 0.5,
        "tests": [{"id": "a", "status": "PASS"}, {"id": "b", "status": "PASS"}],
    }
    agg = _agg(_t("a", "FAIL"), _t("b", "FAIL"), *[_t(f"n{i}", "PASS") for i in range(8)])
    res = gate_rule.evaluate(agg, {"max_new_failures": 1, "baseline_tolerance_pp": 50}, baseline, "fake")
    assert res["verdict"] == "FAIL"
    assert res["new_failures_vs_baseline"] == ["a", "b"]
    tolerated = gate_rule.evaluate(agg, {"max_new_failures": 2, "baseline_tolerance_pp": 50}, baseline, "fake")
    assert tolerated["verdict"] == "PASS"
    assert any("tolerated" in r for r in tolerated["reasons"])


def test_baseline_with_other_tool_mode_is_ignored():
    baseline = {"tool_mode": "real", "pass_rate": 1.0, "tests": [{"id": "a", "status": "PASS"}]}
    agg = _agg(_t("a", "FAIL"), _t("b", "PASS"), _t("c", "PASS"))
    res = gate_rule.evaluate(agg, {"max_new_failures": 0}, baseline, "fake")
    assert res["verdict"] == "PASS"
    assert res["baseline_pass_rate"] is None
    assert any("baseline ignored" in r for r in res["reasons"])


def test_only_infra_errors_is_inconclusive():
    agg = _agg(_t("a", "INFRA_ERROR"), _t("b", "INFRA_ERROR"))
    res = gate_rule.evaluate(agg, {"overall_floor": 0.9})
    assert res["verdict"] == "INCONCLUSIVE" and res["exit_code"] == 3


def test_many_infra_errors_that_could_flip_the_result_are_inconclusive():
    # 3 PASS + 1 FAIL decided (75%); 2 INFRA: optimistic 5/6 passes the 0.7
    # floor, pessimistic 3/6 does not, and infra share 33% > 25%.
    agg = _agg(
        _t("a", "PASS"), _t("b", "PASS"), _t("c", "PASS"), _t("d", "FAIL"),
        _t("e", "INFRA_ERROR"), _t("f", "INFRA_ERROR"),
    )
    res = gate_rule.evaluate(agg, {"overall_floor": 0.7})
    assert res["verdict"] == "INCONCLUSIVE"
    assert res["infra_ratio"] == pytest.approx(2 / 6, abs=1e-4)


def test_infra_errors_cannot_rescue_a_clear_failure():
    # Even if both INFRA tests had passed: 2/6 < 0.7 -> FAIL, not INCONCLUSIVE.
    agg = _agg(
        _t("a", "FAIL"), _t("b", "FAIL"), _t("c", "FAIL"), _t("d", "FAIL"),
        _t("e", "INFRA_ERROR"), _t("f", "INFRA_ERROR"),
    )
    assert gate_rule.evaluate(agg, {"overall_floor": 0.7})["verdict"] == "FAIL"


def test_few_infra_errors_are_decided_on_decided_tests():
    agg = _agg(*[_t(f"p{i}", "PASS") for i in range(9)], _t("i", "INFRA_ERROR"))
    res = gate_rule.evaluate(agg, {"overall_floor": 0.95})
    assert res["verdict"] == "PASS"  # 10% infra <= 25%; decided 9/9


def test_skipped_tests_do_not_count_toward_rates():
    agg = _agg(_t("a", "PASS"), _t("b", "SKIPPED"), _t("c", "SKIPPED"))
    res = gate_rule.evaluate(agg, {"overall_floor": 1.0})
    assert res["verdict"] == "PASS" and res["pass_rate"] == 1.0


# --------------------------------------------------------------------------
# app-relative IDs
# --------------------------------------------------------------------------


def test_relativize_platform_ids_strips_app_prefix_and_types_bare_ids():
    pids = {
        "evaluation_run": f"{APP}/evaluationRuns/r1",
        "evaluation_result": f"{APP}/evaluations/e1/results/x",
        "conversation": f"{APP}/conversations/c1",
        "session_id": "abc-123",
        "app_version": "v-9",
        "tool": "tools/t1",
        "empty": "",
    }
    assert ids.relativize_platform_ids(pids) == {
        "evaluation_run": "evaluationRuns/r1",
        "evaluation_result": "evaluations/e1/results/x",
        "conversation": "conversations/c1",
        "session_id": "sessions/abc-123",
        "app_version": "versions/v-9",
        "tool": "tools/t1",
    }


def test_to_full_prefixes_relative_ids_and_passes_full_names_through():
    assert ids.to_full(APP, "evaluationRuns/r1") == f"{APP}/evaluationRuns/r1"
    assert ids.to_full(APP, f"{APP}/tools/t") == f"{APP}/tools/t"
    assert ids.to_full(APP, "") == ""


def test_legacy_and_placeholder_detection():
    assert ids.is_legacy_id(f"{APP}/tools/t")
    assert not ids.is_legacy_id("tools/t")
    assert ids.is_placeholder_id("projects/your-gcp-project/locations/us/apps/x/tools/t")
    assert not ids.is_placeholder_id(f"{APP}/tools/t")


def test_redact_text_removes_project_and_app_identifiers():
    text = (
        f"404 {APP}/evaluationRuns/r1 not found; agent "
        "projects/123456789/locations/us/agents/x; app app-uuid-123 in proj-x"
    )
    out = ids.redact_text(text, APP)
    assert "evaluationRuns/r1" in out
    for secret in ("proj-x", "app-uuid-123", "123456789"):
        assert secret not in out


def test_resolve_app_name_precedence_and_staging_config():
    cfg = {"gcp_project_id": "p", "location": "eu", "app_id": "live-id", "staging_app_id": "stg-id"}
    assert ids.resolve_app_name(APP, "staging", {}, cfg) == APP
    env = {"TOTTO_APP_NAME": "projects/e/locations/us/apps/envapp"}
    assert ids.resolve_app_name(None, "staging", env, cfg).endswith("/apps/envapp")
    env2 = {"GCP_PROJECT_ID": "gp", "CXAS_APP_ID": "ga"}
    assert ids.resolve_app_name(None, "live", env2, cfg) == "projects/gp/locations/us/apps/ga"
    assert ids.resolve_app_name(None, "staging", {}, cfg) == "projects/p/locations/eu/apps/stg-id"
    assert ids.resolve_app_name(None, "live", {}, cfg) == "projects/p/locations/eu/apps/live-id"
    with pytest.raises(ValueError):
        ids.resolve_app_name(None, "staging", {}, {})
    with pytest.raises(ValueError):
        ids.resolve_app_name("not-a-resource-name", "staging", {}, {})


# --------------------------------------------------------------------------
# fake evidence
# --------------------------------------------------------------------------

FAKE_CONV = {
    "turns": [
        {
            "rootSpan": {
                "name": "Turn",
                "childSpans": [
                    {"name": "Fake Tool", "attributes": {"type": "ToolFake", "name": "get_official_links"}},
                    {"name": "Tool", "attributes": {"type": "TransferToAgentTool", "name": "transfer"}},
                ],
            },
            "messages": [{"toolResponse": {"response": {"_fake": True, "status": "success"}}}],
        }
    ]
}
REAL_CONV = {
    "turns": [
        {
            "rootSpan": {
                "childSpans": [
                    {"name": "Tool", "attributes": {"type": "PythonFunctionTool", "name": "get_race_schedule"}}
                ]
            }
        }
    ]
}


def test_span_evidence_counts_fake_spans_and_markers_but_not_system_tools():
    ev = fakes.span_evidence(FAKE_CONV, {"get_official_links", "get_race_schedule"})
    assert ev["fake_tool_spans"] == 1 and ev["fake_markers"] == 1
    assert ev["real_tool_spans"] == 0
    assert ev["fake_tools"] == ["get_official_links"]


def test_span_evidence_reads_markers_inside_json_strings():
    ev = fakes.span_evidence({"payload": json.dumps({"_fake": True})})
    assert ev["fake_markers"] == 1


def test_fake_verified_verdicts():
    fake_ev = fakes.span_evidence(FAKE_CONV)
    real_ev = fakes.span_evidence(REAL_CONV, {"get_race_schedule"})
    assert fakes.fake_verified("fake", fake_ev) is True
    assert fakes.fake_verified("fake", real_ev) is False  # a real tool ran in fake mode
    assert fakes.fake_verified("fake", fakes.span_evidence({"turns": []})) is None
    assert fakes.fake_verified("real", fake_ev) is False


def test_run_fake_verified_needs_one_verified_and_no_contradiction():
    ok = [{"tool_mode": "fake", "fake_verified": True}, {"tool_mode": "fake", "fake_verified": None},
          {"tool_mode": "real", "fake_verified": False}]  # tools layer is always real
    assert fakes.run_fake_verified(ok, "fake") is True
    bad = ok + [{"tool_mode": "fake", "fake_verified": False}]
    assert fakes.run_fake_verified(bad, "fake") is False
    assert fakes.run_fake_verified(ok, "real") is False


# --------------------------------------------------------------------------
# ci_gate helpers
# --------------------------------------------------------------------------


def test_load_baseline_missing_or_foreign_file_is_a_warning_not_an_error(tmp_path):
    assert ci_gate.load_baseline(None) == (None, None)
    data, warn = ci_gate.load_baseline(str(tmp_path / "nope.json"))
    assert data is None and "not found" in warn
    other = tmp_path / "other.json"
    other.write_text('{"schema": "something-else"}')
    data, warn = ci_gate.load_baseline(str(other))
    assert data is None and "not a" in warn
    good = tmp_path / "good.json"
    good.write_text(json.dumps({"schema": ci_gate.SCHEMA, "pass_rate": 0.9}))
    assert ci_gate.load_baseline(str(good)) == ({"schema": ci_gate.SCHEMA, "pass_rate": 0.9}, None)


def test_load_thresholds_picks_tool_mode_section_and_drops_notes(tmp_path):
    p = tmp_path / "th.json"
    p.write_text(json.dumps({"fake": {"overall_floor": 0.8, "justification": "x", "measured_from": []}}))
    th = ci_gate.load_thresholds("fake", p)
    assert th["overall_floor"] == 0.8 and "justification" not in th
    assert ci_gate.load_thresholds("real", p)["overall_floor"] == 0.0


def test_committed_thresholds_file_has_both_modes_with_justification():
    data = json.loads(ci_gate.THRESHOLDS_PATH.read_text(encoding="utf-8"))
    for mode in ("fake", "real"):
        assert set(gate_rule.DEFAULT_THRESHOLDS) - {"aggregation"} <= set(data[mode])
        assert data[mode]["justification"].strip()


def test_committed_floors_are_positive_and_met_by_their_measurements():
    data = json.loads(ci_gate.THRESHOLDS_PATH.read_text(encoding="utf-8"))
    for mode in ("fake", "real"):
        section = data[mode]
        floors = {"overall": section["overall_floor"], **section["layer_floors"]}
        assert all(v > 0 for v in floors.values()), (mode, floors)
        assert section["measured_from"], mode
        for run in section["measured_from"]:
            for scope, floor in floors.items():
                assert run[scope] >= floor, (mode, run["run_id"], scope)


def test_select_layers_defaults_and_rejects_unknown():
    assert ci_gate.select_layers(None) == list(ci_gate.DEFAULT_LAYERS)
    assert ci_gate.select_layers("live_tools, sims") == ["tools", "sims"]
    with pytest.raises(ValueError):
        ci_gate.select_layers("tools,bogus")


def test_default_run_url_from_github_env():
    env = {"GITHUB_SERVER_URL": "https://github.com", "GITHUB_REPOSITORY": "o/r", "GITHUB_RUN_ID": "7"}
    assert ci_gate.default_run_url(env) == "https://github.com/o/r/actions/runs/7"
    assert ci_gate.default_run_url({}) is None


def test_finalize_test_relativizes_ids_redacts_text_and_sets_fake_verified():
    raw = _t(
        "live_goldens::g1",
        "PASS",
        platform_ids={"evaluation_run": f"{APP}/evaluationRuns/r1", "session_id": "s1"},
        message=f"ok for {APP}/evaluations/e1",
        metrics={"err": "project proj-x"},
    )
    out = ci_gate.finalize_test(raw, "fake", APP, fakes.span_evidence(FAKE_CONV))
    assert out["platform_ids"] == {"evaluation_run": "evaluationRuns/r1", "session_id": "sessions/s1"}
    assert out["tool_mode"] == "fake" and out["fake_verified"] is True
    assert "proj-x" not in json.dumps(out) and "app-uuid-123" not in json.dumps(out)


def test_finalize_test_keeps_layer_tool_mode_real_for_execute_tool_results():
    raw = _t("live_tools::x", "PASS", layer="live_tools", tool_mode="real", fake_verified=False)
    out = ci_gate.finalize_test(raw, "fake", APP)
    assert out["tool_mode"] == "real" and out["fake_verified"] is False


def test_redact_artifacts_rewrites_files_with_identifiers(tmp_path):
    (tmp_path / "a.json").write_text(json.dumps({"n": f"{APP}/conversations/c"}))
    (tmp_path / "b.txt").write_text("nothing to see")
    assert ci_gate.redact_artifacts(tmp_path, APP) == 1
    assert "proj-x" not in (tmp_path / "a.json").read_text()


RUN_UUID = "688aa016-1111-4222-8333-444455556666"
SESSION_UUID = "d7d875cd-79e4-4bea-8f39-8bfffb728503"


def test_redacting_stream_masks_project_and_app_but_keeps_run_and_session_uuids():
    import io

    buf = io.StringIO()
    stream = ci_gate.RedactingStream(buf, APP)
    stream.write(f"eval run: {APP}/evaluationRuns/{RUN_UUID}\n")
    stream.write(f"session: {APP}/sessions/{SESSION_UUID}\n")
    stream.write("bare app-uuid-123 and proj-x\n")
    out = buf.getvalue()
    assert f"projects/<project>/locations/us/apps/<app-id>/evaluationRuns/{RUN_UUID}" in out
    assert f"projects/<project>/locations/us/apps/<app-id>/sessions/{SESSION_UUID}" in out
    assert "proj-x" not in out and "app-uuid-123" not in out


def test_mask_text_keeps_child_uuids_and_masks_configured_ids():
    idents = {"proj-y-123": "<project>", "987654321": "<project-number>", "staging-app-uuid": "<staging-app-id>"}
    text = (
        f"projects/proj-y-123/locations/us/apps/staging-app-uuid/conversations/{SESSION_UUID} "
        f"number 987654321 other projects/zz9999/locations/eu/apps/other-app/evaluationRuns/{RUN_UUID}"
    )
    out = ids.mask_text(text, None, idents)
    assert f"projects/<project>/locations/us/apps/<staging-app-id>/conversations/{SESSION_UUID}" in out
    assert f"projects/<project>/locations/eu/apps/<app-id>/evaluationRuns/{RUN_UUID}" in out
    for secret in ("proj-y-123", "987654321", "staging-app-uuid", "zz9999", "other-app"):
        assert secret not in out


def test_main_masks_library_prints_during_the_gate(monkeypatch, capsys):
    import sys

    def fake_gate(args, app_name, layer_names, started, t0):
        # What cxas_scrapi does when the goldens layer upserts evaluations.
        print(f"Updating existing evaluation: {app_name}/evaluations/e1")
        print(f"error for {app_name}/evaluationRuns/{RUN_UUID}", file=sys.stderr)
        return 0

    monkeypatch.setattr(ci_gate, "_gate", fake_gate)
    assert ci_gate.main(["--app-name", APP, "--target", "staging"]) == 0
    captured = capsys.readouterr()
    assert "Updating existing evaluation: projects/<project>/locations/us/apps/<app-id>/evaluations/e1" in captured.out
    assert f"evaluationRuns/{RUN_UUID}" in captured.err
    assert "proj-x" not in captured.out + captured.err
    assert "app-uuid-123" not in captured.out + captured.err


# --------------------------------------------------------------------------
# records / snapshot integration
# --------------------------------------------------------------------------


def test_records_accept_ci_mode_with_draft_version():
    rec = records.build_record(
        mode="ci",
        run_id="ci-test-1",
        started_at="2026-09-29T00:00:00Z",
        finished_at="2026-09-29T00:01:00Z",
        point_time="2026-09-29T00:00:00Z",
        agent={"commit": "abc", "path": "cxas_app", "tree_hash": "t", "dirty": False,
               "dirty_paths_relevant": [], "dirty_paths_unrelated": []},
        suite={"commit": "abc", "dirty": False},
        cxas={"app": "staging", "version_id": "", "version_status": "draft", "model": "m",
              "app_update_time": None, "app_etag": ""},
        rationale="ci-gate fake on staging",
        tests=[_t("a", "PASS", tool_mode="fake")],
        extra={"app_ref": "staging", "tool_mode": "fake"},
    )
    entry = records.index_entry(rec)
    assert entry["app_ref"] == "staging" and entry["tool_mode"] == "fake"


def test_hidden_version_ids_are_discovered_from_evaluation_runs():
    versions = [{"id": "v-listed"}]
    runs = [
        {"app_version": f"{APP}/versions/v-hidden"},
        {"app_version": f"{APP}/versions/v-listed"},
        {"app_version": "v-hidden"},
        {"app_version": ""},
    ]
    assert hidden_version_ids(versions, runs) == ["v-hidden"]


# --------------------------------------------------------------------------
# no project/app identifiers in records, index or trend
# --------------------------------------------------------------------------

FAKE_CFG = {
    "gcp_project_id": "acme-secret-proj",
    "project_number": "998877665544",
    "app_id": "11111111-live-app-id",
    "staging_app_id": "22222222-stg-app-id",
    "location": "us",
}
LIVE_NAME = "projects/acme-secret-proj/locations/us/apps/11111111-live-app-id"
STG_NAME = "projects/acme-secret-proj/locations/us/apps/22222222-stg-app-id"


def _secrets_in(text: str) -> list[str]:
    return [v for k, v in FAKE_CFG.items() if k != "location" and v in text]


def _record_with_ids(run_id: str, app: str) -> dict:
    return records.build_record(
        mode="offline",
        run_id=run_id,
        started_at="2026-09-29T00:00:00Z",
        finished_at="2026-09-29T00:01:00Z",
        point_time="2026-09-29T00:00:00Z",
        agent={"commit": "abc", "path": "cxas_app", "tree_hash": "t", "dirty": False,
               "dirty_paths_relevant": [], "dirty_paths_unrelated": []},
        suite={"commit": "abc", "dirty": False},
        cxas={"app": app, "version_id": None, "version_status": "not_deployed", "model": "m",
              "app_update_time": None, "app_etag": None},
        rationale="leak test",
        tests=[_t("a", "FAIL", message=f"404 {LIVE_NAME}/tools/x in project 998877665544",
                  platform_ids={"tool": f"{STG_NAME}/tools/y"})],
    )


def test_records_index_and_trend_never_contain_configured_identifiers(tmp_path, monkeypatch):
    from totto_suite import config, trend

    monkeypatch.setattr(config, "_LOCAL_CFG", FAKE_CFG)
    for var in ("TOTTO_APP_NAME", "GCP_PROJECT_ID", "CXAS_APP_ID", "CXAS_STAGING_APP_ID"):
        monkeypatch.delenv(var, raising=False)
    runs = tmp_path / "runs"
    rec_live = _record_with_ids("r-live", LIVE_NAME)
    rec_stg = _record_with_ids("r-stg", STG_NAME)
    assert rec_live["cxas"]["app"] == "live" and rec_stg["cxas"]["app"] == "staging"
    assert rec_live["tests"][0]["platform_ids"]["tool"] == "tools/y"
    for rec in (rec_live, rec_stg):
        path = records.write_record(rec, runs)
        assert _secrets_in(path.read_text()) == []
    # A pre-scrubbing local record with raw identifiers must not leak into outputs.
    raw = dict(rec_live, run_id="r-raw", rationale=f"old record for {LIVE_NAME}")
    (runs / "r-raw.json").write_text(json.dumps(raw))
    index = records.write_index(index_path=tmp_path / "index.json", runs_dir=runs)
    assert _secrets_in(index.read_text()) == []
    info = trend.generate(
        runs_dir=runs,
        index_path=tmp_path / "index2.json",
        md_path=tmp_path / "TREND.md",
        html_path=tmp_path / "trend.html",
    )
    for p in info["paths"]:
        assert _secrets_in(Path(p).read_text()) == [], p


def test_write_record_refuses_a_record_that_still_carries_identifiers(tmp_path, monkeypatch):
    from totto_suite import config

    monkeypatch.setattr(config, "_LOCAL_CFG", FAKE_CFG)
    rec = _record_with_ids("r-bypass", LIVE_NAME)
    rec["notes"] = f"smuggled {LIVE_NAME}"  # bypasses build_record's scrubbing
    with pytest.raises(records.RecordError, match="configured identifiers"):
        records.write_record(rec, tmp_path)
