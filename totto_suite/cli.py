"""Command line: ``python -m totto_suite <command>``.

Commands
  offline     fast hermetic layers (no cloud calls); records a run
  snapshot    read-only live inventory + inline export + diff vs commits +
              CXAS version snapshot; with --commit records the first-class
              history point
  trend       regenerate evals/history/{index.json,TREND.md,trend.html}
  live, gate, deploy, backfill, mutants, verify-ids
              delegated to totto_suite.<module>.main(argv) -> int (owned by
              milestones M3/M4); honest exit 2 until those modules exist

Exit codes (offline): 0 all decided tests pass, 1 any FAIL, 2 suite crash or
nothing to run, 3 no FAIL but INFRA_ERROR present (inconclusive).
"""

from __future__ import annotations

import argparse
import datetime
import hashlib
import importlib
import json
import os
import re
import sys
import tempfile
import time
from pathlib import Path

from totto_suite import config, gitinfo, records, taxonomy, trend
from totto_suite import layers as layers_pkg

# command -> (module, owning milestone)
DELEGATED = {
    "live": ("totto_suite.live", "M3"),
    "verify-ids": ("totto_suite.verify_ids", "M3"),
    "gate": ("totto_suite.gate", "M4"),
    "deploy": ("totto_suite.deploy", "M4"),
    "backfill": ("totto_suite.backfill", "M4"),
    "mutants": ("totto_suite.mutants", "M4"),
}

EXIT_OK, EXIT_FAIL, EXIT_CRASH, EXIT_INFRA = 0, 1, 2, 3


def _now() -> datetime.datetime:
    return datetime.datetime.now(datetime.timezone.utc)


def _iso(dt: datetime.datetime) -> str:
    return gitinfo.iso_utc(dt)


def _log(msg: str) -> None:
    print(msg, flush=True)


# --------------------------------------------------------------------------
# Shared: run layers and record
# --------------------------------------------------------------------------


