#!/usr/bin/env python3
"""Push the repo's ``cxas_app/`` to a CXAS app (staging, or live from CI).

What it does, in order:

1. Resolves the target app's full resource name from the environment
   (``GCP_PROJECT_ID``/``GOOGLE_CLOUD_PROJECT``, ``CXAS_LOCATION`` and
   ``CXAS_STAGING_APP_ID``/``CXAS_LIVE_APP_ID``). On a developer machine it
   falls back to the gitignored ``gecx-config.json``. Nothing is hard-coded.
2. Copies ``cxas_app/`` to a temporary directory (the repo copy is never
   touched), patches ``app.json`` ``displayName`` for the target and, if
   ``$CXAS_EVAL_AUDIO_BUCKET`` is set, fills
   ``loggingSettings.evaluationAudioRecordingConfig.gcsBucket`` (so the
   bucket name never has to be committed).
3. Runs ``cxas push --app-dir <copy> --to <app> --overwrite`` (plus
   ``--create-version`` when asked) and parses the created version name.

Safety rules:

* ``--target staging`` refuses to push unless the target app's current
  display name ends with ``-staging`` (so a wrong app ID can't hit live).
* ``--target live`` is refused unless running in GitHub Actions on
  ``refs/heads/main``. The live app changes only through the gated
  ``deploy-live`` CI job (``scripts/ci/deploy_live.py``).

Everything printed goes through :func:`redact` so public Actions logs show
``projects/<project>/...`` instead of the project ID/number.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
from typing import Any, Callable, Mapping, Sequence

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_APP_DIR = REPO_ROOT / "cxas_app"
LOCAL_CONFIG = REPO_ROOT / "gecx-config.json"

STAGING_DISPLAY_NAME = "totto-mercedes-f1-fan-agent-staging"
STAGING_SUFFIX = "-staging"
MAIN_REF = "refs/heads/main"
DEFAULT_AUDIO_PATH_PREFIX = "ces-eval-audio/$session"

# Files that are local configuration and must never be uploaded.
_SKIP_NAMES = {"__pycache__", "gecx-config.json", "environment.json", ".DS_Store"}
_SKIP_SUFFIXES = (".pyc", ".pyo")

_CREATED_VERSION_RE = re.compile(r"Created app version:\s*(projects/\S+/versions/[^\s,]+)")
_APP_NAME_RE = re.compile(
    r"^projects/(?P<project>[^/]+)/locations/(?P<location>[^/]+)/apps/(?P<app_id>[^/]+)$"
)


class PushError(RuntimeError):
    """Raised when the push is refused or fails."""


# ---------------------------------------------------------------------------
# Target resolution
# ---------------------------------------------------------------------------


def load_local_config(path: Path = LOCAL_CONFIG) -> dict[str, str]:
    """Reads the gitignored gecx-config.json (developer machines only)."""
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(data, dict):
        return {}
    return {str(k): str(v) for k, v in data.items() if v is not None}


def normalize_audio_bucket(bucket: str | None) -> str | None:
    """Normalizes an eval audio bucket to ``gs://<bucket>`` (CES AppValidator rule)."""
    raw = (bucket or "").strip().rstrip("/")
    if not raw:
        return None
    if not raw.startswith("gs://"):
        raw = f"gs://{raw}"
    without_scheme = raw.removeprefix("gs://")
    if not without_scheme or "/" in without_scheme:
        raise PushError(
            f"invalid audio bucket {bucket!r}: expected 'gs://<bucket>' or '<bucket>' without '/'"
        )
    return raw


