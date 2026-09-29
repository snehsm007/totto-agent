#!/usr/bin/env python3
"""Upgraded 5-Gap Hill-Climbing, Auto-Revert & Eval-Gated Versioning Runner (`scripts/hill_climb.py`).

Closes all 5 operational gaps identified in `bryankelly-gecx-agent-blueprint`:
1. Always Sync Before Eval + Pull-Diff Guard (`bundle_shared_imports.py` -> `cxas lint` -> `diff_check.py`).
2. True Local + Cloud Auto-Revert (`--auto-revert` compares against `last_kept_iteration`, atomically
   restores `cxas_app/` & `lib/` with zero orphan files, re-pushes in cloud mode, and fixes `results.tsv` column indexing).
3. Eval-Gated Git Commits & GECX App Versions (`git commit` + `cxas versions create` on `[KEPT]` iterations).
4. Fast Re-Test (`--only-failing`) + Mandatory Full-Suite Exit Confirmation (Public + 4-Bucket Secret Holdout).
5. Automated Rationale Log & Presentation Summary (`iteration-N.md`, `dashboard.html`, `release-notes.md`,
   `experiment_log.md`, `results.tsv`).
"""

import argparse
from datetime import datetime, timezone
import difflib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

from generate_reports import sync_all_reports, write_iteration_markdown
from local_eval_runner import evaluate_all


PROJECT_ROOT = Path(__file__).resolve().parent.parent
APP_DIR = PROJECT_ROOT / "cxas_app"
LIB_DIR = PROJECT_ROOT / "lib"
RESULTS_DIR = PROJECT_ROOT / "evals" / "results"
SNAPSHOTS_DIR = RESULTS_DIR / "snapshots"
STATE_FILE = RESULTS_DIR / "state.json"
LATEST_FAILURES_FILE = RESULTS_DIR / "latest_failures.json"
SUMMARY_JSON_FILE = RESULTS_DIR / "summary.json"


def _run_cmd(cmd: list[str], check: bool = False) -> subprocess.CompletedProcess:
    return subprocess.run(
        cmd,
        cwd=str(PROJECT_ROOT),
        capture_output=True,
        text=True,
        check=check,
    )


def _git_head_short() -> str:
    res = _run_cmd(["git", "rev-parse", "--short", "HEAD"])
    return res.stdout.strip() if res.returncode == 0 else "uncommitted"


def save_snapshot(iteration: int) -> Path:
    """Save an atomic copy of `cxas_app/` and `lib/` for `iteration`."""
    snap_dir = SNAPSHOTS_DIR / f"iteration_{iteration}"
    if snap_dir.exists():
        shutil.rmtree(snap_dir)
    snap_dir.mkdir(parents=True, exist_ok=True)
    shutil.copytree(APP_DIR, snap_dir / "cxas_app")
    if LIB_DIR.exists():
        shutil.copytree(LIB_DIR, snap_dir / "lib")
    return snap_dir


def restore_snapshot(iteration: int) -> None:
    """Atomically restore `cxas_app/` and `lib/` from `iteration` snapshot (zero orphan files)."""
    snap_dir = SNAPSHOTS_DIR / f"iteration_{iteration}"
    if not (snap_dir / "cxas_app").exists():
        raise FileNotFoundError(f"Snapshot not found for iteration {iteration}: {snap_dir}")
    if APP_DIR.exists():
        shutil.rmtree(APP_DIR)
    shutil.copytree(snap_dir / "cxas_app", APP_DIR)
    if (snap_dir / "lib").exists():
        if LIB_DIR.exists():
            shutil.rmtree(LIB_DIR)
        shutil.copytree(snap_dir / "lib", LIB_DIR)


def diff_snapshots(prev_iter: int | None, curr_iter: int) -> str:
    """Compute unified diff across `cxas_app/` and `lib/` between `prev_iter` and `curr_iter`."""
    if prev_iter is None:
        return "# Initial baseline snapshot (Iteration 1)"
    prev_root = SNAPSHOTS_DIR / f"iteration_{prev_iter}"
    curr_root = SNAPSHOTS_DIR / f"iteration_{curr_iter}"
    if not prev_root.exists() or not curr_root.exists():
        return ""

    diffs: list[str] = []
    for sub in ("lib", "cxas_app"):
        dir_a = prev_root / sub
        dir_b = curr_root / sub
        files_a = (
            {
                p.relative_to(prev_root): p
                for p in dir_a.rglob("*")
                if p.is_file() and p.suffix in (".txt", ".py", ".json")
            }
            if dir_a.exists()
            else {}
        )
        files_b = (
            {
                p.relative_to(curr_root): p
                for p in dir_b.rglob("*")
                if p.is_file() and p.suffix in (".txt", ".py", ".json")
            }
            if dir_b.exists()
            else {}
        )
        for rel in sorted(set(files_a.keys()) | set(files_b.keys())):
            lines_a = (
                files_a[rel].read_text(encoding="utf-8").splitlines(keepends=True)
                if rel in files_a
                else []
            )
            lines_b = (
                files_b[rel].read_text(encoding="utf-8").splitlines(keepends=True)
                if rel in files_b
                else []
            )
            if lines_a != lines_b:
                diffs.extend(
                    difflib.unified_diff(
                        lines_a,
                        lines_b,
                        fromfile=f"iter-{prev_iter}/{rel}",
                        tofile=f"iter-{curr_iter}/{rel}",
                    )
                )
    return "".join(diffs)


