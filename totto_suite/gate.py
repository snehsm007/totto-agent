"""Automatic pre-commit regression gate (`totto_suite gate`).

Implements Decision D2 from `plan.md`:
- Runs the offline suite against the candidate `cxas_app` directory (default:
  `<repo>/cxas_app` or `TOTTO_APP_DIR`).
- Compares per-scenario verdicts against the baseline (`HEAD:cxas_app` or an
  explicit `--baseline-dir` / `--baseline-record`).
- Blocks (exit code 1) if:
  1. `lint` layer fails (`cxas lint` or `bundle_shared_imports.py --check`),
  2. Any scenario flips `PASS -> FAIL` relative to the baseline (or a new
     agent-layer scenario fails),
  3. Any `selftest`, `grader`, or `regrade` test fails, or
  4. Any offline test fails when `--strict-zero-failures` is passed.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import tempfile
import time
from typing import Any

from totto_suite import config, cxasapi, gitinfo, records
from totto_suite import layers as layers_pkg
from totto_suite.taxonomy import Status


EXIT_GATE_PASS = 0
EXIT_GATE_BLOCKED = 1
EXIT_GATE_CRASH = 2

DEFAULT_GATE_LAYERS = (
    "lint",
    "config",
    "callbacks",
    "tools",
    "dates",
    "grader",
    "regrade",
    "selftest",
)

AGENT_DEPENDENT_LAYERS = (
    "lint",
    "config",
    "callbacks",
    "tools",
    "dates",
)


def _run_offline_layers_on_dir(
    app_dir: Path,
    repo_root: Path,
    layer_names: tuple[str, ...],
) -> tuple[list[dict[str, Any]], list[str]]:
    """Run specified offline layers on `app_dir` and return `(tests, crash_errors)`."""
    discovered = {m.name: m for m in layers_pkg.discover("offline")}
    all_results: list[dict[str, Any]] = []
    crashes: list[str] = []

    prev_env = os.environ.get("TOTTO_APP_DIR")
    os.environ["TOTTO_APP_DIR"] = str(app_dir)
    try:
        with tempfile.TemporaryDirectory(prefix="totto_gate_artifacts_") as art_dir:
            ctx = {
                "repo_root": str(repo_root),
                "app_dir": str(app_dir),
                "mode": "gate",
                "run_id": "gate_check",
                "artifacts_dir": art_dir,
                "repeats": 1,
                "now": None,
                "app_name": config.app_name(),
            }
            for name in layer_names:
                mod = discovered.get(name)
                if mod is None:
                    continue
                outcome = layers_pkg.run_layer(mod, ctx)
                if outcome.crashed:
                    crashes.append(f"{mod.module}: {outcome.error}")
                else:
                    all_results.extend(outcome.results)
    finally:
        if prev_env is None:
            os.environ.pop("TOTTO_APP_DIR", None)
        else:
            os.environ["TOTTO_APP_DIR"] = prev_env

    all_results.sort(key=lambda r: (str(r["id"]), int(r.get("repeat", 1))))
    return all_results, crashes


def _resolve_baseline_tests(
    *,
    repo_root: Path,
    baseline_dir: Path | None,
    baseline_record: Path | None,
    layer_names: tuple[str, ...],
) -> tuple[dict[str, str], str]:
    """Return `({test_id: status}, baseline_description)`."""
    if baseline_record is not None:
        rec = records.load_record(baseline_record.resolve())
        return (
            {str(t["id"]): str(t["status"]) for t in rec.get("tests", [])},
            f"record:{baseline_record.name}",
        )

    if baseline_dir is not None:
        b_dir = baseline_dir.resolve()
        agent_layers = tuple(l for l in layer_names if l in AGENT_DEPENDENT_LAYERS)
        tests, crashes = _run_offline_layers_on_dir(b_dir, repo_root, agent_layers)
        if crashes:
            raise RuntimeError(f"Baseline execution crashed: {'; '.join(crashes)}")
        return (
            {str(t["id"]): str(t["status"]) for t in tests},
            f"dir:{config.repo_relative(b_dir)}",
        )

    # Default: compare against HEAD:cxas_app.
    runs_dir = repo_root / "evals" / "history" / "runs"
    if not runs_dir.is_dir():
        runs_dir = config.RUNS_DIR
    try:
        head = gitinfo.head_commit(repo=repo_root)
    except Exception:
        head = None

    if head:
        with tempfile.TemporaryDirectory(prefix="totto_gate_head_") as td:
            try:
                head_app = gitinfo.archive_subdir(head, "cxas_app", Path(td), repo=repo_root)
            except Exception:
                head_app = None

            if head_app is not None and (head_app / "app.json").is_file():
                head_tree_hash = cxasapi.app_tree_hash(head_app)
                if runs_dir.is_dir():
                    for p in sorted(runs_dir.glob("*.json"), reverse=True):
                        try:
                            rec = records.load_record(p)
                        except Exception:
                            continue
                        if (
                            rec.get("mode") == "offline"
                            and rec.get("agent", {}).get("tree_hash") == head_tree_hash
                            and rec.get("tests")
                        ):
                            return (
                                {str(t["id"]): str(t["status"]) for t in rec["tests"]},
                                f"HEAD({head[:7]}) via record {rec['run_id']}",
                            )

                # Otherwise run agent-dependent offline layers directly on archived HEAD:cxas_app
                agent_layers = tuple(l for l in layer_names if l in AGENT_DEPENDENT_LAYERS)
                tests, crashes = _run_offline_layers_on_dir(head_app, repo_root, agent_layers)
                if not crashes:
                    return (
                        {str(t["id"]): str(t["status"]) for t in tests},
                        f"HEAD({head[:7]}):cxas_app",
                    )

    # Final fallback: latest offline record if available
    if runs_dir.is_dir():
        all_recs = records.load_all(runs_dir)
        latest_off = records.latest(all_recs, "offline")
        if latest_off and latest_off.get("tests"):
            return (
                {str(t["id"]): str(t["status"]) for t in latest_off["tests"]},
                f"latest_offline:{latest_off['run_id']}",
            )

    return {}, "no_prior_baseline"


def evaluate_gate(
    *,
    app_dir: Path | None = None,
    repo_root: Path | None = None,
    baseline_dir: Path | None = None,
    baseline_record: Path | None = None,
    layer_names: tuple[str, ...] = DEFAULT_GATE_LAYERS,
    strict_zero_failures: bool = False,
) -> dict[str, Any]:
    """Run the offline gate on `app_dir` and return a structured evaluation dict."""
    t0 = time.monotonic()
    repo_root_path = Path(repo_root).resolve() if repo_root else config.REPO_ROOT
    candidate_dir = Path(app_dir).resolve() if app_dir else config.app_dir()

    if not (candidate_dir / "app.json").is_file():
        return {
            "passed": False,
            "exit_code": EXIT_GATE_CRASH,
            "error": f"Candidate directory {candidate_dir} does not contain app.json",
            "regressions": [],
            "existing_failures": [],
            "lint_failures": [],
            "selftest_failures": [],
            "all_failures": [],
        }

    baseline_map, baseline_source = _resolve_baseline_tests(
        repo_root=repo_root_path,
        baseline_dir=baseline_dir,
        baseline_record=baseline_record,
        layer_names=layer_names,
    )

    candidate_tests, crashes = _run_offline_layers_on_dir(
        candidate_dir, repo_root_path, layer_names
    )
    duration_s = round(time.monotonic() - t0, 2)

    if crashes:
        return {
            "passed": False,
            "exit_code": EXIT_GATE_CRASH,
            "error": "; ".join(crashes),
            "baseline_source": baseline_source,
            "duration_s": duration_s,
            "regressions": [],
            "existing_failures": [],
            "lint_failures": [],
            "selftest_failures": [],
            "all_failures": [],
        }

    regressions: list[dict[str, Any]] = []
    existing_failures: list[dict[str, Any]] = []
    lint_failures: list[dict[str, Any]] = []
    selftest_failures: list[dict[str, Any]] = []
    all_failures: list[dict[str, Any]] = []

    for t in candidate_tests:
        tid = str(t["id"])
        layer = str(t["layer"])
        status = str(t["status"])
        base_status = baseline_map.get(tid, Status.PASS.value)

        if status != Status.PASS.value and status != Status.SKIPPED.value:
            entry = {
                "id": tid,
                "layer": layer,
                "baseline_status": base_status,
                "candidate_status": status,
                "message": (t.get("message") or "")[:500],
                "findings": list(t.get("findings") or []),
            }
            all_failures.append(entry)
            if layer == "lint":
                lint_failures.append(entry)
            if layer in ("selftest", "grader", "regrade"):
                selftest_failures.append(entry)
            if base_status == Status.PASS.value and status == Status.FAIL.value:
                regressions.append(entry)
            elif base_status == Status.FAIL.value and status == Status.FAIL.value:
                existing_failures.append(entry)

    layers_summary = records.layer_summary(candidate_tests)

    # Decision D2 blocking conditions:
    blocking_reasons: list[str] = []
    if lint_failures:
        blocking_reasons.append(f"lint failed ({len(lint_failures)} check(s))")
    if regressions:
        blocking_reasons.append(
            f"{len(regressions)} scenario(s) regressed PASS -> FAIL vs {baseline_source}"
        )
    if selftest_failures:
        blocking_reasons.append(
            f"suite self-test/grader failed ({len(selftest_failures)} check(s))"
        )
    if strict_zero_failures and all_failures and not blocking_reasons:
        blocking_reasons.append(
            f"{len(all_failures)} offline check(s) failed under --strict-zero-failures"
        )

    passed = len(blocking_reasons) == 0
    return {
        "passed": passed,
        "exit_code": EXIT_GATE_PASS if passed else EXIT_GATE_BLOCKED,
        "evaluated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "candidate_app_dir": config.repo_relative(candidate_dir),
        "baseline_source": baseline_source,
        "duration_s": duration_s,
        "layers": layers_summary,
        "total_tests": len(candidate_tests),
        "regressions": regressions,
        "existing_failures": existing_failures,
        "lint_failures": lint_failures,
        "selftest_failures": selftest_failures,
        "all_failures": all_failures,
        "blocking_reasons": blocking_reasons,
        "tests": candidate_tests,
    }


def format_gate_report(result: dict[str, Any]) -> str:
    """Format a concise, actionable console report for the pre-commit gate."""
    if result.get("exit_code") == EXIT_GATE_CRASH:
        return f"[gate] SUITE CRASH: {result.get('error')}\n[gate] RESULT: BLOCKED (exit 2)"

    lines: list[str] = [
        f"[gate] Candidate: {result['candidate_app_dir']} | Baseline: {result['baseline_source']} | Wall: {result['duration_s']:.2f}s",
        f"{'layer':<16} {'pass':>6} {'fail':>6} {'infra':>6} {'score':>8}",
        "-" * 46,
    ]
    for layer, s in result.get("layers", {}).items():
        score = "n/a" if s["score"] is None else f"{s['score'] * 100:.1f}%"
        lines.append(
            f"{layer:<16} {s['pass']:>6} {s['fail']:>6} {s['infra_error']:>6} {score:>8}"
        )

    existing_cnt = len(result.get("existing_failures") or [])
    if existing_cnt:
        lines.append(
            f"[gate] Pre-existing frozen-agent diagnostic findings (FAIL -> FAIL, non-regression per D2): {existing_cnt}"
        )

    if result["regressions"]:
        lines.append("")
        lines.append(
            f"[gate] REGRESSIONS (PASS -> FAIL vs {result['baseline_source']}): {len(result['regressions'])}"
        )
        for r in result["regressions"]:
            first_line = (r["message"] or "").splitlines()[0][:140] if r["message"] else ""
            lines.append(
                f"  - {r['id']} [{r['baseline_status']} -> {r['candidate_status']}]: {first_line}"
            )

    if result["lint_failures"]:
        lines.append("")
        lines.append(f"[gate] LINT FAILURES: {len(result['lint_failures'])}")
        for lf in result["lint_failures"]:
            first_line = (lf["message"] or "").splitlines()[0][:140] if lf["message"] else ""
            lines.append(f"  - {lf['id']}: {first_line}")

    if result["selftest_failures"]:
        lines.append("")
        lines.append(f"[gate] SELFTEST/GRADER FAILURES: {len(result['selftest_failures'])}")
        for sf in result["selftest_failures"]:
            first_line = (sf["message"] or "").splitlines()[0][:140] if sf["message"] else ""
            lines.append(f"  - {sf['id']}: {first_line}")

    if result["passed"]:
        lines.append("")
        lines.append(
            f"[gate] RESULT: PASSED ({result['total_tests']} checks evaluated, 0 PASS->FAIL regressions, 0 lint errors, 0 selftest errors)"
        )
    else:
        lines.append("")
        lines.append(
            f"[gate] RESULT: BLOCKED — {'; '.join(result['blocking_reasons'])}"
        )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="totto_suite gate",
        description="Run the offline pre-commit regression gate (Decision D2).",
    )
    parser.add_argument(
        "--app-dir",
        type=Path,
        default=None,
        help="Candidate cxas_app directory to check (default: <repo>/cxas_app).",
    )
    parser.add_argument(
        "--baseline-dir",
        type=Path,
        default=None,
        help="Optional baseline cxas_app directory to diff verdicts against.",
    )
    parser.add_argument(
        "--baseline-record",
        type=Path,
        default=None,
        help="Optional baseline run record JSON to diff verdicts against.",
    )
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=None,
        help="Optional repository root override.",
    )
    parser.add_argument(
        "--layers",
        type=str,
        default=None,
        help="Comma-separated subset of offline layers to run (default: all 8 offline layers).",
    )
    parser.add_argument(
        "--strict-zero-failures",
        action="store_true",
        help="Block even on pre-existing FAIL -> FAIL diagnostic findings.",
    )
    parser.add_argument(
        "--json-out",
        type=Path,
        default=None,
        help="Optional path to write structured JSON gate report.",
    )
    args = parser.parse_args(argv)

    layer_names = (
        tuple(x.strip() for x in args.layers.split(",") if x.strip())
        if args.layers
        else DEFAULT_GATE_LAYERS
    )

    result = evaluate_gate(
        app_dir=args.app_dir,
        repo_root=args.repo_root,
        baseline_dir=args.baseline_dir,
        baseline_record=args.baseline_record,
        layer_names=layer_names,
        strict_zero_failures=args.strict_zero_failures,
    )
    print(format_gate_report(result), flush=True)

    if args.json_out is not None:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        payload = {k: v for k, v in result.items() if k != "tests"}
        args.json_out.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )

    return int(result["exit_code"])


if __name__ == "__main__":
    raise SystemExit(main())
