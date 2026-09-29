"""Structural checks of .github/workflows/ci.yml and its helper scripts.

`act` is not available, so these tests pin the properties the acceptance
criteria depend on (job graph, gate step name, SHA pins, main-only live
deploy, no identifiers) and run the helper scripts directly.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import re
import subprocess

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS = REPO_ROOT / ".github" / "workflows"
CI = WORKFLOWS / "ci.yml"
CI_DIR = REPO_ROOT / "scripts" / "ci"


@pytest.fixture(scope="module")
def wf() -> dict:
    return yaml.safe_load(CI.read_text(encoding="utf-8"))


def _steps(wf: dict, job: str) -> list[dict]:
    return wf["jobs"][job]["steps"]


def _step(wf: dict, job: str, name: str) -> dict:
    matches = [s for s in _steps(wf, job) if s.get("name") == name]
    assert len(matches) == 1, f"{job}: expected one step named {name!r}"
    return matches[0]


def test_ci_is_the_only_workflow() -> None:
    assert sorted(p.name for p in WORKFLOWS.glob("*.y*ml")) == ["ci.yml"]


def test_triggers_every_push_pull_request_and_dispatch(wf: dict) -> None:
    on = wf.get("on", wf.get(True))  # PyYAML reads the bare key `on` as True
    assert on["push"]["branches"] == ["**"]
    assert "pull_request" in on and "workflow_dispatch" in on


def test_job_graph(wf: dict) -> None:
    jobs = wf["jobs"]
    assert set(jobs) == {"offline", "staging-gate", "deploy-live", "publish-dashboard"}
    # The staging gate must not wait for offline, so a prompt-only regression
    # is reported by the CXAS eval gate step.
    assert "needs" not in jobs["staging-gate"]
    assert jobs["deploy-live"]["needs"] == ["offline", "staging-gate"]
    assert jobs["publish-dashboard"]["needs"] == ["staging-gate", "deploy-live"]
    for name, job in jobs.items():
        assert job.get("timeout-minutes"), f"{name} has no timeout"


def test_deploy_live_only_on_main_push(wf: dict) -> None:
    job = wf["jobs"]["deploy-live"]
    assert job["if"].replace(" ", "") == "${{github.event_name=='push'&&github.ref=='refs/heads/main'}}"
    assert job["concurrency"] == {"group": "cxas-live", "cancel-in-progress": False}
    assert job["permissions"]["id-token"] == "write"
    run = _step(wf, "deploy-live", "Deploy to live (version, snapshots, phone)")["run"]
    assert "scripts/ci/deploy_live.py" in run and "--allow-non-main" not in run
    assert "--gate-verdict" in run and "--gate-run-id" in run


def test_publish_dashboard_runs_always_on_main(wf: dict) -> None:
    job = wf["jobs"]["publish-dashboard"]
    cond = job["if"].replace(" ", "")
    assert cond.startswith("${{always()&&") and "refs/heads/main" in cond and "'push'" in cond
    assert job["permissions"] == {"contents": "write"}
    env = _step(wf, "publish-dashboard", "Publish dashboard branch")["env"]
    assert "needs.staging-gate.result == 'success'" in env["DASHBOARD_UPDATE_BASELINE"]


def test_staging_gate_steps_and_order(wf: dict) -> None:
    job = wf["jobs"]["staging-gate"]
    assert job["permissions"] == {"contents": "read", "id-token": "write"}
    assert job["concurrency"] == {"group": "cxas-staging", "cancel-in-progress": False}
    names = [s.get("name") for s in job["steps"]]
    order = [
        "Check repo variables",
        "Authenticate to Google Cloud (WIF, no key)",
        "Deploy to staging",
        "Fetch main baseline (dashboard branch)",
        "CXAS eval gate",
        "Verify platform IDs",
        "Platform IDs (app-relative)",
        "Upload gate summary",
    ]
    assert [n for n in names if n in order] == order
    gate = _step(wf, "staging-gate", "CXAS eval gate")
    assert gate["id"] == "gate"
    assert "ci-gate --target staging" in gate["run"] and "--tool-mode fake" in gate["run"]
    assert "--baseline baseline.json" in gate["run"] and 'exit "$rc"' in gate["run"]
    assert "totto_suite verify-ids" in _step(wf, "staging-gate", "Verify platform IDs")["run"]
    assert "push_app.py --target staging" in _step(wf, "staging-gate", "Deploy to staging")["run"]
    upload = _step(wf, "staging-gate", "Upload gate summary")
    assert upload["with"]["name"] == "gate-summary"  # name the dashboard job downloads


def test_auth_uses_repo_variables_and_no_key(wf: dict) -> None:
    text = CI.read_text(encoding="utf-8")
    assert "credentials_json" not in text
    for job in ("staging-gate", "deploy-live"):
        auth = _step(wf, job, "Authenticate to Google Cloud (WIF, no key)")
        assert auth["with"] == {
            "workload_identity_provider": "${{ vars.GCP_WIF_PROVIDER }}",
            "service_account": "${{ vars.GCP_CI_SERVICE_ACCOUNT }}",
        }
        check = _step(wf, job, "Check repo variables")
        assert check["run"] == "bash scripts/ci/check_repo_vars.sh"


def test_every_action_is_pinned_to_a_commit_sha(wf: dict) -> None:
    uses = [s["uses"] for job in wf["jobs"].values() for s in job["steps"] if "uses" in s]
    assert uses
    for ref in uses:
        assert re.fullmatch(r"[\w.-]+/[\w.-]+@[0-9a-f]{40}", ref), ref


def test_python_312_with_pip_cache(wf: dict) -> None:
    assert wf["env"]["PYTHON_VERSION"] == "3.12"
    for job in ("offline", "staging-gate", "deploy-live"):
        setup = _step(wf, job, "Set up Python")
        assert setup["with"]["cache"] == "pip"
        assert _step(wf, job, "Install (pip install -e .)")["run"] == "python -m pip install -e ."


def test_offline_job_runs_every_local_check(wf: dict) -> None:
    runs = " && ".join(s.get("run", "") for s in _steps(wf, "offline"))
    for cmd in (
        "bundle_shared_imports.py --check",
        "cxas lint --app-dir cxas_app",
        "python -m pytest",
        "totto_suite offline",
        "totto_suite mutants",
    ):
        assert cmd in runs


def test_workflow_holds_no_identifiers() -> None:
    text = CI.read_text(encoding="utf-8")
    assert not re.search(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", text)
    assert not re.search(r"projects/\d+", text)
    assert "iam.gserviceaccount.com" not in text
    cfg_path = REPO_ROOT / "gecx-config.json"
    if cfg_path.is_file():
        cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
        for key in ("gcp_project_id", "project_number", "app_id", "staging_app_id", "eval_audio_bucket"):
            if cfg.get(key):
                for path in [CI, *CI_DIR.iterdir()]:
                    if path.is_file():
                        assert str(cfg[key]) not in path.read_text(encoding="utf-8"), (key, path)


def test_no_commit_back_to_main(wf: dict) -> None:
    runs = "\n".join(s.get("run", "") for job in wf["jobs"].values() for s in job["steps"])
    assert "git push" not in runs and "git commit" not in runs


# --------------------------------------------------------------------------
# check_repo_vars.sh
# --------------------------------------------------------------------------

GOOD = {
    "WIF_PROVIDER": "projects/123456/locations/global/workloadIdentityPools/pool/providers/prov",
    "CI_SA": "ci-bot@my-proj-1.iam.gserviceaccount.com",
    "LIVE_APP_ID": "11111111-2222-3333-4444-555555555555",
    "STAGING_APP_ID": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
}


def _check_vars(tmp_path: Path, **overrides: str) -> tuple[subprocess.CompletedProcess, str]:
    env_file = tmp_path / "github_env"
    env_file.write_text("", encoding="utf-8")
    env = {k: v for k, v in os.environ.items() if k not in GOOD}
    env.update(GOOD)
    env.update(overrides)
    env["GITHUB_ENV"] = str(env_file)
    env["CXAS_LOCATION"] = "us"
    res = subprocess.run(
        ["bash", str(CI_DIR / "check_repo_vars.sh")], env=env, capture_output=True, text=True
    )
    return res, env_file.read_text(encoding="utf-8")


def test_check_repo_vars_exports_names_and_masks_project(tmp_path: Path) -> None:
    res, exported = _check_vars(tmp_path)
    assert res.returncode == 0, res.stdout + res.stderr
    assert "::add-mask::my-proj-1" in res.stdout and "::add-mask::123456" in res.stdout
    assert "GCP_PROJECT_ID=my-proj-1" in exported
    assert "GCP_PROJECT_NUMBER=123456" in exported
    assert (
        "STAGING_APP_NAME=projects/my-proj-1/locations/us/apps/aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
        in exported
    )


def test_check_repo_vars_lists_every_missing_variable(tmp_path: Path) -> None:
    res, exported = _check_vars(tmp_path, WIF_PROVIDER="", STAGING_APP_ID="")
    assert res.returncode == 1 and exported == ""
    assert "GCP_WIF_PROVIDER" in res.stdout and "CXAS_STAGING_APP_ID" in res.stdout
    assert "::error" in res.stdout


@pytest.mark.parametrize(
    "overrides,title",
    [
        ({"WIF_PROVIDER": "projects/p/locations/global/workloadIdentityPools/x"}, "Bad GCP_WIF_PROVIDER"),
        ({"CI_SA": "someone@example.com"}, "Bad GCP_CI_SERVICE_ACCOUNT"),
        ({"LIVE_APP_ID": "projects/x/locations/us/apps/y"}, "Bad CXAS_LIVE_APP_ID"),
        ({"STAGING_APP_ID": GOOD["LIVE_APP_ID"]}, "must differ"),
    ],
)
def test_check_repo_vars_rejects_malformed_values(tmp_path: Path, overrides, title) -> None:
    res, exported = _check_vars(tmp_path, **overrides)
    assert res.returncode == 1 and exported == ""
    assert title in res.stdout


# --------------------------------------------------------------------------
# print_gate_ids.py
# --------------------------------------------------------------------------


def test_print_gate_ids_shows_app_relative_ids_only(tmp_path: Path) -> None:
    summary = {
        "verdict": "PASS",
        "commit": "0123456789",
        "run_id": "ci-1-1",
        "tool_mode": "fake",
        "fake_verified": True,
        "pass_rate": 0.9,
        "baseline_pass_rate": None,
        "reasons": ["floors only"],
        "tests": [
            {
                "id": "golden::next_race",
                "layer": "goldens",
                "status": "PASS",
                "tool_mode": "fake",
                "platform_ids": {
                    "evaluation_run": "evaluationRuns/r-1",
                    "session_id": ["projects/p9/locations/us/apps/a9/sessions/s-1"],
                },
            }
        ],
    }
    path = tmp_path / "gate_summary.json"
    path.write_text(json.dumps(summary), encoding="utf-8")
    res = subprocess.run(
        ["python3", str(CI_DIR / "print_gate_ids.py"), str(path)], capture_output=True, text=True
    )
    assert res.returncode == 0, res.stderr
    assert "evaluationRuns/r-1" in res.stdout and "sessions/s-1" in res.stdout
    assert "p9" not in res.stdout and "apps/a9" not in res.stdout
    assert "CXAS eval gate: PASS" in res.stdout and "2 platform IDs recorded." in res.stdout
