#!/usr/bin/env python3
"""Gated deploy of ``cxas_app/`` to the LIVE CXAS app (CI ``deploy-live`` job).

Runs only on ``refs/heads/main`` after the staging eval gate passed:

1. export a **before** snapshot of the live app;
2. ``cxas push --overwrite --create-version`` to live, version display name
   ``git-<sha7>``, description = full commit SHA + Actions run URL + staging
   gate run ID; the created version is re-read with ``get_version``;
3. export an **after** snapshot and write a normalized before/after diff;
4. repoint every ``GOOGLE_TELEPHONY_PLATFORM`` deployment (the phone number)
   to the new version (``deployments.patch`` with ``updateMask=app_version``)
   and re-read each deployment to verify;
5. write ``deploy.json`` (app-relative IDs only, plus commit, run URL and
   snapshot paths) into ``--out-dir``, which CI uploads as an artifact and
   hands to the dashboard.

It refuses to run unless ``GITHUB_REF == refs/heads/main`` (tests pass
``--allow-non-main`` together with a fake backend; nothing in the tests ever
talks to CXAS). Nothing is committed to git.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import sys
from typing import Any, Callable, Mapping, Protocol

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import push_app  # noqa: E402  pylint: disable=wrong-import-position

from totto_suite import cxasapi  # noqa: E402  pylint: disable=wrong-import-position

SCHEMA = "totto-deploy-record/v1"
MAIN_REF = "refs/heads/main"
TELEPHONY = "GOOGLE_TELEPHONY_PLATFORM"
EXIT_OK = 0
EXIT_FAILED = 1
EXIT_REFUSED = 2


class DeployError(RuntimeError):
    """A deploy step failed; ``step`` names it for the record."""

    def __init__(self, step: str, message: str):
        super().__init__(message)
        self.step = step


class Backend(Protocol):
    """The CXAS operations the deploy needs (real: :class:`CxasBackend`)."""

    def export_app(self) -> bytes: ...

    def push(self, src_dir: Path, version_display_name: str, description: str) -> str: ...

    def get_version(self, version_name: str) -> dict: ...

    def list_deployments(self) -> list[dict]: ...

    def set_deployment_version(self, deployment_name: str, version_name: str) -> dict: ...

    def get_deployment(self, deployment_name: str) -> dict: ...


# ---------------------------------------------------------------------------
# Real backend (SCRAPI / CES client). Not exercised by unit tests.
# ---------------------------------------------------------------------------


def _deployment_to_dict(dep: Any) -> dict:
    channel = getattr(getattr(dep, "channel_profile", None), "channel_type", None)
    channel_name = getattr(channel, "name", None) or str(channel or "")
    return {
        "name": dep.name,
        "display_name": dep.display_name,
        "channel_type": channel_name,
        "app_version": dep.app_version,
    }


class CxasBackend:
    """Talks to CES for one app (the live app in CI)."""

    def __init__(self, app_name: str, terms: list[str]):
        self.app_name = app_name
        self.terms = terms

    def export_app(self) -> bytes:
        return cxasapi.export_app_bytes(self.app_name)

    def push(self, src_dir: Path, version_display_name: str, description: str) -> str:
        result = push_app.push_app(
            app_name=self.app_name,
            src_dir=src_dir,
            audio_bucket=push_app.resolve_audio_bucket(),
            create_version=True,
            version_name=version_display_name,
            version_description=description,
            terms=self.terms,
        )
        return result["version_name"]

    def get_version(self, version_name: str) -> dict:
        from cxas_scrapi.core.versions import Versions  # pylint: disable=import-outside-toplevel

        v = Versions(app_name=self.app_name).get_version(version_name.rsplit("/", 1)[-1])
        return cxasapi.version_to_dict(v)

    def _deployments(self):
        from cxas_scrapi.core.deployments import Deployments  # pylint: disable=import-outside-toplevel

        return Deployments(app_name=self.app_name)

    def list_deployments(self) -> list[dict]:
        return [_deployment_to_dict(d) for d in self._deployments().list_deployments()]

    def set_deployment_version(self, deployment_name: str, version_name: str) -> dict:
        from google.cloud.ces_v1beta import types  # pylint: disable=import-outside-toplevel
        from google.protobuf import field_mask_pb2  # pylint: disable=import-outside-toplevel

        request = types.UpdateDeploymentRequest(
            deployment=types.Deployment(name=deployment_name, app_version=version_name),
            update_mask=field_mask_pb2.FieldMask(paths=["app_version"]),
        )
        return _deployment_to_dict(self._deployments().client.update_deployment(request=request))

    def get_deployment(self, deployment_name: str) -> dict:
        from google.cloud.ces_v1beta import types  # pylint: disable=import-outside-toplevel

        dep = self._deployments().client.get_deployment(
            request=types.GetDeploymentRequest(name=deployment_name)
        )
        return _deployment_to_dict(dep)


# ---------------------------------------------------------------------------
# Orchestration (pure; unit-tested with a fake backend)
# ---------------------------------------------------------------------------


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def rel(name: str | None) -> str | None:
    return push_app.app_relative(name) if name else name


def check_ref(env: Mapping[str, str], allow_non_main: bool) -> None:
    ref = env.get("GITHUB_REF", "")
    if ref != MAIN_REF and not allow_non_main:
        raise DeployError(
            "guard",
            f"refusing to deploy to LIVE from GITHUB_REF={ref!r}: live changes only via "
            f"the gated {MAIN_REF} CI path",
        )


def version_display_name(commit: str) -> str:
    return f"git-{commit[:7]}"


def version_description(commit: str, run_url: str, gate_run_id: str) -> str:
    return f"commit {commit} | run {run_url} | staging gate {gate_run_id}"


def _redactor(terms: Mapping[str, str]) -> Callable[[str], str]:
    ordered = sorted(((k, v) for k, v in terms.items() if k), key=lambda kv: -len(kv[0]))

    def apply(text: str) -> str:
        for needle, replacement in ordered:
            text = text.replace(needle, replacement)
        return text

    return apply


def snapshot(backend: Backend, dest: Path) -> dict:
    """Exports the app into ``dest/app`` and returns its tree hashes."""
    data = backend.export_app()
    app_dir = dest / "app"
    app_dir.mkdir(parents=True, exist_ok=True)
    files = cxasapi.extract_export(data, app_dir)
    return {
        "path": app_dir,
        "files": len(files),
        "tree_hash": cxasapi.app_tree_hash(app_dir),
    }


def write_diff(before_dir: Path, after_dir: Path, out_dir: Path, redact: Callable[[str], str]) -> dict:
    diff = cxasapi.diff_app_trees(before_dir, after_dir, "before", "after")
    lines = [
        "# Live app before/after diff (normalized)",
        "",
        f"- identical: {diff['identical']}",
        f"- changed files: {len(diff['differing_files'])}",
        f"- only before: {len(diff['only_left'])}",
        f"- only after: {len(diff['only_right'])}",
        "",
    ]
    for path, text in diff["unified_diffs"].items():
        lines += [f"## {path}", "", "```diff", text.rstrip("\n"), "```", ""]
    (out_dir / "diff.md").write_text(redact("\n".join(lines) + "\n"), encoding="utf-8")
    summary = {
        "identical": diff["identical"],
        "changed_files": diff["differing_files"],
        "only_before": diff["only_left"],
        "only_after": diff["only_right"],
        "before_tree_hash": diff["left_tree_hash"],
        "after_tree_hash": diff["right_tree_hash"],
    }
    (out_dir / "diff.json").write_text(
        redact(json.dumps({**summary, "unified_diffs": diff["unified_diffs"]}, indent=2)) + "\n",
        encoding="utf-8",
    )
    return summary


def repoint_telephony(backend: Backend, version_name: str, out: list[dict]) -> list[dict]:
    """Points every GTP deployment at ``version_name`` and verifies it.

    Entries are appended to ``out`` before each change, so the caller keeps
    the partial state if a later deployment fails.
    """
    for dep in backend.list_deployments():
        if dep.get("channel_type") != TELEPHONY:
            continue
        entry = {
            "deployment": rel(dep["name"]),
            "display_name": dep.get("display_name"),
            "channel_type": TELEPHONY,
            "previous_version": rel(dep.get("app_version")),
            "new_version": rel(version_name),
            "verified": False,
        }
        out.append(entry)
        if rel(dep.get("app_version")) != rel(version_name):
            backend.set_deployment_version(dep["name"], version_name)
        got = backend.get_deployment(dep["name"])
        if rel(got.get("app_version")) != rel(version_name):
            raise DeployError(
                "repoint",
                f"{entry['deployment']} still points at {rel(got.get('app_version'))}, "
                f"expected {rel(version_name)}",
            )
        entry["verified"] = True
    return out


def run_deploy_live(
    backend: Backend,
    *,
    src_dir: Path,
    out_dir: Path,
    commit: str,
    run_url: str,
    gate_run_id: str,
    gate_verdict: str,
    env: Mapping[str, str] | None = None,
    allow_non_main: bool = False,
    redact_terms: Mapping[str, str] | None = None,
    now: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
) -> tuple[int, dict]:
    """Runs the five deploy steps; always writes ``out_dir/deploy.json``.

    Returns ``(exit_code, record)``.
    """
    env = os.environ if env is None else env
    redact = _redactor(redact_terms or {})
    out_dir = Path(out_dir)
    record: dict[str, Any] = {
        "schema": SCHEMA,
        "kind": "deploy",
        "target": "live",
        "ok": False,
        "commit": commit,
        "commit_short": commit[:7],
        "ref": env.get("GITHUB_REF", ""),
        "run_url": run_url,
        "staging_gate": {"run_id": gate_run_id, "verdict": gate_verdict},
        "started_at": _iso(now()),
        "finished_at": None,
        "failed_step": None,
        "error": None,
        "version": None,
        "phone_deployments": [],
        "snapshots": {},
        "diff": None,
        "agent_content_matches_repo": None,
    }
    try:
        check_ref(env, allow_non_main)
        if gate_verdict != "PASS":
            raise DeployError("guard", f"staging gate verdict is {gate_verdict!r}, not PASS")
        if len(commit) < 7:
            raise DeployError("guard", f"bad commit SHA {commit!r}")
        out_dir.mkdir(parents=True, exist_ok=True)

        # (a) before snapshot
        try:
            before = snapshot(backend, out_dir / "before")
        except Exception as exc:  # noqa: BLE001  record any API failure
            raise DeployError("before_snapshot", str(exc)) from exc
        record["snapshots"]["before"] = {
            "path": "before/app",
            "files": before["files"],
            "tree_hash": before["tree_hash"],
        }

        # (b) push + version
        display = version_display_name(commit)
        description = version_description(commit, run_url, gate_run_id)
        try:
            version_name = backend.push(Path(src_dir), display, description)
        except Exception as exc:  # noqa: BLE001
            raise DeployError("push", str(exc)) from exc
        if not version_name:
            raise DeployError("push", "push reported no created version")
        try:
            got = backend.get_version(version_name)
        except Exception as exc:  # noqa: BLE001
            raise DeployError("verify_version", str(exc)) from exc
        if got.get("display_name") != display:
            raise DeployError(
                "verify_version",
                f"version {rel(version_name)} has display name {got.get('display_name')!r}, "
                f"expected {display!r}",
            )
        record["version"] = {
            "id": rel(version_name),
            "display_name": display,
            "description": description,
            "create_time": got.get("create_time"),
            "verified": True,
        }

        # (c) after snapshot + diff
        try:
            after = snapshot(backend, out_dir / "after")
        except Exception as exc:  # noqa: BLE001
            raise DeployError("after_snapshot", str(exc)) from exc
        record["snapshots"]["after"] = {
            "path": "after/app",
            "files": after["files"],
            "tree_hash": after["tree_hash"],
        }
        record["diff"] = write_diff(before["path"], after["path"], out_dir, redact)
        record["snapshots"]["diff_md"] = "diff.md"
        record["snapshots"]["diff_json"] = "diff.json"
        repo_vs_after = cxasapi.diff_app_trees(Path(src_dir), after["path"], "repo", "after")
        changed = sorted(
            set(repo_vs_after["differing_files"] + repo_vs_after["only_left"] + repo_vs_after["only_right"])
        )
        record["after_vs_repo_changed_files"] = changed
        # app.json carries server-side identity (name, displayName), and
        # evaluations/ + evaluationExpectations/ are platform-synced from
        # evals/*.yaml, so the agent content check ignores them; every other
        # file must match.
        record["agent_content_matches_repo"] = not [
            p
            for p in changed
            if p != "app.json"
            and not p.startswith(("evaluations/", "evaluationExpectations/", "evaluationDatasets/"))
        ]

        # (d) phone deployments (entries are appended as they are processed,
        # so a partial failure is still visible in the record)
        try:
            repoint_telephony(backend, version_name, record["phone_deployments"])
        except DeployError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise DeployError("repoint", str(exc)) from exc

        record["ok"] = True
        code = EXIT_OK
    except DeployError as exc:
        record["failed_step"] = exc.step
        record["error"] = str(exc)
        code = EXIT_REFUSED if exc.step == "guard" else EXIT_FAILED
    record["status"] = "SUCCESS" if record["ok"] else ("REFUSED" if code == EXIT_REFUSED else "FAILED")
    record["finished_at"] = _iso(now())
    record = json.loads(redact(json.dumps(record)))
    # (e) the record, also on failure so the dashboard shows what happened.
    # A refusal (wrong branch / gate not PASS) leaves no trace on disk.
    if code != EXIT_REFUSED:
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "deploy.json").write_text(
            json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
    return code, record


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _git_head() -> str:
    return subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=REPO_ROOT, capture_output=True, text=True, check=True
    ).stdout.strip()


def _default_run_url(env: Mapping[str, str]) -> str:
    server = env.get("GITHUB_SERVER_URL", "https://github.com")
    repo = env.get("GITHUB_REPOSITORY", "")
    run_id = env.get("GITHUB_RUN_ID", "")
    return f"{server}/{repo}/actions/runs/{run_id}" if repo and run_id else "local"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="scripts/ci/deploy_live.py",
        description="Gated live deploy: snapshot, push + version, snapshot + diff, repoint phone, record.",
    )
    parser.add_argument("--app-dir", type=Path, default=push_app.DEFAULT_APP_DIR)
    parser.add_argument("--out-dir", type=Path, default=Path("deploy_out"))
    parser.add_argument("--commit", default=None, help="default: $GITHUB_SHA, else git HEAD")
    parser.add_argument("--run-url", default=None, help="default: built from $GITHUB_* vars")
    parser.add_argument("--gate-run-id", required=True, help="staging gate run id (ci-<run_id>)")
    parser.add_argument("--gate-verdict", required=True, help="must be PASS")
    parser.add_argument(
        "--allow-non-main",
        action="store_true",
        help="tests only: skip the GITHUB_REF == refs/heads/main guard",
    )
    args = parser.parse_args(argv)

    env = os.environ
    # Refuse before touching CES at all.
    try:
        check_ref(env, args.allow_non_main)
    except DeployError as exc:
        print(f"[deploy_live] REFUSED: {exc}", file=sys.stderr, flush=True)
        return EXIT_REFUSED
    try:
        app_name = push_app.resolve_app_name("live")
    except push_app.PushError as exc:
        print(f"[deploy_live] ERROR: {exc}", file=sys.stderr, flush=True)
        return EXIT_FAILED
    terms = push_app.redaction_terms()
    redact_terms = {t: "<project>" for t in terms}
    redact_terms[push_app.parse_app_name(app_name)["app_id"]] = "<live-app>"
    commit = args.commit or env.get("GITHUB_SHA") or _git_head()
    run_url = args.run_url or _default_run_url(env)

    code, record = run_deploy_live(
        CxasBackend(app_name, terms),
        src_dir=args.app_dir,
        out_dir=args.out_dir,
        commit=commit,
        run_url=run_url,
        gate_run_id=args.gate_run_id,
        gate_verdict=args.gate_verdict,
        env=env,
        allow_non_main=args.allow_non_main,
        redact_terms=redact_terms,
    )
    if record["ok"]:
        v = record["version"]
        print(f"[deploy_live] live version {v['id']} ({v['display_name']}) verified", flush=True)
        print(f"[deploy_live] before/after diff: {len(record['diff']['changed_files'])} changed files", flush=True)
        for dep in record["phone_deployments"]:
            print(
                f"[deploy_live] phone deployment {dep['deployment']}: "
                f"{dep['previous_version']} -> {dep['new_version']} (verified)",
                flush=True,
            )
        if not record["phone_deployments"]:
            print("[deploy_live] no GOOGLE_TELEPHONY_PLATFORM deployment on live", flush=True)
    else:
        print(
            f"[deploy_live] FAILED at {record['failed_step']}: {record['error']}",
            file=sys.stderr,
            flush=True,
        )
    print(f"[deploy_live] record: {args.out_dir / 'deploy.json'}", flush=True)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