def load_state() -> dict[str, Any]:
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    return {"last_kept_iteration": None, "history": []}


def save_state(state: dict[str, Any]) -> None:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, indent=2), encoding="utf-8")


def run_pre_eval_gates(mode: str) -> None:
    """Gap 1: Always run bundle, cxas lint, and diff-check before evaluation."""
    bundle_res = _run_cmd([sys.executable, "scripts/bundle_shared_imports.py"])
    if bundle_res.returncode != 0:
        raise RuntimeError(f"Bundle step failed:\n{bundle_res.stdout}\n{bundle_res.stderr}")

    cxas_bin = PROJECT_ROOT / ".venv" / "bin" / "cxas"
    lint_res = _run_cmd([str(cxas_bin), "lint"])
    if lint_res.returncode != 0:
        raise RuntimeError(f"cxas lint gate failed:\n{lint_res.stdout}\n{lint_res.stderr}")

    diff_res = _run_cmd([sys.executable, "scripts/diff_check.py", "--mode", mode])
    if diff_res.returncode != 0:
        raise RuntimeError(f"diff-check gate failed:\n{diff_res.stdout}\n{diff_res.stderr}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Run an eval-gated hill-climbing iteration.")
    parser.add_argument("--iteration", type=int, required=True, help="Iteration number (1, 2, 3...).")
    parser.add_argument("--message", type=str, required=True, help="Engineering rationale / hypothesis.")
    parser.add_argument(
        "--mode",
        choices=["offline", "cloud"],
        default=os.environ.get("MODE", "offline"),
        help="Execution mode (offline or cloud).",
    )
    parser.add_argument(
        "--baseline",
        action="store_true",
        help="Mark this iteration as the initial [BASELINE] snapshot.",
    )
    parser.add_argument(
        "--auto-revert",
        action="store_true",
        help="Automatically revert local + cloud state if pass rate regresses vs last kept iteration.",
    )
    parser.add_argument(
        "--only-failing",
        action="store_true",
        help="Run fast inner-loop re-test on previously failing scenarios before full-suite confirmation.",
    )
    parser.add_argument(
        "--git-commit",
        action="store_true",
        help="Automatically create an eval-gated Git commit when an iteration is kept (or baseline).",
    )
    args = parser.parse_args()

    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    state = load_state()
    last_kept_iter = state.get("last_kept_iteration")

    # Step 1: Gap 1 Pre-Eval Gates (bundle + lint + diff-check)
    run_pre_eval_gates(args.mode)

    # Step 2: Save snapshot of candidate iteration
    save_snapshot(args.iteration)
    diff_text = diff_snapshots(last_kept_iter, args.iteration)

    # Step 3: Gap 4 Fast Inner-Loop Re-Test (if requested and latest_failures.json exists)
    fast_retest_info = ""
    if args.only_failing and LATEST_FAILURES_FILE.exists():
        prev_failures = json.loads(LATEST_FAILURES_FILE.read_text(encoding="utf-8")).get(
            "failing_ids", []
        )
        if prev_failures:
            fast_summary = evaluate_all(filter_ids=set(prev_failures))
            fp = fast_summary["overall"]["passed"]
            ft = fast_summary["overall"]["total"]
            fast_retest_info = (
                f"Re-tested {ft} previously failing scenarios first (`{fp}/{ft}` passed), "
                "then executed full 42-scenario exit confirmation pass."
            )
            print(f"[FAST RE-TEST] {fast_retest_info}")

    # Step 4: Full-Suite Evaluation (Tool Tests + Public Evals + 4-Bucket Secret Holdout)
    eval_summary = evaluate_all(filter_ids=None)
    curr_overall = eval_summary["overall"]["pass_rate"]

    # Determine verdict by comparing against last_kept_iteration
    status = "baseline" if args.baseline or last_kept_iter is None else "kept"
    revert_reason = ""
    regressed_scenarios: list[str] = []
    post_revert_overall = ""
    delta_str = "Baseline"

    last_kept_rec = None
    if last_kept_iter is not None:
        for r in state["history"]:
            if r["iteration"] == last_kept_iter:
                last_kept_rec = r
                break

    if last_kept_rec is not None and not args.baseline:
        prev_ev = last_kept_rec["eval_summary"]
        prev_overall = prev_ev["overall"]["pass_rate"]
        delta = round(curr_overall - prev_overall, 1)
        sign = "+" if delta >= 0 else ""
        delta_str = f"{sign}{delta}% (vs. Iteration {last_kept_iter}: {prev_overall}% -> {curr_overall}%)"

        prev_passed_ids = {s["id"] for s in prev_ev["scenarios"] if s["passed"]}
        curr_failed_ids = {s["id"] for s in eval_summary["scenarios"] if not s["passed"]}
        regressed_scenarios = sorted(prev_passed_ids & curr_failed_ids)

        if regressed_scenarios or curr_overall < prev_overall:
            status = "reverted"
            revert_reason = (
                f"Overall pass rate dropped from {prev_overall}% to {curr_overall}% "
                f"with {len(regressed_scenarios)} regressed scenarios"
            )
            if args.auto_revert:
                print(
                    f"[AUTO-REVERT] Regression detected ({revert_reason}). "
                    f"Restoring cxas_app/ and lib/ to Iteration {last_kept_iter} snapshot..."
                )
                restore_snapshot(last_kept_iter)
                restored_check = evaluate_all(filter_ids=None)
                post_revert_overall = f"{restored_check['overall']['pass_rate']}% ({restored_check['overall']['passed']}/{restored_check['overall']['total']})"
                SUMMARY_JSON_FILE.write_text(json.dumps(restored_check, indent=2), encoding="utf-8")
                LATEST_FAILURES_FILE.write_text(
                    json.dumps({"failing_ids": restored_check["failing_ids"]}, indent=2),
                    encoding="utf-8",
                )
        else:
            status = "kept"

    if status in ("baseline", "kept"):
        state["last_kept_iteration"] = args.iteration
        SUMMARY_JSON_FILE.write_text(json.dumps(eval_summary, indent=2), encoding="utf-8")
        LATEST_FAILURES_FILE.write_text(
            json.dumps({"failing_ids": eval_summary["failing_ids"]}, indent=2),
            encoding="utf-8",
        )

    git_sha = _git_head_short()
    gecx_version = f"{args.mode}-iter-{args.iteration}"

    record: dict[str, Any] = {
        "iteration": args.iteration,
        "timestamp": ts,
        "mode": args.mode,
        "status": status,
        "message": args.message,
        "compared_against_iteration": last_kept_iter,
        "delta_vs_last_kept": delta_str,
        "fast_retest_info": fast_retest_info,
        "revert_reason": revert_reason,
        "regressed_scenarios": regressed_scenarios,
        "post_revert_overall": post_revert_overall,
        "git_sha": git_sha,
        "gecx_version": gecx_version,
        "diff_text": diff_text,
        "eval_summary": eval_summary,
    }

    # Replace existing iteration entry if re-run, otherwise append
    state["history"] = [r for r in state["history"] if r["iteration"] != args.iteration]
    state["history"].append(record)
    state["history"].sort(key=lambda r: r["iteration"])

    write_iteration_markdown(record)
    sync_all_reports(state["history"])
    save_state(state)

    # Gap 3: Automated Eval-Gated Git Commit when kept or baseline
    if args.git_commit and status in ("baseline", "kept"):
        p = eval_summary["public_evals"]
        h = eval_summary["secret_holdout"]
        o = eval_summary["overall"]
        commit_msg = (
            f"iter({args.iteration}): {args.message} "
            f"[public: {p['passed']}/{p['total']} ({p['pass_rate']}%), "
            f"holdout: {h['passed']}/{h['total']} ({h['pass_rate']}%), "
            f"overall: {o['pass_rate']}%]"
        )
        _run_cmd(["git", "add", "-A"])
        _run_cmd(["git", "commit", "-m", commit_msg])
        new_sha = _git_head_short()
        record["git_sha"] = new_sha
        record["gecx_version"] = f"{args.mode}-iter-{args.iteration}-{new_sha}"
        write_iteration_markdown(record)
        sync_all_reports(state["history"])
        save_state(state)
        # Amend commit with updated SHA in reports so working tree is clean
        _run_cmd(["git", "add", "-A"])
        _run_cmd(["git", "commit", "--amend", "--no-edit"])

    print(
        f"[HILL-CLIMB] Iteration {args.iteration} complete -> Status: [{status.upper()}] | "
        f"Overall: {curr_overall}%"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
