"""Push-disabled deployment & version-snapshot workflow (`totto_suite deploy`).

Never pushes (`--no-push` is mandatory; `--push` is refused because the live
app is changed only by the gated CI deploy-live job, scripts/ci/deploy_live.py):
1. Runs the offline regression gate (`totto_suite.gate.evaluate_gate`) on `cxas_app`.
2. If the gate passes, snapshots the live CXAS app version via `cxasapi`
   (`get_app`, `create_version`, `get_version`, `list_versions`) without pushing
   or mutating live app resources.
3. Writes a schema-v1 `deploy` run record in `evals/history/runs/<run_id>.json`
   linking the git commit, `cxas_app` tree hash, model, rationale, offline gate
   test results, and fetchable CXAS version ID, then updates the trend files.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import time
from typing import Any

from totto_suite import config, cxasapi, gate, gitinfo, records, trend


EXIT_DEPLOY_OK = 0
EXIT_DEPLOY_GATE_FAIL = 1
EXIT_DEPLOY_BLOCKED = 2


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return gitinfo.iso_utc(dt)


def _model_from_app_dir(app_dir: Path) -> str | None:
    try:
        data = json.loads((app_dir / "app.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return (data.get("modelSettings") or {}).get("model")


def run_deploy(
    *,
    rationale: str,
    app_dir: Path | None = None,
    repo_root: Path | None = None,
    push: bool = False,
    no_push: bool = True,
    record_run: bool = True,
    cxas_client: Any = None,
) -> dict[str, Any]:
    """Execute the push-disabled deploy workflow and return a summary dict."""
    if push or not no_push:
        return {
            "ok": False,
            "exit_code": EXIT_DEPLOY_BLOCKED,
            "error": (
                "--push is not available from `totto_suite deploy`: the live CXAS app is "
                "changed only by the gated deploy-live job in .github/workflows/ci.yml "
                "(scripts/ci/deploy_live.py, refs/heads/main after the staging eval gate "
                "passes). Use --no-push (default) for a version snapshot."
            ),
            "push_performed": False,
        }

    if not str(rationale or "").strip():
        return {
            "ok": False,
            "exit_code": EXIT_DEPLOY_BLOCKED,
            "error": "A non-empty --rationale is required for every deploy run.",
            "push_performed": False,
        }

    started = _now()
    t0 = time.monotonic()
    repo_root_path = Path(repo_root).resolve() if repo_root else config.REPO_ROOT
    candidate_dir = Path(app_dir).resolve() if app_dir else config.app_dir()

    # Step 1: Run the offline pre-commit gate
    gate_result = gate.evaluate_gate(
        app_dir=candidate_dir,
        repo_root=repo_root_path,
    )
    if not gate_result["passed"]:
        return {
            "ok": False,
            "exit_code": EXIT_DEPLOY_GATE_FAIL,
            "error": f"Pre-deploy offline gate failed: {'; '.join(gate_result.get('blocking_reasons', []))}",
            "gate_result": gate_result,
            "push_performed": False,
        }

    # Step 2: Snapshot CXAS version via cxasapi (read/snapshot only, no push)
    api = cxas_client or cxasapi
    target_app_name = config.app_name()
    stamp = started.strftime("%Y%m%dT%H%M%SZ")
    head = gitinfo.head_commit(repo=repo_root_path)
    short_head = head[:7]

    before = api.get_app(target_app_name)
    display_name = f"r4-deploy-{short_head}-{stamp}"
    description = (
        f"Push-disabled deploy snapshot for commit {short_head}: {rationale.strip()[:180]}"
    )
    requested_at = _now()
    created = api.create_version(display_name, description, target_app_name)
    fetched = api.get_version(created["id"], target_app_name)
    listed_after = api.list_versions(target_app_name) or []
    after = api.get_app(target_app_name)

    if fetched is None or fetched.get("name") != created.get("name"):
        return {
            "ok": False,
            "exit_code": EXIT_DEPLOY_BLOCKED,
            "error": f"get_version({created.get('id')!r}) did not verify fetchable version.",
            "push_performed": False,
        }

    in_list = any(v.get("id") == created["id"] for v in listed_after)
    version_status = "in_version_list" if in_list else "hidden_fetchable"

    created_dt = None
    if created.get("create_time"):
        try:
            created_dt = datetime.strptime(
                created["create_time"], "%Y-%m-%dT%H:%M:%S.%fZ"
            ).replace(tzinfo=timezone.utc)
        except ValueError:
            created_dt = None
    returned_existing = created.get("display_name") != display_name or (
        created_dt is not None and created_dt < requested_at - timedelta(seconds=60)
    )

    state_before = {"update_time": before.get("update_time"), "etag": before.get("etag")}
    state_after = {"update_time": after.get("update_time"), "etag": after.get("etag")}
    app_unchanged = state_before == state_after

    # Step 3: Build and write schema-v1 deploy record
    run_id = records.make_run_id("deploy", head, started)
    rel_app = config.repo_relative(candidate_dir)
    dirty = gitinfo.dirty_state(agent_path=rel_app, include_suite=True, repo=repo_root_path)
    tree_hash = cxasapi.app_tree_hash(candidate_dir)
    model = (
        _model_from_app_dir(candidate_dir)
        or ((before.get("raw") or {}).get("modelSettings") or {}).get("model")
        or config.EXPECTED_MODEL
    )
    elapsed = round(time.monotonic() - t0, 2)

    record = records.build_record(
        mode="deploy",
        run_id=run_id,
        started_at=_iso(started),
        finished_at=_iso(_now()),
        point_time=_iso(started),
        agent={
            "commit": head,
            "path": rel_app,
            "tree_hash": tree_hash,
            "dirty": dirty["dirty"],
            "dirty_paths_relevant": dirty["dirty_paths_relevant"],
            "dirty_paths_unrelated": dirty["dirty_paths_unrelated"],
        },
        suite={
            "commit": head,
            "dirty": dirty["suite_dirty"],
            "dirty_paths": dirty["suite_dirty_paths"],
        },
        cxas={
            "app": target_app_name,
            "version_id": created["id"],
            "version_status": version_status,
            "model": model,
            "app_update_time": before.get("update_time"),
            "app_etag": before.get("etag"),
        },
        rationale=rationale.strip(),
        tests=gate_result["tests"],
        extra={
            "duration_s": elapsed,
            "deploy": {
                "push_performed": False,
                "no_push_enforced": True,
                "gate_passed": True,
                "gate_baseline": gate_result["baseline_source"],
                "version_name": created["name"],
                "version_display_name": created.get("display_name"),
                "version_create_time": created.get("create_time"),
                "returned_existing_version": returned_existing,
                "get_version_ok": True,
                "in_version_list": in_list,
                "app_state_before": state_before,
                "app_state_after": state_after,
                "app_unchanged": app_unchanged,
            },
        },
    )

    rec_path = None
    trend_info = None
    if record_run:
        runs_dir = repo_root_path / "evals" / "history" / "runs"
        rec_path = records.write_record(record, runs_dir=runs_dir)
        if repo_root_path == config.REPO_ROOT:
            trend_info = trend.generate()

    return {
        "ok": True,
        "exit_code": EXIT_DEPLOY_OK,
        "run_id": run_id,
        "record": record,
        "record_path": str(rec_path) if rec_path else None,
        "version_id": created["id"],
        "version_name": created["name"],
        "version_status": version_status,
        "get_version_ok": True,
        "in_version_list": in_list,
        "returned_existing_version": returned_existing,
        "app_unchanged": app_unchanged,
        "push_performed": False,
        "gate_result": gate_result,
        "trend_info": trend_info,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="totto_suite deploy",
        description="Run the push-disabled deploy workflow (gate + CXAS version snapshot + run record).",
    )
    parser.add_argument(
        "--rationale",
        type=str,
        required=True,
        help="Required rationale describing why this deploy/version snapshot is being recorded.",
    )
    parser.add_argument(
        "--no-push",
        action="store_true",
        default=True,
        help="Record CXAS version snapshot without pushing local cxas_app to the live app (default).",
    )
    parser.add_argument(
        "--push",
        action="store_true",
        default=False,
        help="Refused: live pushes happen only in the gated CI deploy-live job on main.",
    )
    parser.add_argument(
        "--app-dir",
        type=Path,
        default=None,
        help="Candidate cxas_app directory (default: <repo>/cxas_app).",
    )
    parser.add_argument(
        "--no-record",
        action="store_true",
        help="Do not write a deploy record to evals/history/runs/.",
    )
    args = parser.parse_args(argv)

    result = run_deploy(
        rationale=args.rationale,
        app_dir=args.app_dir,
        push=args.push,
        no_push=not args.push,
        record_run=not args.no_record,
    )

    if not result["ok"]:
        if "gate_result" in result:
            print(gate.format_gate_report(result["gate_result"]), flush=True)
        print(f"[deploy] BLOCKED: {result['error']}", flush=True)
        return int(result["exit_code"])

    print(gate.format_gate_report(result["gate_result"]), flush=True)
    print(
        f"[deploy] Version snapshot verified: {result['version_id']} "
        f"({result['version_status']}, get_version_ok={result['get_version_ok']}, "
        f"app_unchanged={result['app_unchanged']}, push_performed={result['push_performed']})",
        flush=True,
    )
    if result.get("record_path"):
        print(
            f"[deploy] Wrote run record: {config.repo_relative(result['record_path'])}",
            flush=True,
        )
    if result.get("trend_info"):
        ti = result["trend_info"]
        print(
            f"[deploy] Regenerated trend: {ti['points']} points, {ti['regressions']} regression flags",
            flush=True,
        )
    return EXIT_DEPLOY_OK


if __name__ == "__main__":
    raise SystemExit(main())
