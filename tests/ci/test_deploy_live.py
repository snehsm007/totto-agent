"""Unit tests for scripts/ci/deploy_live.py orchestration (fake backend, no CXAS)."""

from __future__ import annotations

import importlib.util
import io
import json
from pathlib import Path
import sys
import zipfile

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
CI_DIR = REPO_ROOT / "scripts" / "ci"
if str(CI_DIR) not in sys.path:
    sys.path.insert(0, str(CI_DIR))


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, CI_DIR / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


deploy_live = _load("deploy_live")

PROJECT = "proj-secret-1"
APP = f"projects/{PROJECT}/locations/us/apps/live-app-uuid"
SHA = "0123456789abcdef0123456789abcdef01234567"
RUN_URL = "https://github.com/o/r/actions/runs/42"
MAIN_ENV = {"GITHUB_REF": "refs/heads/main"}
REDACT = {PROJECT: "<project>", "live-app-uuid": "<live-app>"}


def _write_app(root: Path, instruction: str) -> Path:
    (root / "agents" / "a").mkdir(parents=True)
    (root / "app.json").write_text(
        json.dumps({"displayName": "totto-mercedes-f1-fan-agent", "rootAgent": "a"}), encoding="utf-8"
    )
    (root / "agents" / "a" / "a.json").write_text(
        json.dumps({"displayName": "a", "instruction": "agents/a/instruction.txt"}), encoding="utf-8"
    )
    (root / "agents" / "a" / "instruction.txt").write_text(instruction, encoding="utf-8")
    return root


def _zip_tree(root: Path, server_name: str = "live display") -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for p in sorted(root.rglob("*")):
            if p.is_file():
                rel = p.relative_to(root).as_posix()
                data = p.read_bytes()
                if rel == "app.json":
                    obj = json.loads(data)
                    obj["displayName"] = server_name  # the server keeps the live name
                    obj["name"] = "live-app-uuid"
                    data = json.dumps(obj).encode()
                z.writestr(f"{server_name}/{rel}", data)
    return buf.getvalue()


class FakeBackend:
    """In-memory stand-in for CES: the live app is a directory tree."""

    def __init__(self, live_dir: Path, deployments: list[dict] | None = None):
        self.live_dir = live_dir
        self.calls: list[str] = []
        self.versions: dict[str, dict] = {}
        self.deployments = {d["name"]: dict(d) for d in (deployments or [])}
        self.fail_push = False
        self.ignore_patch = False
        self.wrong_version_name = False
        self.pushed_description = None

    def export_app(self) -> bytes:
        self.calls.append("export")
        return _zip_tree(self.live_dir)

    def push(self, src_dir: Path, display: str, description: str) -> str:
        self.calls.append("push")
        if self.fail_push:
            raise RuntimeError(f"cxas push exited 1 for {APP}")
        self.live_dir = Path(src_dir)
        self.pushed_description = description
        name = f"{APP}/versions/v-new"
        self.versions[name] = {
            "name": name,
            "id": "v-new",
            "display_name": "other" if self.wrong_version_name else display,
            "description": description,
            "create_time": "2026-09-29T21:00:00.000000Z",
        }
        return name

    def get_version(self, version_name: str) -> dict:
        self.calls.append("get_version")
        return self.versions[version_name]

    def list_deployments(self) -> list[dict]:
        self.calls.append("list_deployments")
        return [dict(d) for d in self.deployments.values()]

    def set_deployment_version(self, name: str, version: str) -> dict:
        self.calls.append(f"set:{name.rsplit('/', 1)[-1]}")
        if not self.ignore_patch:
            self.deployments[name]["app_version"] = version
        return dict(self.deployments[name])

    def get_deployment(self, name: str) -> dict:
        self.calls.append(f"get:{name.rsplit('/', 1)[-1]}")
        return dict(self.deployments[name])


def _deps() -> list[dict]:
    return [
        {
            "name": f"{APP}/deployments/phone-1",
            "display_name": "phone",
            "channel_type": "GOOGLE_TELEPHONY_PLATFORM",
            "app_version": f"{APP}/versions/v-old",
        },
        {
            "name": f"{APP}/deployments/web-1",
            "display_name": "web",
            "channel_type": "WEB_UI",
            "app_version": f"{APP}/versions/v-old",
        },
    ]