def model_from_app_dir(app_dir: Path) -> str | None:
    try:
        app = json.loads((Path(app_dir) / "app.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return (app.get("modelSettings") or {}).get("model")


def match_live_snapshot(tree_hash: str, recs: list[dict] | None = None) -> dict | None:
    """Latest snapshot record whose normalized agent tree hash equals ours."""
    recs = records.load_all() if recs is None else recs
    matching = [
        r
        for r in recs
        if r.get("mode") == "snapshot" and r.get("agent", {}).get("tree_hash") == tree_hash
    ]
    return records.latest(matching, "snapshot")


def layer_status(summary: dict) -> str:
    if summary["fail"]:
        return "FAIL"
    if summary["infra_error"]:
        return "INFRA_ERROR"
    if summary["pass"]:
        return "PASS"
    return "SKIPPED"


def run_layers(kind: str, ctx: dict, directory: Path | None = None, package: str | None = None):
    """Discovers and runs all layer modules of ``kind``; returns (mods, outcomes)."""
    kwargs = {}
    if directory is not None:
        kwargs["directory"] = directory
    if package is not None:
        kwargs["package"] = package
    mods = layers_pkg.discover(kind, **kwargs)
    outcomes = []
    for mod in mods:
        _log(f"[{kind}] running {mod.module} ...")
        outcome = layers_pkg.run_layer(mod, ctx)
        state = "CRASHED" if outcome.crashed else f"{len(outcome.results)} results"
        _log(f"[{kind}] {mod.module}: {state} in {outcome.duration_s:.2f}s")
        outcomes.append(outcome)
    return mods, outcomes


def print_summary(tests: list[dict]) -> dict:
    summary = records.layer_summary(tests)
    _log("")
    _log(f"{'layer':<18} {'status':<12} {'pass':>5} {'fail':>5} {'infra':>6} {'skip':>5}  score")
    for layer, s in summary.items():
        score = "n/a" if s["score"] is None else f"{s['score'] * 100:.1f}%"
        _log(
            f"{layer:<18} {layer_status(s):<12} {s['pass']:>5} {s['fail']:>5}"
            f" {s['infra_error']:>6} {s['skipped']:>5}  {score}"
        )
    infra = taxonomy.summarize_infra(tests)
    _log(f"INFRA_ERROR total: {infra['count']} {infra['by_kind'] or ''}".rstrip())
    fails = [t for t in tests if t["status"] == "FAIL"]
    if fails:
        _log(f"FAILED tests ({len(fails)}):")
        for t in fails:
            msg = (t.get("message") or "").splitlines()[0][:160] if t.get("message") else ""
            _log(f"  FAIL {t['id']} (repeat {t.get('repeat', 1)}): {msg}")
    return summary


def exit_code_for(tests: list[dict]) -> int:
    statuses = {t["status"] for t in tests}
    if "FAIL" in statuses:
        return EXIT_FAIL
    if "INFRA_ERROR" in statuses:
        return EXIT_INFRA
    return EXIT_OK


# --------------------------------------------------------------------------
# offline
# --------------------------------------------------------------------------


def cmd_offline(args: argparse.Namespace) -> int:
    app_dir = Path(args.app_dir) if args.app_dir else config.DEFAULT_APP_DIR
    if not app_dir.is_absolute():
        app_dir = (config.REPO_ROOT / app_dir).resolve()
    if not (app_dir / "app.json").is_file():
        _log(f"error: {app_dir} has no app.json (not a CXAS app directory)")
        return EXIT_CRASH
    os.environ["TOTTO_APP_DIR"] = str(app_dir)

    mods = layers_pkg.discover("offline")
    if not mods:
        _log(
            "No offline layer modules found in totto_suite/layers/ (expected"
            " offline_<name>.py exposing run(ctx); owned by milestone M2)."
            " Nothing was run and nothing was recorded."
        )
        return EXIT_CRASH

    started = _now()
    t0 = time.monotonic()
    head = gitinfo.head_commit()
    run_id = records.make_run_id("offline", head, started)
    record_it = not args.no_record
    tmp = None
    if record_it:
        artifacts_dir = config.ARTIFACTS_DIR / run_id
    else:
        tmp = tempfile.TemporaryDirectory(prefix="totto_offline_")
        artifacts_dir = Path(tmp.name)
    ctx = {
        "repo_root": str(config.REPO_ROOT),
        "app_dir": str(app_dir),
        "mode": "offline",
        "run_id": run_id,
        "artifacts_dir": str(artifacts_dir),
        "repeats": 1,
        "now": args.now,
        "app_name": config.app_name(),
    }
    _log(f"offline run {run_id}: app_dir={config.repo_relative(app_dir)} ({len(mods)} layer modules)")
    try:
        _, outcomes = run_layers("offline", ctx)
    finally:
        if tmp is not None:
            tmp.cleanup()
    crashed = [o for o in outcomes if o.crashed]
    if crashed:
        for o in crashed:
            _log(f"SUITE CRASH in {o.layer.module}:\n{o.error}")
        _log("Suite crashed: no record written (a crash is neither PASS nor FAIL).")
        return EXIT_CRASH

    tests = sorted(
        (r for o in outcomes for r in o.results),
        key=lambda t: (t["id"], t.get("repeat", 1)),
    )
    if not tests:
        _log("Offline layers returned no results; nothing recorded.")
        return EXIT_CRASH
    print_summary(tests)
    digest = records.results_digest(tests)
    elapsed = time.monotonic() - t0
    _log(f"tests: {len(tests)}  results digest: {digest}  wall: {elapsed:.1f}s")
    code = exit_code_for(tests)

    if not record_it:
        _log("--no-record: nothing written to evals/history/.")
        return code

    rel_app = config.repo_relative(app_dir)
    dirty = gitinfo.dirty_state(agent_path=rel_app, include_suite=True)
    tree_hash = _app_tree_hash(app_dir)
    snap = match_live_snapshot(tree_hash)
    agent_clean = not any(
        p == rel_app or p.startswith(rel_app.rstrip("/") + "/")
        for p in dirty["dirty_paths_relevant"]
    )
    point_time = gitinfo.commit_time(head) if agent_clean else _iso(started)
    cxas = {
        "app": config.app_name(),
        "version_id": snap["cxas"]["version_id"] if snap else None,
        "version_status": snap["cxas"]["version_status"] if snap else "not_deployed",
        "model": model_from_app_dir(app_dir) or "unknown",
        "app_update_time": snap["cxas"]["app_update_time"] if snap else None,
        "app_etag": snap["cxas"]["app_etag"] if snap else None,
    }
    record = records.build_record(
        mode="offline",
        run_id=run_id,
        started_at=_iso(started),
        finished_at=_iso(_now()),
        point_time=point_time,
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
        cxas=cxas,
        rationale=args.rationale or gitinfo.commit_subject(head),
        tests=tests,
        extra={
            "matched_snapshot_run": snap["run_id"] if snap else None,
            "duration_s": round(elapsed, 2),
        },
    )
    path = records.write_record(record)
    info = trend.generate()
    _log(f"record: {config.repo_relative(path)}")
    _log(
        f"version: {cxas['version_id'] or '-'} ({cxas['version_status']});"
        f" trend regenerated: {info['points']} points, {info['regressions']} regression flags"
    )
    return code


def _app_tree_hash(app_dir: Path) -> str:
    from totto_suite import cxasapi  # pure helpers; SCRAPI stays unimported

    return cxasapi.app_tree_hash(app_dir)


# --------------------------------------------------------------------------
# snapshot
# --------------------------------------------------------------------------


def _safe_label(label: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_-]+", "_", label.strip()).strip("_")
    if not cleaned:
        raise ValueError("label must contain letters or digits")
    return cleaned[:40]


def _read(step: str, fn, errors: dict, *a, **kw):
    """Runs one read-only call; records classified errors instead of dying."""
    try:
        return fn(*a, **kw)
    except Exception as e:  # pylint: disable=broad-except
        infra = taxonomy.classify_exception(e)
        errors[step] = {
            "kind": infra.kind if infra else "error",
            "detail": (infra.message() if infra else f"{type(e).__name__}: {e}")[:500],
        }
        _log(f"  ! {step} failed: {errors[step]['detail']}")
        return None


def _app_state(app: dict | None) -> dict:
    if not app:
        return {"update_time": None, "etag": None}
    return {"update_time": app["update_time"], "etag": app["etag"]}


def _iso_seconds(ts: str | None) -> str | None:
    """'2026-09-28T20:55:38.643615Z' -> '2026-09-28T20:55:38Z'."""
    if not ts:
        return None
    return re.sub(r"\.\d+Z$", "Z", ts)


def _diff_markdown(result: dict) -> str:
    lines = [
        "# Live export vs repo commits (normalized)",
        "",
        f"Export: `{result['export_dir']}` (normalized tree hash `{result['export_tree_hash']}`).",
        f"Nearest source commit: `{result['nearest_source_commit']}`;"
        f" identical commits: {', '.join('`' + c + '`' for c in result['identical_commits']) or 'none'}.",
        "",
        "Normalization rules (applied to both sides; the raw file-level view is"
        " listed per commit so nothing is hidden):",
        "",
        *[f"- {rule}" for rule in result["normalization_rules"]],
        "",
        f"Platform-managed app.json keys found in the live export (excluded by N5): "
        f"`{json.dumps(result['server_managed_live'], sort_keys=True)}`",
        "",
        "| commit | time | identical (normalized) | differing | only in commit | only in live | raw differing / only-commit / only-live |",
        "|---|---|---|---|---|---|---|",
    ]
    for c in result["commits"]:
        raw = c["raw"]
        lines.append(
            f"| `{c['short']}` | {c['time']} | {'yes' if c['identical'] else 'no'} |"
            f" {len(c['differing_files'])} | {len(c['only_in_commit'])} | {len(c['only_in_live'])} |"
            f" {len(raw['differing'])} / {len(raw['only_left'])} / {len(raw['only_right'])} |"
        )
    for c in result["commits"]:
        lines += ["", f"## `{c['short']}` {c['subject']}", ""]
        if c["identical"]:
            lines.append("Identical after normalization.")
        for key, title in (
            ("differing_files", "Differing files"),
            ("only_in_commit", "Only in commit"),
            ("only_in_live", "Only in live export"),
        ):
            if c[key]:
                lines.append(f"{title}: " + ", ".join(f"`{p}`" for p in c[key]))
        lines.append(
            "Raw (un-normalized) view: differing "
            + (", ".join(f"`{p}`" for p in c["raw"]["differing"]) or "none")
            + "; only in commit "
            + (", ".join(f"`{p}`" for p in c["raw"]["only_left"]) or "none")
            + "; only in live "
            + (", ".join(f"`{p}`" for p in c["raw"]["only_right"]) or "none")
        )
        if c["commit"] in (result["nearest_source_commit_full"], result["head"]) and c["unified_diffs"]:
            lines += ["", "```diff"]
            for rel in sorted(c["unified_diffs"]):
                lines.append(c["unified_diffs"][rel].rstrip("\n"))
            lines.append("```")
        elif c["unified_diffs"]:
            lines.append("(unified diffs for this commit are in diff_vs_commits.json)")
        if c.get("raw_unified_diffs"):
            lines += [
                "",
                "Raw differences absorbed by the normalization rules (JSON pretty-printed"
                " with sorted keys, nothing else changed):",
                "",
                "```diff",
            ]
            for rel in sorted(c["raw_unified_diffs"]):
                lines.append(c["raw_unified_diffs"][rel].rstrip("\n"))
            lines.append("```")
    return "\n".join(lines) + "\n"


def diff_against_commits(export_app_dir: Path, export_rel: str) -> dict:
    from totto_suite import cxasapi

    commits = gitinfo.list_commits()
    head = gitinfo.head_commit()
    out = []
    live_managed = {}
    with tempfile.TemporaryDirectory(prefix="totto_commits_") as td:
        for c in commits:
            dest = Path(td) / c["short"]
            commit_app = gitinfo.archive_subdir(c["commit"], "cxas_app", dest)
            d = cxasapi.diff_app_trees(
                commit_app,
                export_app_dir,
                f"commit:{c['short']}/cxas_app",
                "live-export/cxas_app",
            )
            live_managed = d["server_managed_right"]
            out.append(
                {
                    **c,
                    "has_cxas_app": commit_app.is_dir(),
                    "identical": d["identical"],
                    "differing_files": d["differing_files"],
                    "only_in_commit": d["only_left"],
                    "only_in_live": d["only_right"],
                    "commit_tree_hash": d["left_tree_hash"],
                    "raw": d["raw"],
                    "server_managed_commit": d["server_managed_left"],
                    "unified_diffs": d["unified_diffs"],
                }
            )

        nearest = pick_source_commit(out)
        if nearest is not None:
            nearest["raw_unified_diffs"] = cxasapi.raw_pretty_diffs(
                Path(td) / nearest["short"] / "cxas_app",
                export_app_dir,
                f"commit:{nearest['short']}/cxas_app",
                "live-export/cxas_app",
            )
    identical = [c["commit"] for c in out if c["identical"]]
    return {
        "export_dir": export_rel,
        "export_tree_hash": _app_tree_hash(export_app_dir),
        "head": head,
        "normalization_rules": cxasapi.NORMALIZATION_RULES,
        "server_managed_live": live_managed,
        "identical_commits": [gitinfo.short(c) for c in identical],
        "identical_commits_full": identical,
        "nearest_source_commit": gitinfo.short(nearest["commit"]) if nearest else None,
        "nearest_source_commit_full": nearest["commit"] if nearest else None,
        "nearest_source_rule": SOURCE_COMMIT_RULE,
        "nearest_distance_files": commit_distance(nearest) if nearest else None,
        "commits": out,
    }


SOURCE_COMMIT_RULE = (
    "fewest differing files after normalization; among the newest such"
    " commits, the oldest commit of the contiguous run with the same"
    " normalized cxas_app (the commit that introduced this content)"
)


def commit_distance(c: dict) -> int:
    return len(c["differing_files"]) + len(c["only_in_commit"]) + len(c["only_in_live"])


def pick_source_commit(commits: list[dict]) -> dict | None:
    """Returns the commit that introduced the content closest to the export.

    ``commits`` is newest-first (``git log`` order) with ``differing_files``,
    ``only_in_commit``, ``only_in_live`` and ``commit_tree_hash``. Commits
    that did not touch the agent (e.g. suite-only commits) share the tree
    hash of their parent, so walking back to the oldest member of the run
    yields the commit that authored the agent content.
    """
    if not commits:
        return None
    best = min(commit_distance(c) for c in commits)
    i = next(k for k, c in enumerate(commits) if commit_distance(c) == best)
    tree = commits[i].get("commit_tree_hash")
    while i + 1 < len(commits) and commits[i + 1].get("commit_tree_hash") == tree:
        i += 1
    return commits[i]


def cmd_snapshot(args: argparse.Namespace) -> int:
    from totto_suite import cxasapi

    label = _safe_label(args.label)
    started = _now()
    stamp = started.strftime("%Y%m%dT%H%M%SZ")
    app_name = config.app_name()
    snap_dir = config.SNAPSHOTS_DIR / f"{stamp}_{label}"
    snap_rel = config.repo_relative(snap_dir)
    snap_dir.mkdir(parents=True, exist_ok=False)
    suite_head = gitinfo.head_commit()
    suite_dirty = gitinfo.dirty_state(include_suite=True)
    errors: dict = {}
    _log(f"snapshot {label} of {app_name}")
    _log(f"  dir: {snap_rel}")

    # (1) read-only inventory.
    _log("[1/5] read-only inventory")
    before = _read("get_app(before)", cxasapi.get_app, errors, app_name)
    if before is None:
        _log("cannot read the app; aborting (nothing created).")
        return EXIT_CRASH
    raw = before["raw"]
    _log(f"  app update_time={before['update_time']} etag={before['etag']}")
    versions = _read("list_versions", cxasapi.list_versions, errors, app_name) or []
    _log(f"  listed versions: {len(versions)}")
    hidden = []
    for vid in config.KNOWN_HIDDEN_VERSION_IDS:
        v = _read(f"get_version({vid})", cxasapi.get_version, errors, vid, app_name)
        hidden.append(
            {
                "id": vid,
                "fetchable": v is not None,
                "in_version_list": any(x["id"] == vid for x in versions),
                "version": v,
            }
        )
        _log(f"  known hidden version {vid}: fetchable={v is not None}")
    evaluations = _read("list_evaluations", cxasapi.list_evaluations, errors, app_name)
    runs = _read("list_evaluation_runs", cxasapi.list_evaluation_runs, errors, app_name)
    _log(
        f"  evaluations: {None if evaluations is None else len(evaluations)};"
        f" evaluation runs: {None if runs is None else len(runs)}"
    )
    conv_counts = {}
    for source in ("LIVE", "SIMULATOR", "EVAL", "AGENT_TOOL"):
        convs = _read(
            f"list_conversations(24h,{source})",
            cxasapi.list_conversations,
            errors,
            "24h",
            source,
            app_name,
        )
        conv_counts[source] = None if convs is None else len(convs)
    _log(f"  conversations in the last 24h by source: {conv_counts}")
    inventory = {
        "captured_at": _iso(started),
        "app_name": app_name,
        "app": {
            "display_name": before["display_name"],
            "create_time": before["create_time"],
            "update_time": before["update_time"],
            "etag": before["etag"],
            "model_settings": raw.get("modelSettings"),
            "guardrails": raw.get("guardrails", []),
            "variable_declarations": raw.get("variableDeclarations", []),
            "root_agent": raw.get("rootAgent"),
            "logging_settings": raw.get("loggingSettings"),
            "deployment_count": raw.get("deploymentCount", 0),
            "tool_execution_mode": raw.get("toolExecutionMode"),
            "locked": raw.get("locked", False),
            "pinned": raw.get("pinned", False),
        },
        "app_raw": raw,
        "versions": versions,
        "known_hidden_versions": hidden,
        "evaluations": evaluations,
        "evaluation_runs": runs,
        "conversations_24h_by_source": conv_counts,
        "read_errors": errors,
    }
    (snap_dir / "inventory.json").write_text(
        json.dumps(inventory, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )

    # (2) inline export into the snapshot dir.
    _log("[2/5] inline export (gcs_uri=None)")
    zip_bytes = _read("export_app", cxasapi.export_app_bytes, errors, app_name)
    if zip_bytes is None:
        _log("export failed; aborting before creating a version.")
        return EXIT_CRASH
    (snap_dir / "export.zip").write_bytes(zip_bytes)
    export_app_dir = snap_dir / "cxas_app"
    members = cxasapi.extract_export(zip_bytes, export_app_dir)
    export_rel = config.repo_relative(export_app_dir)
    zip_sha = hashlib.sha256(zip_bytes).hexdigest()
    _log(f"  export.zip {len(zip_bytes)} bytes sha256={zip_sha[:16]}...; {len(members)} files -> {export_rel}")

    # (3) normalized diff against every commit.
    _log("[3/5] normalized diff vs every commit (git archive)")
    diff = diff_against_commits(export_app_dir, export_rel)
    (snap_dir / "diff_vs_commits.json").write_text(
        json.dumps(diff, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    (snap_dir / "diff_vs_commits.md").write_text(_diff_markdown(diff), encoding="utf-8")
    for c in diff["commits"]:
        _log(
            f"  {c['short']} {c['time']}: identical={c['identical']}"
            f" differing={c['differing_files']} only_in_commit={c['only_in_commit']}"
            f" only_in_live={c['only_in_live']}"
        )
    _log(
        f"  nearest source commit: {diff['nearest_source_commit']}"
        f" (distance {diff['nearest_distance_files']} files);"
        f" identical commits: {diff['identical_commits']}"
    )

    # (4) version snapshot.
    _log("[4/5] create_version snapshot")
    display_name = f"r3-{label}-{stamp}"
    description = (
        f"Team 3 test-suite snapshot of the live app as found; evidence in repo"
        f" path {snap_rel} (python -m totto_suite snapshot)"
    )
    requested_at = _now()
    created = _read(
        "create_version", cxasapi.create_version, errors, display_name, description, app_name
    )
    if created is None:
        _log("create_version failed; snapshot evidence kept, no record written.")
        return EXIT_CRASH
    fetched = _read("get_version(created)", cxasapi.get_version, errors, created["id"], app_name)
    listed_after = _read("list_versions(after)", cxasapi.list_versions, errors, app_name) or []
    in_list = any(v["id"] == created["id"] for v in listed_after)
    created_dt = None
    if created.get("create_time"):
        created_dt = datetime.datetime.strptime(
            created["create_time"], "%Y-%m-%dT%H:%M:%S.%fZ"
        ).replace(tzinfo=datetime.timezone.utc)
    returned_existing = created["display_name"] != display_name or (
        created_dt is not None
        and created_dt < requested_at - datetime.timedelta(seconds=60)
    )
    version_status = "in_version_list" if in_list else "hidden_fetchable"
    if fetched is None:
        _log("get_version on the returned id FAILED; cannot claim a fetchable version.")
    after = _read("get_app(after)", cxasapi.get_app, errors, app_name)
    state_before, state_after = _app_state(before), _app_state(after)
    unchanged = state_before == state_after
    expected = {}
    if args.expect_etag or args.expect_update_time:
        expected = {
            "etag": args.expect_etag,
            "update_time": args.expect_update_time,
            "etag_matches": (args.expect_etag == state_before["etag"]) if args.expect_etag else None,
            "update_time_matches": (
                args.expect_update_time == state_before["update_time"]
            )
            if args.expect_update_time
            else None,
        }
    version_doc = {
        "requested": {
            "display_name": display_name,
            "description": description,
            "requested_at": _iso(requested_at),
        },
        "returned": created,
        "returned_existing_version": returned_existing,
        "get_version": fetched,
        "get_version_ok": fetched is not None and fetched["name"] == created["name"],
        "in_version_list": in_list,
        "version_status": version_status,
        "listed_versions_after": listed_after,
        "app_state_before": state_before,
        "app_state_after": state_after,
        "app_unchanged": unchanged,
        "expected_reference": expected,
        "errors": errors,
    }
    (snap_dir / "version.json").write_text(
        json.dumps(version_doc, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    _log(
        f"  version: {created['name']}\n  display_name={created['display_name']!r}"
        f" create_time={created['create_time']} returned_existing={returned_existing}"
    )
    _log(f"  get_version ok={version_doc['get_version_ok']}; in list_versions={in_list} -> {version_status}")
    _log(f"  app before={state_before} after={state_after} unchanged={unchanged}")
    if expected:
        _log(f"  reference check: {expected}")
    if not version_doc["get_version_ok"]:
        return EXIT_CRASH

    if not args.commit:
        _log("[5/5] --commit not given: snapshot left uncommitted; no run record written.")
        return EXIT_OK

    # (5) commit snapshot (S), then record + trend (second commit).
    _log("[5/5] path-limited commits")
    s_commit = gitinfo.commit_paths(
        f"history: live app snapshot '{label}' ({stamp}), CXAS version {created['id']}",
        [snap_rel],
    )
    _log(f"  commit S (snapshot): {s_commit}")
    agent_rel = f"{snap_rel}/cxas_app"
    agent_dirty = gitinfo.dirty_state(agent_path=agent_rel, include_suite=False)
    nearest = next(
        (c for c in diff["commits"] if c["commit"] == diff["nearest_source_commit_full"]),
        None,
    )
    model = (raw.get("modelSettings") or {}).get("model") or "unknown"
    run_id = records.make_run_id("snapshot", s_commit, started)
    record = records.build_record(
        mode="snapshot",
        run_id=run_id,
        started_at=_iso(started),
        finished_at=_iso(_now()),
        point_time=_iso_seconds(before["update_time"]) or _iso(started),
        agent={
            "commit": s_commit,
            "path": agent_rel,
            "tree_hash": diff["export_tree_hash"],
            "dirty": agent_dirty["dirty"],
            "dirty_paths_relevant": agent_dirty["dirty_paths_relevant"],
            "dirty_paths_unrelated": agent_dirty["dirty_paths_unrelated"],
            "nearest_source_commit": diff["nearest_source_commit_full"],
            "identical_source_commits": diff["identical_commits_full"],
            "diff_vs_nearest_source": {
                "identical_normalized": nearest["identical"] if nearest else None,
                "differing_files": nearest["differing_files"] if nearest else None,
                "only_in_commit": nearest["only_in_commit"] if nearest else None,
                "only_in_live": nearest["only_in_live"] if nearest else None,
                "raw": nearest["raw"] if nearest else None,
                "server_managed_live": diff["server_managed_live"],
                "details": f"{snap_rel}/diff_vs_commits.md",
            },
        },
        suite={
            "commit": suite_head,
            "dirty": suite_dirty["suite_dirty"],
            "dirty_paths": suite_dirty["suite_dirty_paths"],
        },
        cxas={
            "app": app_name,
            "version_id": created["id"],
            "version_status": version_status,
            "model": model,
            "app_update_time": before["update_time"],
            "app_etag": before["etag"],
        },
        rationale=args.rationale,
        tests=[],
        extra={
            "snapshot": {
                "dir": snap_rel,
                "inventory": f"{snap_rel}/inventory.json",
                "version_evidence": f"{snap_rel}/version.json",
                "export_zip_sha256": zip_sha,
                "version_name": created["name"],
                "version_display_name": created["display_name"],
                "version_create_time": created["create_time"],
                "returned_existing_version": returned_existing,
                "get_version_ok": True,
                "app_state_before": state_before,
                "app_state_after": state_after,
                "app_unchanged": unchanged,
            }
        },
    )
    path = records.write_record(record)
    info = trend.generate()
    rel_paths = [
        config.repo_relative(path),
        config.repo_relative(config.INDEX_PATH),
        config.repo_relative(config.TREND_MD_PATH),
        config.repo_relative(config.TREND_HTML_PATH),
    ]
    r_commit = gitinfo.commit_paths(
        f"history: record {run_id} (live snapshot, version {created['id']})", rel_paths
    )
    _log(f"  record: {rel_paths[0]}")
    _log(f"  commit R (record + index + trend): {r_commit}")
    _log(f"  trend: {info['points']} points, {info['regressions']} regression flags")
    return EXIT_OK


# --------------------------------------------------------------------------
# trend / delegated commands
# --------------------------------------------------------------------------


def cmd_trend(_args: argparse.Namespace) -> int:
    info = trend.generate()
    _log(f"trend: {info['points']} points, {info['regressions']} regression flags")
    for p in info["paths"]:
        _log(f"  wrote {config.repo_relative(p)}")
    return EXIT_OK


def run_delegated(command: str, argv: list[str]) -> int:
    module_name, owner = DELEGATED[command]
    try:
        mod = importlib.import_module(module_name)
    except ModuleNotFoundError as e:
        if e.name != module_name:
            raise  # the module exists but one of its imports is missing
        _log(
            f"command '{command}' is not available yet (owned by milestone"
            f" {owner}; expected module {module_name} with main(argv) -> int)."
        )
        return EXIT_CRASH
    main_fn = getattr(mod, "main", None)
    if not callable(main_fn):
        _log(f"{module_name} has no main(argv); command '{command}' unavailable.")
        return EXIT_CRASH
    return int(main_fn(argv) or 0)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="python -m totto_suite",
        description="Totto CXAS test suite (one command for every mode).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    sub = p.add_subparsers(dest="command", required=True)

    off = sub.add_parser("offline", help="fast hermetic layers; records a run")
    off.add_argument("--app-dir", default=None, help="agent dir under test (default cxas_app)")
    off.add_argument("--rationale", default=None, help="why this change (default: HEAD subject)")
    off.add_argument("--no-record", action="store_true", help="do not write evals/history")
    off.add_argument("--now", default=None, help="ISO time override passed to layers as ctx['now']")
    off.set_defaults(func=cmd_offline)

    snap = sub.add_parser("snapshot", help="live inventory + export + diff + version snapshot")
    snap.add_argument("--label", required=True)
    snap.add_argument("--commit", action="store_true", help="commit snapshot, then record")
    snap.add_argument(
        "--rationale", default="snapshot of the live app", help="why this point exists"
    )
    snap.add_argument("--expect-etag", default=None, help="reference etag to compare with")
    snap.add_argument("--expect-update-time", default=None, help="reference update_time")
    snap.set_defaults(func=cmd_snapshot)

    tr = sub.add_parser("trend", help="regenerate index.json, TREND.md, trend.html")
    tr.set_defaults(func=cmd_trend)

    for name, (module_name, owner) in DELEGATED.items():
        d = sub.add_parser(name, help=f"delegated to {module_name}.main(argv) [{owner}]", add_help=False)
        d.add_argument("rest", nargs=argparse.REMAINDER)
    return p


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] in DELEGATED:
        return run_delegated(argv[0], argv[1:])
    args = build_parser().parse_args(argv)
    try:
        return int(args.func(args))
    except KeyboardInterrupt:
        _log("interrupted")
        return EXIT_CRASH