def resolve_audio_bucket(
    env: Mapping[str, str] | None = None,
    local_cfg: Mapping[str, str] | None = None,
) -> str | None:
    """Returns normalized ``gs://<bucket>`` from env, local config, or ``<project>-ces-eval-audio``."""
    env = os.environ if env is None else env
    cfg = load_local_config() if local_cfg is None else local_cfg
    raw = env.get("CXAS_EVAL_AUDIO_BUCKET", "").strip() or cfg.get("eval_audio_bucket", "").strip()
    if not raw:
        project = (
            env.get("GCP_PROJECT_ID", "").strip()
            or env.get("GOOGLE_CLOUD_PROJECT", "").strip()
            or cfg.get("gcp_project_id", "").strip()
        )
        if project:
            raw = f"{project}-ces-eval-audio"
    return normalize_audio_bucket(raw)


def resolve_app_name(
    target: str,
    env: Mapping[str, str] | None = None,
    local_cfg: Mapping[str, str] | None = None,
) -> str:
    """Returns ``projects/<p>/locations/<l>/apps/<id>`` for ``staging``/``live``."""
    env = os.environ if env is None else env
    cfg = load_local_config() if local_cfg is None else local_cfg
    if target not in ("staging", "live"):
        raise PushError(f"unknown target {target!r} (expected staging or live)")
    project = (
        env.get("GCP_PROJECT_ID", "").strip()
        or env.get("GOOGLE_CLOUD_PROJECT", "").strip()
        or cfg.get("gcp_project_id", "").strip()
    )
    location = env.get("CXAS_LOCATION", "").strip() or cfg.get("location", "").strip() or "us"
    if target == "staging":
        app_id = env.get("CXAS_STAGING_APP_ID", "").strip() or cfg.get("staging_app_id", "").strip()
        hint = "CXAS_STAGING_APP_ID (repo variable) or staging_app_id in gecx-config.json"
    else:
        app_id = env.get("CXAS_LIVE_APP_ID", "").strip() or cfg.get("app_id", "").strip()
        hint = "CXAS_LIVE_APP_ID (repo variable) or app_id in gecx-config.json"
    if not project:
        raise PushError("no project: set GCP_PROJECT_ID (CI derives it from the service account)")
    if not app_id:
        raise PushError(f"no {target} app ID: set {hint}")
    return f"projects/{project}/locations/{location}/apps/{app_id}"


def parse_app_name(name: str) -> dict[str, str]:
    m = _APP_NAME_RE.match(name or "")
    if not m:
        raise PushError(f"not an app resource name: {name!r}")
    return m.groupdict()


def app_relative(name: str) -> str:
    """``projects/p/locations/l/apps/a/versions/v`` -> ``versions/v``."""
    if not name:
        return name
    m = re.match(r"^projects/[^/]+/locations/[^/]+/apps/[^/]+/(.+)$", name)
    return m.group(1) if m else name


def redaction_terms(env: Mapping[str, str] | None = None) -> list[str]:
    """Identifiers that must not appear in public logs."""
    env = os.environ if env is None else env
    cfg = load_local_config()
    terms = [
        env.get("GCP_PROJECT_ID", ""),
        env.get("GOOGLE_CLOUD_PROJECT", ""),
        env.get("GCP_PROJECT_NUMBER", ""),
        cfg.get("gcp_project_id", ""),
        cfg.get("project_number", ""),
    ]
    return sorted({t.strip() for t in terms if t and t.strip()}, key=len, reverse=True)


def redact(text: str, terms: Sequence[str] | None = None) -> str:
    """Replaces the project ID/number in ``projects/<x>/`` style strings."""
    terms = redaction_terms() if terms is None else terms
    for term in terms:
        text = text.replace(term, "<project>")
    return text


# ---------------------------------------------------------------------------
# Temp copy + app.json patch
# ---------------------------------------------------------------------------


def _ignore(_dir: str, names: list[str]) -> set[str]:
    return {n for n in names if n in _SKIP_NAMES or n.endswith(_SKIP_SUFFIXES)}