@pytest.fixture()
def apps(tmp_path: Path) -> tuple[Path, Path]:
    before = _write_app(tmp_path / "live_before", "old instruction\n")
    repo = _write_app(tmp_path / "repo_app", "new instruction\n")
    return before, repo


def _run(backend, repo: Path, out: Path, **kw):
    params = dict(
        src_dir=repo, out_dir=out, commit=SHA, run_url=RUN_URL, gate_run_id="ci-42",
        gate_verdict="PASS", env=MAIN_ENV, redact_terms=REDACT,
    )
    params.update(kw)
    return deploy_live.run_deploy_live(backend, **params)


def test_happy_path_versions_snapshots_repoints_phone_and_records(apps, tmp_path: Path) -> None:
    before, repo = apps
    backend = FakeBackend(before, _deps())
    out = tmp_path / "out"
    code, record = _run(backend, repo, out)

    assert code == deploy_live.EXIT_OK, record
    assert record["ok"] is True and record["status"] == "SUCCESS"
    assert backend.calls == [
        "export", "push", "get_version", "export", "list_deployments", "set:phone-1", "get:phone-1",
    ]
    # Version linked to the commit, run and staging gate.
    assert record["version"]["id"] == "versions/v-new"
    assert record["version"]["display_name"] == "git-0123456"
    assert record["version"]["verified"] is True
    assert backend.pushed_description == f"commit {SHA} | run {RUN_URL} | staging gate ci-42"
    # Before/after snapshots + normalized diff show the instruction change.
    assert (out / "before" / "app" / "agents" / "a" / "instruction.txt").read_text() == "old instruction\n"
    assert (out / "after" / "app" / "agents" / "a" / "instruction.txt").read_text() == "new instruction\n"
    assert record["diff"]["identical"] is False
    assert record["diff"]["changed_files"] == ["agents/a/instruction.txt"]
    assert "+new instruction" in (out / "diff.md").read_text()
    assert record["snapshots"]["before"]["tree_hash"] != record["snapshots"]["after"]["tree_hash"]
    assert record["agent_content_matches_repo"] is True
    # Only the telephony deployment is repointed; web stays.
    assert record["phone_deployments"] == [
        {
            "deployment": "deployments/phone-1",
            "display_name": "phone",
            "channel_type": "GOOGLE_TELEPHONY_PLATFORM",
            "previous_version": "versions/v-old",
            "new_version": "versions/v-new",
            "verified": True,
        }
    ]
    assert backend.deployments[f"{APP}/deployments/web-1"]["app_version"].endswith("v-old")
    # deploy.json on disk equals the record and holds no identifiers.
    written = (out / "deploy.json").read_text(encoding="utf-8")
    assert json.loads(written) == record
    for text in (written, (out / "diff.md").read_text(), (out / "diff.json").read_text()):
        assert PROJECT not in text and "live-app-uuid" not in text
    assert record["commit"] == SHA and record["run_url"] == RUN_URL
    assert record["staging_gate"] == {"run_id": "ci-42", "verdict": "PASS"}


@pytest.mark.parametrize("ref", ["", "refs/heads/feature", "refs/pull/3/merge"])
def test_refuses_outside_main_without_touching_cxas(apps, tmp_path: Path, ref: str) -> None:
    before, repo = apps
    backend = FakeBackend(before, _deps())
    code, record = _run(backend, repo, tmp_path / "out", env={"GITHUB_REF": ref})
    assert code == deploy_live.EXIT_REFUSED
    assert record["failed_step"] == "guard" and record["status"] == "REFUSED"
    assert backend.calls == []
    assert not (tmp_path / "out").exists()


def test_allow_non_main_flag_lets_tests_run_the_flow(apps, tmp_path: Path) -> None:
    before, repo = apps
    code, record = _run(
        FakeBackend(before, []), repo, tmp_path / "out", env={"GITHUB_REF": "refs/heads/x"},
        allow_non_main=True,
    )
    assert code == 0 and record["ok"] and record["ref"] == "refs/heads/x"


