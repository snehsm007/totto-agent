"""Hermetic self-tests for Milestone M4: mutants, pre-commit gate, push-disabled deploy, backfill & Makefile."""

from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import stat
from typing import Any

import pytest

from totto_suite import backfill, config, cxasapi, deploy, gate, mutants, records


def test_mutant_specs_catalogue_and_temp_isolation(tmp_path: Path) -> None:
    """Verify >=10 mutants across tools, callbacks, and config, and that each mutator works in isolation."""
    specs = mutants.MUTANT_SPECS
    assert len(specs) >= 10
    categories = {s.category for s in specs}
    assert {"tools", "callbacks", "config"}.issubset(categories)
    assert sum(1 for s in specs if s.category == "tools") >= 4
    assert sum(1 for s in specs if s.category == "callbacks") >= 2
    assert sum(1 for s in specs if s.category == "config") >= 3

    before_hash = cxasapi.app_tree_hash(config.DEFAULT_APP_DIR)
    for spec in specs:
        target_copy = tmp_path / spec.mutant_id / "cxas_app"
        shutil.copytree(config.DEFAULT_APP_DIR, target_copy)
        spec.mutate(target_copy)
        # Ensure mutation actually changed the temp copy
        changed = False
        for rel in spec.target_files:
            orig_bytes = (config.DEFAULT_APP_DIR / rel).read_bytes()
            mut_bytes = (target_copy / rel).read_bytes()
            if orig_bytes != mut_bytes:
                changed = True
                break
        assert changed, f"Mutant {spec.mutant_id} did not modify any of {spec.target_files}"

    after_hash = cxasapi.app_tree_hash(config.DEFAULT_APP_DIR)
    assert before_hash == after_hash, "Mutators must never touch <repo>/cxas_app in-place"


def test_mutants_report_artifacts_and_100_percent_kill_rate() -> None:
    """Verify generated mutants_report.json and mutants_report.md show 100% kill rate."""
    json_path = config.HISTORY_DIR / "mutants" / "mutants_report.json"
    md_path = config.HISTORY_DIR / "mutants" / "mutants_report.md"
    assert json_path.is_file(), "Missing evals/history/mutants/mutants_report.json"
    assert md_path.is_file(), "Missing evals/history/mutants/mutants_report.md"

    report = json.loads(json_path.read_text(encoding="utf-8"))
    summary = report["summary"]
    assert summary["total_mutants"] >= 10
    assert summary["killed"] == summary["total_mutants"]
    assert summary["survived"] == 0
    assert summary["kill_rate"] == 1.0

    for m in report["mutants"]:
        assert m["killed"] is True, f"Mutant {m['mutant_id']} survived!"
        assert m["killed_by_count"] >= 1
        assert len(m["killed_by_scenarios"]) == m["killed_by_count"]

    md_text = md_path.read_text(encoding="utf-8")
    assert "100.0%" in md_text
    for spec in mutants.MUTANT_SPECS:
        assert spec.mutant_id in md_text


def test_precommit_hook_and_gate_demo_log() -> None:
    """Verify hooks/pre-commit is executable and gate_demo.log proves both block and allow paths."""
    hook_path = config.REPO_ROOT / "hooks" / "pre-commit"
    assert hook_path.is_file()
    mode = hook_path.stat().st_mode
    assert bool(mode & stat.S_IXUSR), "hooks/pre-commit must be executable"
    hook_text = hook_path.read_text(encoding="utf-8")
    assert "totto_suite gate" in hook_text

    demo_log = config.HISTORY_DIR / "gate" / "gate_demo.log"
    assert demo_log.is_file(), "Missing evals/history/gate/gate_demo.log"
    log_text = demo_log.read_text(encoding="utf-8")
    assert "git commit exit code on broken change: 1" in log_text
    assert "RESULT: BLOCKED" in log_text
    assert "git commit exit code on clean change: 0" in log_text
    assert "RESULT: PASSED" in log_text