def prepare_app_copy(
    src_dir: Path,
    dest_root: Path,
    *,
    display_name: str | None = None,
    audio_bucket: str | None = None,
    audio_path_prefix: str | None = None,
) -> Path:
    """Copies ``src_dir`` to ``dest_root/cxas_app`` and patches ``app.json``.

    Returns the path of the copy. ``src_dir`` is never modified.
    """
    src_dir = Path(src_dir)
    if not (src_dir / "app.json").is_file():
        raise PushError(f"{src_dir} has no app.json")
    norm_bucket = normalize_audio_bucket(audio_bucket)
    dest = Path(dest_root) / "cxas_app"
    shutil.copytree(src_dir, dest, ignore=_ignore)
    app_json = dest / "app.json"
    data = json.loads(app_json.read_text(encoding="utf-8"))
    if display_name:
        data["displayName"] = display_name
    if norm_bucket:
        logging_settings = data.setdefault("loggingSettings", {})
        audio_cfg = logging_settings.setdefault("evaluationAudioRecordingConfig", {})
        audio_cfg["gcsBucket"] = norm_bucket
        prefix = (audio_path_prefix or audio_cfg.get("gcsPathPrefix") or DEFAULT_AUDIO_PATH_PREFIX).strip()
        if "$session" not in prefix:
            raise PushError(
                f"invalid evaluationAudioRecordingConfig.gcsPathPrefix {prefix!r}: must contain '$session'"
            )
        audio_cfg["gcsPathPrefix"] = prefix
    app_json.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return dest


# ---------------------------------------------------------------------------
# cxas push
# ---------------------------------------------------------------------------


def cxas_binary() -> str:
    """The ``cxas`` CLI next to the running interpreter, else on PATH."""
    sibling = Path(sys.executable).parent / "cxas"
    if sibling.is_file():
        return str(sibling)
    found = shutil.which("cxas")
    if not found:
        raise PushError("cxas CLI not found (pip install -e . installs cxas-scrapi)")
    return found


def build_push_command(
    cxas_bin: str,
    app_dir: Path,
    app_name: str,
    *,
    create_version: bool = False,
    version_name: str | None = None,
    version_description: str | None = None,
) -> list[str]:
    cmd = [cxas_bin, "push", "--app-dir", str(app_dir), "--to", app_name, "--overwrite"]
    if create_version:
        cmd.append("--create-version")
        if version_name:
            cmd += ["--version-name", version_name]
        if version_description:
            cmd += ["--version-description", version_description]
    return cmd


def parse_created_version(output: str) -> str | None:
    """Full version name from ``cxas push --create-version`` output."""
    m = _CREATED_VERSION_RE.search(output or "")
    return m.group(1) if m else None


def run_streaming(cmd: Sequence[str], terms: Sequence[str]) -> tuple[int, str]:
    """Runs ``cmd``, echoing redacted output live; returns (rc, full output)."""
    proc = subprocess.Popen(
        list(cmd),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )
    lines = []
    assert proc.stdout is not None
    for line in proc.stdout:
        lines.append(line)
        sys.stdout.write(redact(line, terms))
        sys.stdout.flush()
    return proc.wait(), "".join(lines)


def get_app_display_name(app_name: str) -> str:
    """Current display name of the target app (read-only CES call)."""
    from cxas_scrapi.core.apps import Apps  # pylint: disable=import-outside-toplevel

    parts = parse_app_name(app_name)
    app = Apps(project_id=parts["project"], location=parts["location"]).get_app(app_name)
    return app.display_name