@pytest.mark.parametrize("verdict", ["FAIL", "INCONCLUSIVE", ""])
def test_refuses_unless_staging_gate_passed(apps, tmp_path: Path, verdict: str) -> None:
    before, repo = apps
    backend = FakeBackend(before, _deps())
    code, record = _run(backend, repo, tmp_path / "out", gate_verdict=verdict)
    assert code == deploy_live.EXIT_REFUSED
    assert "not PASS" in record["error"]
    assert backend.calls == []


def test_push_failure_is_recorded_with_before_snapshot_and_redacted_error(apps, tmp_path: Path) -> None:
    before, repo = apps
    backend = FakeBackend(before, _deps())
    backend.fail_push = True
    out = tmp_path / "out"
    code, record = _run(backend, repo, out)
    assert code == deploy_live.EXIT_FAILED
    assert record["ok"] is False and record["failed_step"] == "push" and record["status"] == "FAILED"
    assert record["snapshots"]["before"]["path"] == "before/app"
    assert PROJECT not in record["error"] and "<project>" in record["error"]
    assert json.loads((out / "deploy.json").read_text())["failed_step"] == "push"
    assert "list_deployments" not in backend.calls


def test_version_display_name_mismatch_fails_verification(apps, tmp_path: Path) -> None:
    before, repo = apps
    backend = FakeBackend(before, _deps())
    backend.wrong_version_name = True
    code, record = _run(backend, repo, tmp_path / "out")
    assert code == deploy_live.EXIT_FAILED
    assert record["failed_step"] == "verify_version"
    assert "list_deployments" not in backend.calls


def test_phone_repoint_that_does_not_stick_fails(apps, tmp_path: Path) -> None:
    before, repo = apps
    backend = FakeBackend(before, _deps())
    backend.ignore_patch = True
    code, record = _run(backend, repo, tmp_path / "out")
    assert code == deploy_live.EXIT_FAILED
    assert record["failed_step"] == "repoint"
    assert "still points at versions/v-old" in record["error"]
    # The partial phone state is kept in the record.
    assert record["phone_deployments"][0]["deployment"] == "deployments/phone-1"
    assert record["phone_deployments"][0]["verified"] is False
    # The version was created and verified before the repoint failed.
    assert record["version"]["verified"] is True


def test_no_phone_deployment_is_ok_and_recorded_empty(apps, tmp_path: Path) -> None:
    before, repo = apps
    code, record = _run(FakeBackend(before, _deps()[1:]), repo, tmp_path / "out")
    assert code == 0 and record["phone_deployments"] == []


def test_phone_already_on_new_version_is_verified_without_patch(apps, tmp_path: Path) -> None:
    before, repo = apps
    deps = _deps()[:1]
    deps[0]["app_version"] = f"{APP}/versions/v-new"
    backend = FakeBackend(before, deps)
    code, record = _run(backend, repo, tmp_path / "out")
    assert code == 0
    assert "set:phone-1" not in backend.calls and "get:phone-1" in backend.calls
    assert record["phone_deployments"][0]["verified"] is True


def test_identical_push_reports_identical_diff(tmp_path: Path) -> None:
    repo = _write_app(tmp_path / "repo_app", "same\n")
    code, record = _run(FakeBackend(repo, []), repo, tmp_path / "out")
    assert code == 0 and record["diff"]["identical"] is True and record["diff"]["changed_files"] == []


def test_version_naming_helpers() -> None:
    assert deploy_live.version_display_name(SHA) == "git-0123456"
    assert deploy_live.version_description(SHA, RUN_URL, "ci-1") == (
        f"commit {SHA} | run {RUN_URL} | staging gate ci-1"
    )


def test_cli_refuses_off_main_before_resolving_app(monkeypatch, capsys) -> None:
    monkeypatch.setenv("GITHUB_REF", "refs/heads/feature")
    monkeypatch.setattr(
        deploy_live.push_app, "resolve_app_name", lambda target: pytest.fail("must not resolve")
    )
    assert deploy_live.main(["--gate-run-id", "ci-1", "--gate-verdict", "PASS"]) == deploy_live.EXIT_REFUSED
    assert "REFUSED" in capsys.readouterr().err
