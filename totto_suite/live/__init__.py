"""Live evaluation suite entry point (`python -m totto_suite live`)."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path
import sys
import time

from totto_suite import config, cxasapi, gitinfo, ids, oracle, records, trend
from totto_suite import layers as layers_pkg
from totto_suite.cli import EXIT_CRASH, exit_code_for, print_summary
from totto_suite.live.runner import TOOL_MODES, fetch_live_cxas_metadata


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="totto_suite live",
        description="Run the live CXAS evaluation suite (sequential, parallel=1).",
    )
    parser.add_argument(
        "--repeats",
        type=int,
        default=3,
        help="Number of repeats for non-deterministic live layers (default: 3).",
    )
    parser.add_argument(
        "--rationale",
        default="Live evaluation suite run against deployed CXAS app",
        help="Rationale stored in the run record.",
    )
    parser.add_argument(
        "--run-id",
        default=None,
        help="Optional explicit run ID.",
    )
    parser.add_argument(
        "--target",
        choices=ids.APP_REFS,
        default="live",
        help="Which app this is; stored as the record's app_ref (default: live).",
    )
    parser.add_argument(
        "--app-name",
        default=None,
        help="Full CXAS app resource name (default: $TOTTO_APP_NAME / env /"
        " gecx-config.json for --target).",
    )
    parser.add_argument(
        "--tool-mode",
        choices=TOOL_MODES,
        default="real",
        help="real tools (default) or platform tool fakes (use_tool_fakes / FAKE).",
    )
    parser.add_argument(
        "--layers",
        default=None,
        help="Optional comma-separated subset of live layer names (e.g. tools,goldens).",
    )
    parser.add_argument(
        "--now",
        default=None,
        help="ISO-8601 UTC timestamp override for runtime date oracle.",
    )
    parser.add_argument(
        "--no-record",
        action="store_true",
        help="Run without writing to evals/history/runs/.",
    )
    args = parser.parse_args(argv)
    try:
        args.app_name = ids.resolve_app_name(args.app_name, args.target)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_CRASH

    started = datetime.now(timezone.utc)
    t0 = time.monotonic()
    now_dt = oracle.parse_utc(args.now) if args.now else started
    head = gitinfo.head_commit()
    run_id = args.run_id or records.make_run_id("live", head, started)

    all_mods = layers_pkg.discover("live")
    if args.layers:
        wanted = {
            x.strip().removeprefix("live_")
            for x in args.layers.split(",")
            if x.strip()
        }
        mods = [m for m in all_mods if m.name in wanted or f"live_{m.name}" in wanted]
    else:
        mods = all_mods

    if not mods:
        print("error: no matching live layer modules found.", file=sys.stderr)
        return EXIT_CRASH

    artifacts_dir = config.ARTIFACTS_DIR / run_id
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    app_dir = config.DEFAULT_APP_DIR

    ctx = {
        "repo_root": str(config.REPO_ROOT),
        "app_dir": str(app_dir),
        "mode": "live",
        "repeats": max(1, args.repeats),
        "now": now_dt.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "now_dt": now_dt,
        "run_id": run_id,
        "artifacts_dir": str(artifacts_dir),
        "app_name": args.app_name,
        "tool_mode": args.tool_mode,
    }

    print(
        f"[live] run {run_id}: repeats={ctx['repeats']} "
        f"modules={[m.module for m in mods]}",
        flush=True,
    )
    outcomes = []
    for mod in mods:
        print(f"[live] running {mod.module} ...", flush=True)
        outcome = layers_pkg.run_layer(mod, ctx)
        state = "CRASHED" if outcome.crashed else f"{len(outcome.results)} results"
        print(
            f"[live] {mod.module}: {state} in {outcome.duration_s:.2f}s",
            flush=True,
        )
        outcomes.append(outcome)

    crashed = [o for o in outcomes if o.crashed]
    if crashed:
        for o in crashed:
            print(f"SUITE CRASH in {o.layer.module}:\n{o.error}", file=sys.stderr)
        return EXIT_CRASH

    from totto_suite.ci_gate import finalize_test, redact_artifacts  # pylint: disable=import-outside-toplevel

    # App-relative platform IDs + tool_mode/fake_verified; no identifiers.
    tests = sorted(
        (finalize_test(r, args.tool_mode, args.app_name) for o in outcomes for r in o.results),
        key=lambda t: (t["id"], t.get("repeat", 1)),
    )
    if not tests:
        print("Live layers returned no results; nothing recorded.", file=sys.stderr)
        return EXIT_CRASH

    print_summary(tests)
    elapsed = time.monotonic() - t0
    code = exit_code_for(tests)

    if args.no_record:
        import shutil

        shutil.rmtree(artifacts_dir, ignore_errors=True)
        print("--no-record: nothing written to evals/history/.", flush=True)
        return code

    rel_app = config.repo_relative(app_dir)
    dirty = gitinfo.dirty_state(agent_path=rel_app, include_suite=True)
    tree_hash = cxasapi.app_tree_hash(app_dir)
    finished = datetime.now(timezone.utc)
    started_iso = gitinfo.iso_utc(started)
    finished_iso = gitinfo.iso_utc(finished)
    version_hint = next(
        (t["platform_ids"]["app_version"] for t in tests if t["platform_ids"].get("app_version")),
        None,
    )
    cxas_meta = fetch_live_cxas_metadata(
        args.app_name,
        app_ref=args.target,
        version_hint=ids.to_full(args.app_name, version_hint) if version_hint else None,
    )
    cxas_meta = ids.redact_obj({k: cxas_meta.get(k) for k in records.CXAS_KEYS}, args.app_name)

    record = records.build_record(
        mode="live",
        run_id=run_id,
        started_at=started_iso,
        finished_at=finished_iso,
        point_time=started_iso,
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
        cxas=cxas_meta,
        rationale=args.rationale,
        tests=tests,
        extra={
            "app_ref": args.target,
            "tool_mode": args.tool_mode,
            "repeats": ctx["repeats"],
            "duration_s": round(elapsed, 2),
        },
    )
    path = records.write_record(record)
    redact_artifacts(artifacts_dir, args.app_name)
    info = trend.generate()
    print(f"record: {config.repo_relative(path)}", flush=True)
    print(
        f"version: {cxas_meta['version_id']} ({cxas_meta['version_status']}); "
        f"trend regenerated: {info['points']} points",
        flush=True,
    )
    return code
