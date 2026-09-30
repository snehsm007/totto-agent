"""Unit tests for scripts/ci/push_app.py (no CXAS calls: the push runner is faked)."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
CI_DIR = REPO_ROOT / "scripts" / "ci"


def _load(name: str):
    if str(CI_DIR) not in sys.path:
        sys.path.insert(0, str(CI_DIR))
    spec = importlib.util.spec_from_file_location(name, CI_DIR / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


push_app = _load("push_app")

APP = "projects/proj-x/locations/us/apps/app-1234"


@pytest.fixture()
def src_app(tmp_path: Path) -> Path:
    src = tmp_path / "src" / "cxas_app"
    (src / "agents" / "a" / "__pycache__").mkdir(parents=True)
    (src / "agents" / "a" / "instruction.txt").write_text("hi\n", encoding="utf-8")
    (src / "agents" / "a" / "__pycache__" / "x.cpython-312.pyc").write_bytes(b"\0")
    (src / "gecx-config.json").write_text('{"gcp_project_id": "proj-x"}', encoding="utf-8")
    (src / "app.json").write_text(
        json.dumps({"displayName": "totto-mercedes-f1-fan-agent", "rootAgent": "a"}),
        encoding="utf-8",
    )
    return src


def test_resolve_app_name_prefers_env_over_local_config() -> None:
    env = {"GCP_PROJECT_ID": "p-env", "CXAS_STAGING_APP_ID": "s-env", "CXAS_LIVE_APP_ID": "l-env"}
    cfg = {"gcp_project_id": "p-cfg", "staging_app_id": "s-cfg", "app_id": "l-cfg", "location": "eu"}
    assert push_app.resolve_app_name("staging", env, cfg) == "projects/p-env/locations/eu/apps/s-env"
    assert push_app.resolve_app_name("live", env, cfg) == "projects/p-env/locations/eu/apps/l-env"


def test_resolve_app_name_falls_back_to_local_config_and_default_location() -> None:
    cfg = {"gcp_project_id": "p-cfg", "staging_app_id": "s-cfg"}
    assert push_app.resolve_app_name("staging", {}, cfg) == "projects/p-cfg/locations/us/apps/s-cfg"


def test_resolve_app_name_uses_google_cloud_project_from_auth_action() -> None:
    env = {"GOOGLE_CLOUD_PROJECT": "p-auth", "CXAS_LIVE_APP_ID": "l"}
    assert push_app.resolve_app_name("live", env, {}) == "projects/p-auth/locations/us/apps/l"


@pytest.mark.parametrize(
    "env,message",
    [
        ({"CXAS_STAGING_APP_ID": "s"}, "no project"),
        ({"GCP_PROJECT_ID": "p"}, "CXAS_STAGING_APP_ID"),
    ],
)
def test_resolve_app_name_missing_values_raise_clear_errors(env, message) -> None:
    with pytest.raises(push_app.PushError, match=message):
        push_app.resolve_app_name("staging", env, {})


def test_resolve_app_name_rejects_unknown_target() -> None:
    with pytest.raises(push_app.PushError, match="unknown target"):
        push_app.resolve_app_name("prod", {"GCP_PROJECT_ID": "p"}, {})


def test_prepare_app_copy_patches_display_name_and_audio_bucket_without_touching_source(
    src_app: Path, tmp_path: Path
) -> None:
    before = (src_app / "app.json").read_text(encoding="utf-8")
    copy = push_app.prepare_app_copy(
        src_app, tmp_path / "out", display_name="x-staging", audio_bucket="bucket-a"
    )
    data = json.loads((copy / "app.json").read_text(encoding="utf-8"))
    assert data["displayName"] == "x-staging"
    audio_cfg = data["loggingSettings"]["evaluationAudioRecordingConfig"]
    assert audio_cfg["gcsBucket"] == "gs://bucket-a"
    assert audio_cfg["gcsPathPrefix"] == "ces-eval-audio/$session"
    assert "$session" in audio_cfg["gcsPathPrefix"]
    assert data["rootAgent"] == "a"
    # Local-only config and caches are never uploaded.
    assert not (copy / "gecx-config.json").exists()
    assert not (copy / "agents" / "a" / "__pycache__").exists()
    assert (copy / "agents" / "a" / "instruction.txt").read_text(encoding="utf-8") == "hi\n"
    assert (src_app / "app.json").read_text(encoding="utf-8") == before


def test_normalize_and_resolve_audio_bucket(src_app: Path, tmp_path: Path) -> None:
    assert push_app.normalize_audio_bucket(None) is None
    assert push_app.normalize_audio_bucket("  ") is None
    assert push_app.normalize_audio_bucket("my-bucket") == "gs://my-bucket"
    assert push_app.normalize_audio_bucket("gs://my-bucket/") == "gs://my-bucket"
    with pytest.raises(push_app.PushError, match="invalid audio bucket"):
        push_app.normalize_audio_bucket("gs://my-bucket/subpath")
    with pytest.raises(push_app.PushError, match="must contain '\\$session'"):
        push_app.prepare_app_copy(
            src_app, tmp_path / "bad_prefix", audio_bucket="my-bucket", audio_path_prefix="no-session-var"
        )
    assert push_app.resolve_audio_bucket({"CXAS_EVAL_AUDIO_BUCKET": "env-bkt"}, {"eval_audio_bucket": "cfg-bkt"}) == (
        "gs://env-bkt"
    )
    assert push_app.resolve_audio_bucket({}, {"eval_audio_bucket": "cfg-bkt"}) == "gs://cfg-bkt"
    assert push_app.resolve_audio_bucket({"GCP_PROJECT_ID": "proj-ci"}, {}) == "gs://proj-ci-ces-eval-audio"
    assert push_app.resolve_audio_bucket({}, {}) is None


def test_prepare_app_copy_without_bucket_adds_no_logging_settings(src_app: Path, tmp_path: Path) -> None:
    copy = push_app.prepare_app_copy(src_app, tmp_path / "out")
    data = json.loads((copy / "app.json").read_text(encoding="utf-8"))
    assert "loggingSettings" not in data
    assert data["displayName"] == "totto-mercedes-f1-fan-agent"


def test_prepare_app_copy_requires_app_json(tmp_path: Path) -> None:
    (tmp_path / "empty").mkdir()
    with pytest.raises(push_app.PushError, match="no app.json"):
        push_app.prepare_app_copy(tmp_path / "empty", tmp_path / "out")


def test_build_push_command_always_overwrites_and_adds_version_flags() -> None:
    cmd = push_app.build_push_command(
        "cxas", Path("/tmp/a"), APP, create_version=True, version_name="git-abc1234",
        version_description="commit abc",
    )
    assert cmd[:7] == ["cxas", "push", "--app-dir", "/tmp/a", "--to", APP, "--overwrite"]
    assert cmd[7:] == [
        "--create-version", "--version-name", "git-abc1234", "--version-description", "commit abc",
    ]
    assert "--create-version" not in push_app.build_push_command("cxas", Path("/a"), APP)


def test_parse_created_version_and_app_relative() -> None:
    out = (
        "Uploading to CES...\nSuccessfully pushed to: projects/p/locations/us/apps/a\n"
        "Created app version: projects/p/locations/us/apps/a/versions/v-9 with display name git-1\n"
    )
    full = push_app.parse_created_version(out)
    assert full == "projects/p/locations/us/apps/a/versions/v-9"
    assert push_app.app_relative(full) == "versions/v-9"
    assert push_app.parse_created_version("Successfully pushed") is None


def test_redact_replaces_project_terms() -> None:
    text = "Successfully pushed to: projects/proj-x/locations/us/apps/a (123456)"
    assert push_app.redact(text, ["proj-x", "123456"]) == (
        "Successfully pushed to: projects/<project>/locations/us/apps/a (<project>)"
    )


def test_push_app_runs_cxas_push_on_patched_copy_and_returns_relative_version(
    src_app: Path,
) -> None:
    seen = {}

    def runner(cmd, terms):
        app_dir = Path(cmd[cmd.index("--app-dir") + 1])
        seen["cmd"] = list(cmd)
        seen["display"] = json.loads((app_dir / "app.json").read_text(encoding="utf-8"))["displayName"]
        return 0, f"Created app version: {APP}/versions/v-1 with display name git-abc\n"

    res = push_app.push_app(
        app_name=APP, src_dir=src_app, display_name="t-staging", create_version=True,
        version_name="git-abc", runner=runner, cxas_bin="cxas", terms=[],
    )
    assert seen["display"] == "t-staging"
    assert "--overwrite" in seen["cmd"] and seen["cmd"][seen["cmd"].index("--to") + 1] == APP
    assert res["version"] == "versions/v-1"
    assert res["version_name"] == f"{APP}/versions/v-1"
    assert "app-1234" not in json.dumps({k: v for k, v in res.items() if k != "version_name"})


@pytest.mark.parametrize(
    "rc,output,message",
    [
        (1, "Failed to push app: boom", "exited 1"),
        (0, "Failed to push app: boom", "Failed to push app"),
        (0, "Successfully pushed to: x", "did not report a created version"),
    ],
)
def test_push_app_failures_raise(src_app: Path, rc, output, message) -> None:
    with pytest.raises(push_app.PushError, match=message):
        push_app.push_app(
            app_name=APP, src_dir=src_app, create_version=True,
            runner=lambda cmd, terms: (rc, output), cxas_bin="cxas", terms=[],
        )


def test_push_app_rejects_malformed_app_name(src_app: Path) -> None:
    with pytest.raises(push_app.PushError, match="not an app resource name"):
        push_app.push_app(app_name="apps/x", src_dir=src_app, runner=lambda c, t: (0, ""), cxas_bin="c", terms=[])


@pytest.mark.parametrize(
    "env",
    [
        {},
        {"GITHUB_ACTIONS": "true", "GITHUB_REF": "refs/heads/feature"},
        {"GITHUB_ACTIONS": "false", "GITHUB_REF": "refs/heads/main"},
    ],
)
def test_live_push_refused_outside_main_ci(env) -> None:
    with pytest.raises(push_app.PushError, match="refusing to push to LIVE"):
        push_app.check_live_allowed(env)


def test_live_push_allowed_on_main_ci() -> None:
    push_app.check_live_allowed({"GITHUB_ACTIONS": "true", "GITHUB_REF": "refs/heads/main"})


def test_cli_live_target_refused_locally(monkeypatch, capsys) -> None:
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    monkeypatch.setenv("GITHUB_REF", "refs/heads/main")
    monkeypatch.setenv("GCP_PROJECT_ID", "p")
    monkeypatch.setenv("CXAS_LIVE_APP_ID", "l")
    called = []
    monkeypatch.setattr(push_app, "push_app", lambda **kw: called.append(kw))
    assert push_app.main(["--target", "live"]) == 1
    assert not called
    assert "refusing to push to LIVE" in capsys.readouterr().err


def test_cli_staging_refuses_app_without_staging_suffix(monkeypatch, capsys) -> None:
    monkeypatch.setenv("GCP_PROJECT_ID", "p")
    monkeypatch.setenv("CXAS_STAGING_APP_ID", "s")
    monkeypatch.setattr(push_app, "get_app_display_name", lambda name: "totto-live-app")
    called = []
    monkeypatch.setattr(push_app, "push_app", lambda **kw: called.append(kw))
    assert push_app.main(["--target", "staging"]) == 1
    assert not called
    assert "does not end with '-staging'" in capsys.readouterr().err


def test_cli_staging_push_writes_identifier_free_json(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("GCP_PROJECT_ID", "p")
    monkeypatch.setenv("CXAS_STAGING_APP_ID", "s-uuid")
    monkeypatch.setenv("CXAS_EVAL_AUDIO_BUCKET", "gs://b")
    monkeypatch.setattr(push_app, "get_app_display_name", lambda name: "totto-mercedes-f1-fan-agent-staging")
    captured = {}

    def fake_push(**kw):
        captured.update(kw)
        return {
            "version_name": None, "version": None,
            "display_name_patch": kw["display_name"], "audio_bucket_templated": True,
        }

    monkeypatch.setattr(push_app, "push_app", fake_push)
    out = tmp_path / "push.json"
    assert push_app.main(["--target", "staging", "--json-out", str(out)]) == 0
    assert captured["app_name"] == "projects/p/locations/us/apps/s-uuid"
    assert captured["display_name"] == push_app.STAGING_DISPLAY_NAME
    assert captured["audio_bucket"] == "gs://b"
    written = out.read_text(encoding="utf-8")
    assert "s-uuid" not in written and json.loads(written)["target"] == "staging"