def test_gate_decision_d2_blocks_regression_and_allows_clean(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Verify gate.evaluate_gate implements Decision D2 (blocks on PASS->FAIL or lint failure, allows existing FAIL->FAIL)."""
    fake_app = tmp_path / "cxas_app"
    fake_app.mkdir()
    (fake_app / "app.json").write_text('{"rootAgent": "totto_root_agent"}\n', encoding="utf-8")

    baseline_map = {
        "lint::cxas_lint": "PASS",
        "tools::test_standings": "PASS",
        "tools::test_known_agent_defect": "FAIL",
        "selftest::test_suite": "PASS",
    }

    monkeypatch.setattr(
        gate,
        "_resolve_baseline_tests",
        lambda **kwargs: (baseline_map, "mock_baseline"),
    )

    # 1. Clean candidate (known FAIL->FAIL stays FAIL, all PASS stay PASS) -> PASSED (exit 0)
    clean_candidate = [
        {"id": "lint::cxas_lint", "layer": "lint", "status": "PASS", "repeat": 1, "message": ""},
        {"id": "tools::test_standings", "layer": "tools", "status": "PASS", "repeat": 1, "message": ""},
        {"id": "tools::test_known_agent_defect", "layer": "tools", "status": "FAIL", "repeat": 1, "message": "known"},
        {"id": "selftest::test_suite", "layer": "selftest", "status": "PASS", "repeat": 1, "message": ""},
    ]
    monkeypatch.setattr(
        gate,
        "_run_offline_layers_on_dir",
        lambda app_dir, repo_root, layer_names: (clean_candidate, []),
    )
    res_clean = gate.evaluate_gate(app_dir=fake_app, repo_root=tmp_path)
    assert res_clean["passed"] is True
    assert res_clean["exit_code"] == 0
    assert len(res_clean["regressions"]) == 0
    assert len(res_clean["existing_failures"]) == 1

    # 2. Regressed candidate (tools::test_standings flips PASS -> FAIL) -> BLOCKED (exit 1)
    regressed_candidate = [
        {"id": "lint::cxas_lint", "layer": "lint", "status": "PASS", "repeat": 1, "message": ""},
        {"id": "tools::test_standings", "layer": "tools", "status": "FAIL", "repeat": 1, "message": "AssertionError"},
        {"id": "tools::test_known_agent_defect", "layer": "tools", "status": "FAIL", "repeat": 1, "message": "known"},
        {"id": "selftest::test_suite", "layer": "selftest", "status": "PASS", "repeat": 1, "message": ""},
    ]
    monkeypatch.setattr(
        gate,
        "_run_offline_layers_on_dir",
        lambda app_dir, repo_root, layer_names: (regressed_candidate, []),
    )
    res_reg = gate.evaluate_gate(app_dir=fake_app, repo_root=tmp_path)
    assert res_reg["passed"] is False
    assert res_reg["exit_code"] == 1
    assert len(res_reg["regressions"]) == 1
    assert res_reg["regressions"][0]["id"] == "tools::test_standings"


def test_deploy_enforces_r5_no_push_and_records_version_snapshot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Verify deploy hard-blocks --push (R5) and records a schema-v1 deploy record with --no-push."""
    # 1. --push must be blocked immediately with exit code 2
    blocked = deploy.run_deploy(rationale="attempt push", push=True)
    assert blocked["ok"] is False
    assert blocked["exit_code"] == deploy.EXIT_DEPLOY_BLOCKED
    assert blocked["push_performed"] is False
    assert "deploy-live" in blocked["error"]
    assert deploy.main(["--rationale", "attempt push", "--push"]) == deploy.EXIT_DEPLOY_BLOCKED

    # 2. Mocked gate + mocked cxas_client produces valid schema-v1 deploy record
    monkeypatch.setattr(
        gate,
        "evaluate_gate",
        lambda **kwargs: {
            "passed": True,
            "exit_code": 0,
            "candidate_app_dir": "cxas_app",
            "baseline_source": "mock_head",
            "duration_s": 0.1,
            "layers": {"lint": {"pass": 2, "fail": 0, "infra_error": 0, "skipped": 0, "score": 1.0}},
            "total_tests": 2,
            "regressions": [],
            "existing_failures": [],
            "lint_failures": [],
            "selftest_failures": [],
            "all_failures": [],
            "blocking_reasons": [],
            "tests": [
                {"id": "lint::cxas_lint", "layer": "lint", "status": "PASS", "repeat": 1, "message": ""},
                {"id": "lint::bundle_shared_imports", "layer": "lint", "status": "PASS", "repeat": 1, "message": ""},
            ],
        },
    )

    class FakeCxasClient:
        def get_app(self, app_name: str) -> dict[str, Any]:
            return {
                "update_time": "2026-09-28T20:55:38.643615Z",
                "etag": "etag-123",
                "raw": {"modelSettings": {"model": "gemini-3.0-flash-001"}},
            }

        def create_version(self, display_name: str, description: str, app_name: str) -> dict[str, Any]:
            return {
                "id": "11111111-2222-3333-4444-555555555555",
                "name": f"{app_name}/versions/11111111-2222-3333-4444-555555555555",
                "display_name": display_name,
                "create_time": "2026-09-28T23:30:00.000000Z",
            }

        def get_version(self, version_id: str, app_name: str) -> dict[str, Any]:
            return {
                "id": version_id,
                "name": f"{app_name}/versions/{version_id}",
                "display_name": "mock",
            }

        def list_versions(self, app_name: str) -> list[dict[str, Any]]:
            return [{"id": "11111111-2222-3333-4444-555555555555"}]

    res = deploy.run_deploy(
        rationale="Unit test push-disabled deploy",
        app_dir=config.DEFAULT_APP_DIR,
        repo_root=config.REPO_ROOT,
        record_run=False,
        cxas_client=FakeCxasClient(),
    )
    assert res["ok"] is True
    assert res["exit_code"] == 0
    assert res["push_performed"] is False
    assert res["version_id"] == "11111111-2222-3333-4444-555555555555"
    assert res["version_status"] == "in_version_list"
    records.validate(res["record"])


def test_real_deploy_and_backfilled_records_exist_and_validate() -> None:
    """Verify all 6 backfilled records + real deploy record exist in evals/history/runs/ and pass schema validation."""
    all_recs = records.load_all()
    by_id = {r["run_id"]: r for r in all_recs}

    expected_backfill_ids = {
        "20260928T171430Z_reproduced_bdb8f3b": ("reproduced", False),
        "20260928T172142Z_reproduced_1a17988": ("reproduced", False),
        "20260928T181007Z_reproduced_a7c3094": ("reproduced", False),
        "20260928T184131Z_imported_a7c3094": ("imported", True),
        "20260928T191853Z_imported_a7c3094": ("imported", True),
        "20260928T205030Z_imported_f073e02": ("imported", True),
    }
    for run_id, (exp_mode, exp_imported) in expected_backfill_ids.items():
        assert run_id in by_id, f"Missing backfilled run record {run_id}"
        rec = by_id[run_id]
        records.validate(rec)
        assert rec["mode"] == exp_mode
        assert rec["imported"] is exp_imported
        assert len(rec["tests"]) > 0

    # Verify quota INFRA_ERROR separation in 184131 imported record
    rec_1841 = by_id["20260928T184131Z_imported_a7c3094"]
    assert rec_1841["infra_errors"]["count"] > 0
    assert rec_1841["infra_errors"]["by_kind"].get("quota", 0) > 0

    # Verify at least one real deploy record exists with fetchable CXAS version ID
    deploy_recs = [r for r in all_recs if r["mode"] == "deploy"]
    assert len(deploy_recs) >= 1, "Expected at least one mode='deploy' record in evals/history/runs/"
    latest_deploy = deploy_recs[-1]
    assert latest_deploy["cxas"]["version_id"]
    assert latest_deploy["cxas"]["version_status"] in ("in_version_list", "hidden_fetchable")
    assert latest_deploy["deploy"]["push_performed"] is False
    assert latest_deploy["deploy"]["get_version_ok"] is True

    # Verify trend artifacts exist and contain all records
    assert config.INDEX_PATH.is_file()
    assert config.TREND_MD_PATH.is_file()
    assert config.TREND_HTML_PATH.is_file()
    md_text = config.TREND_MD_PATH.read_text(encoding="utf-8")
    assert "REGRESSION" in md_text


def test_makefile_safe_targets() -> None:
    """Verify Makefile exposes the suite targets, setup/hooks, and no live-push target."""
    makefile_text = (config.REPO_ROOT / "Makefile").read_text(encoding="utf-8")
    for target in (
        "offline:", "live:", "trend:", "gate:", "backfill:", "mutants:", "acceptance:",
        "setup:", "hooks:", "push-staging:", "ci-offline:",
    ):
        assert target in makefile_text, f"Missing target {target} in Makefile"
    assert "git config core.hooksPath hooks" in makefile_text
    assert "scripts/ci/push_app.py --target staging" in makefile_text
    # Live changes only via the gated CI deploy-live job.
    assert "--target live" not in makefile_text
    assert "deploy_live.py" not in makefile_text