def ensure_app_settings_persisted(app_name: str, src_dir: Path = DEFAULT_APP_DIR) -> bool:
    """Ensures model_settings, language_settings, and audio_processing_config from app.json are persisted on the remote CES app."""
    app_json = Path(src_dir) / "app.json"
    if not app_json.is_file():
        return False
    data = json.loads(app_json.read_text(encoding="utf-8"))
    model_cfg = data.get("modelSettings") or {}
    audio_cfg = data.get("audioProcessingConfig") or {}
    if not model_cfg and not audio_cfg:
        return False

    from google.cloud import ces_v1beta as ces  # pylint: disable=import-outside-toplevel
    from google.protobuf import field_mask_pb2  # pylint: disable=import-outside-toplevel
    from cxas_scrapi.core.apps import Apps  # pylint: disable=import-outside-toplevel

    parts = parse_app_name(app_name)
    apps_client = Apps(project_id=parts["project"], location=parts["location"])
    remote_app = apps_client.get_app(app_name)

    update_paths: list[str] = []
    patch_kwargs: dict[str, Any] = {"name": app_name}
    expected_model = str(model_cfg.get("model") or "").strip()
    if expected_model and getattr(getattr(remote_app, "model_settings", None), "model", "") != expected_model:
        patch_kwargs["model_settings"] = ces.ModelSettings(model=expected_model)
        update_paths.append("model_settings")

    if audio_cfg:
        barge_in_cfg = audio_cfg.get("bargeInConfig") or {}
        synth_map = audio_cfg.get("synthesizeSpeechConfigs") or {}
        remote_audio = getattr(remote_app, "audio_processing_config", None)
        remote_barge = bool(
            getattr(getattr(remote_audio, "barge_in_config", None), "barge_in_awareness", False)
        )
        remote_synth = getattr(remote_audio, "synthesize_speech_configs", None) or {}
        needs_audio_patch = remote_barge != bool(barge_in_cfg.get("bargeInAwareness", False))
        for loc, cfg in synth_map.items():
            voice_expected = str((cfg or {}).get("voice") or "")
            voice_actual = str(getattr(remote_synth.get(loc), "voice", "") if loc in remote_synth else "")
            if voice_expected and voice_actual != voice_expected:
                needs_audio_patch = True
                break
        if needs_audio_patch:
            patch_kwargs["audio_processing_config"] = ces.AudioProcessingConfig(
                synthesize_speech_configs={
                    loc: ces.SynthesizeSpeechConfig(voice=str((cfg or {}).get("voice") or ""))
                    for loc, cfg in synth_map.items()
                },
                barge_in_config=ces.BargeInConfig(
                    barge_in_awareness=bool(barge_in_cfg.get("bargeInAwareness", False))
                ),
            )
            update_paths.append("audio_processing_config")

    if update_paths:
        req = ces.UpdateAppRequest(
            app=ces.App(**patch_kwargs),
            update_mask=field_mask_pb2.FieldMask(paths=update_paths),
        )
        apps_client.client.update_app(request=req)
        return True
    return False


def push_app(
    *,
    app_name: str,
    src_dir: Path = DEFAULT_APP_DIR,
    display_name: str | None = None,
    audio_bucket: str | None = None,
    create_version: bool = False,
    version_name: str | None = None,
    version_description: str | None = None,
    runner: Callable[[Sequence[str], Sequence[str]], tuple[int, str]] = run_streaming,
    cxas_bin: str | None = None,
    terms: Sequence[str] | None = None,
) -> dict[str, Any]:
    """Pushes a patched temp copy of ``src_dir`` to ``app_name``.

    Returns ``{"version_name": <full or None>, "version": <app-relative
    or None>, "display_name_patch": ..., "audio_bucket_templated": bool}``.
    Raises :class:`PushError` if ``cxas push`` fails, or if a version was
    requested and none was reported.
    """
    parse_app_name(app_name)
    norm_bucket = normalize_audio_bucket(audio_bucket)
    terms = redaction_terms() if terms is None else terms
    with tempfile.TemporaryDirectory(prefix="totto-push-") as tmp:
        copy = prepare_app_copy(
            Path(src_dir), Path(tmp), display_name=display_name, audio_bucket=norm_bucket
        )
        cmd = build_push_command(
            cxas_bin or cxas_binary(),
            copy,
            app_name,
            create_version=create_version,
            version_name=version_name,
            version_description=version_description,
        )
        print(redact("[push_app] $ " + " ".join(cmd), terms), flush=True)
        rc, output = runner(cmd, terms)
    if rc != 0:
        raise PushError(f"cxas push exited {rc}")
    # SCRAPI prints "Failed to push app" and exits 1, but guard against a
    # zero exit with an error message too.
    if "Failed to push app" in output:
        raise PushError("cxas push reported 'Failed to push app'")
    version_name_full = parse_created_version(output) if create_version else None
    if create_version and not version_name_full:
        raise PushError("cxas push --create-version did not report a created version")
    if runner is run_streaming:
        patched = ensure_app_settings_persisted(app_name, src_dir=Path(src_dir))
        if patched and create_version and version_name_full:
            from cxas_scrapi.core.versions import Versions  # pylint: disable=import-outside-toplevel

            v_client = Versions(app_name=app_name)
            v_client.delete_version(version_name_full.rsplit("/", 1)[-1])
            refreshed = v_client.create_version(
                display_name=version_name or "",
                description=version_description or "",
            )
            version_name_full = refreshed.name
    return {
        "version_name": version_name_full,
        "version": app_relative(version_name_full) if version_name_full else None,
        "display_name_patch": display_name,
        "audio_bucket_templated": bool(norm_bucket),
    }


def check_live_allowed(env: Mapping[str, str] | None = None) -> None:
    """Live pushes only from GitHub Actions on main."""
    env = os.environ if env is None else env
    if env.get("GITHUB_ACTIONS") != "true" or env.get("GITHUB_REF") != MAIN_REF:
        raise PushError(
            "refusing to push to LIVE: the live app changes only through the gated "
            "deploy-live job on refs/heads/main (scripts/ci/deploy_live.py)"
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="scripts/ci/push_app.py",
        description="Push cxas_app to the staging CXAS app (or live, from CI on main only).",
    )
    parser.add_argument("--target", choices=("staging", "live"), default="staging")
    parser.add_argument("--app-dir", type=Path, default=DEFAULT_APP_DIR)
    parser.add_argument(
        "--display-name",
        default=None,
        help="displayName patched into the temp app.json (default: "
        f"{STAGING_DISPLAY_NAME} for staging, unchanged for live)",
    )
    parser.add_argument("--create-version", action="store_true")
    parser.add_argument("--version-name", default=None)
    parser.add_argument("--version-description", default=None)
    parser.add_argument("--json-out", "--out", dest="json_out", type=Path, default=None, help="write the result as JSON")
    args = parser.parse_args(argv)

    try:
        app_name = resolve_app_name(args.target)
        audio_bucket = resolve_audio_bucket()
        terms = redaction_terms()
        if args.target == "live":
            check_live_allowed()
            display_name = args.display_name
        else:
            current = get_app_display_name(app_name)
            if not current.endswith(STAGING_SUFFIX):
                raise PushError(
                    f"refusing: target app display name {current!r} does not end with "
                    f"{STAGING_SUFFIX!r}; check CXAS_STAGING_APP_ID"
                )
            print(f"[push_app] target staging app: {current}", flush=True)
            display_name = args.display_name or STAGING_DISPLAY_NAME
        result = push_app(
            app_name=app_name,
            src_dir=args.app_dir,
            display_name=display_name,
            audio_bucket=audio_bucket,
            create_version=args.create_version,
            version_name=args.version_name,
            version_description=args.version_description,
            terms=terms,
        )
    except PushError as exc:
        print(f"[push_app] ERROR: {exc}", file=sys.stderr, flush=True)
        return 1
    result["target"] = args.target
    print(f"[push_app] OK: pushed cxas_app to the {args.target} app", flush=True)
    if result["version"]:
        print(f"[push_app] created {result['version']}", flush=True)
    if args.json_out:
        # Only app-relative IDs leave this process (artifacts are public-ish).
        result.pop("version_name", None)
        args.json_out.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
