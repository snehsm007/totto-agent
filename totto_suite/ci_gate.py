"""Staging CXAS eval gate (`python -m totto_suite ci-gate`).

Runs a subset of the live layers against ONE target app (normally the
permanent staging app), sequentially (parallel=1, one shared 120k tokens/min
quota) with the layers' own 429 backoff, then:

* records every per-repeat result with app-relative platform IDs + tool_mode
  + fake_verified (record mode ``ci`` under ``evals/history/runs/``, so
  ``verify-ids --app-name <same app> --run-id <same id>`` works next);
* aggregates repeats and applies the gate rule (``totto_suite.gate_rule``:
  measured absolute floors + no regression vs an optional baseline
  ``gate_summary.json`` from the last green ``main`` run);
* writes ``gate_summary.json`` and prints a table with app-relative
  ``evaluationRuns/<uuid>`` / ``conversations/<uuid>`` IDs;
* exits 0 PASS, 1 FAIL, 3 INCONCLUSIVE (too many infra errors), 2 bad
  config / crash.

Nothing here pushes to CXAS; deploying the candidate to staging is a
separate CI step. Records, artifacts and the summary never contain project
or app identifiers (``totto_suite.ids``).
"""

from __future__ import annotations

import argparse
import contextlib
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys
import time
from typing import Any

from totto_suite import config, fakes, gate_rule, gitinfo, ids, records
from totto_suite import layers as layers_pkg

SCHEMA = "totto-gate-summary/v1"
THRESHOLDS_PATH = Path(__file__).resolve().parent / "gate_thresholds.json"
DEFAULT_LAYERS = ("tools", "goldens", "sims")
KNOWN_LAYERS = ("tools", "goldens", "sims", "turns", "safety", "escalation", "voice")
EXIT_CRASH = 2
STAGING_SUFFIX = "-staging"


# --------------------------------------------------------------------------
# inputs
# --------------------------------------------------------------------------


def load_thresholds(tool_mode: str, path: Path = THRESHOLDS_PATH) -> dict[str, Any]:
    """Thresholds for ``tool_mode`` from gate_thresholds.json (defaults if absent)."""
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = {}
    section = dict(data.get(tool_mode) or {})
    section.pop("measured_from", None)
    section.pop("justification", None)
    return {**gate_rule.DEFAULT_THRESHOLDS, **section}


def load_baseline(path: str | None) -> tuple[dict[str, Any] | None, str | None]:
    """(baseline summary, warning). A missing/unreadable file is not fatal."""
    if not path:
        return None, None
    p = Path(path)
    if not p.is_file():
        return None, f"baseline {path} not found; applying absolute floors only"
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return None, f"baseline {path} unreadable ({exc}); applying absolute floors only"
    if not isinstance(data, dict) or data.get("schema") != SCHEMA:
        return None, f"baseline {path} is not a {SCHEMA} file; applying absolute floors only"
    return data, None


def default_run_url(environ: dict[str, str] | None = None) -> str | None:
    env = os.environ if environ is None else environ
    server = env.get("GITHUB_SERVER_URL", "").strip()
    repo = env.get("GITHUB_REPOSITORY", "").strip()
    run_id = env.get("GITHUB_RUN_ID", "").strip()
    if server and repo and run_id:
        return f"{server}/{repo}/actions/runs/{run_id}"
    return None


def select_layers(spec: str | None) -> list[str]:
    names = [x.strip().removeprefix("live_") for x in (spec or "").split(",") if x.strip()]
    names = names or list(DEFAULT_LAYERS)
    unknown = [n for n in names if n not in KNOWN_LAYERS]
    if unknown:
        raise ValueError(f"unknown layer(s) {unknown}; known: {', '.join(KNOWN_LAYERS)}")
    return names


# --------------------------------------------------------------------------
# post-processing of layer results
# --------------------------------------------------------------------------


def _merge_evidence(*items: dict[str, Any] | None) -> dict[str, Any] | None:
    present = [e for e in items if e]
    if not present:
        return None
    out: dict[str, Any] = {"fake_tool_spans": 0, "real_tool_spans": 0, "fake_markers": 0}
    fake_tools: set[str] = set()
    real_tools: set[str] = set()
    for e in present:
        for key in ("fake_tool_spans", "real_tool_spans", "fake_markers"):
            out[key] += int(e.get(key) or 0)
        fake_tools.update(e.get("fake_tools") or [])
        real_tools.update(e.get("real_tools") or [])
    out["fake_tools"] = sorted(fake_tools)
    out["real_tools"] = sorted(real_tools)
    return out


def conversation_evidence(
    ch_client: Any,
    conversation: str,
    tool_names: set[str],
    *,
    attempts: int = 3,
    wait_s: float = 3.0,
) -> tuple[dict[str, Any] | None, str | None]:
    """Fetches a conversation and counts fake/real tool spans in it."""
    last_err = None
    for attempt in range(attempts):
        try:
            conv = ch_client.get_conversation(conversation)
            data = type(conv).to_dict(conv) if hasattr(type(conv), "to_dict") else conv
            if isinstance(data, dict) and not data.get("turns") and attempt < attempts - 1:
                time.sleep(wait_s)  # conversation logging can lag the session
                continue
            return fakes.span_evidence(data, tool_names), None
        except Exception as exc:  # noqa: BLE001
            last_err = f"{type(exc).__name__}: {str(exc)[:200]}"
            time.sleep(wait_s)
    return None, last_err


def finalize_test(
    test: dict[str, Any],
    run_tool_mode: str,
    app_name: str,
    conv_evidence: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """tool_mode + fake_verified + app-relative IDs + redacted text for one result."""
    out = dict(test)
    out["tool_mode"] = str(out.get("tool_mode") or run_tool_mode)
    evidence = _merge_evidence(out.get("fake_evidence"), conv_evidence)
    if evidence is not None:
        out["fake_evidence"] = evidence
    if out.get("fake_verified") is None or out["tool_mode"] == "fake":
        out["fake_verified"] = fakes.fake_verified(out["tool_mode"], evidence)
    out["platform_ids"] = ids.relativize_platform_ids(out.get("platform_ids"))
    out["app_ref_ids"] = True
    for key in ("message", "evidence", "raw_artifact_path"):
        if isinstance(out.get(key), str):
            out[key] = ids.redact_text(out[key], app_name)
    for key in ("findings", "deterministic", "judge", "metrics"):
        if key in out:
            out[key] = ids.redact_obj(out[key], app_name)
    return out


def redact_artifacts(art_dir: Path, app_name: str) -> int:
    """Rewrites every artifact file with identifiers stripped; returns count."""
    n = 0
    for path in sorted(Path(art_dir).rglob("*")):
        if not path.is_file() or path.suffix not in (".json", ".txt", ".md", ".log"):
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        red = ids.redact_text(text, app_name)
        if red != text:
            path.write_text(red, encoding="utf-8")
            n += 1
    return n


class RedactingStream:
    """Text stream wrapper that masks project/app IDs in everything written.

    Library code called by the layers (e.g. cxas_scrapi's
    ``Updating existing evaluation: <full resource name>``) prints straight to
    stdout, which ends up in the CI log. Only the project ID/number and app IDs
    are masked (:func:`ids.mask_text`); evaluation-run / session /
    conversation / result UUIDs stay visible so the log can be matched against
    ``verify-ids`` evidence. ``print`` writes the whole formatted string in one
    ``write`` call, so per-write masking catches it.
    """

    def __init__(self, stream: Any, app_name: str | None) -> None:
        self._stream = stream
        self._app_name = app_name
        self._idents = ids.configured_identifiers()

    def write(self, text: str) -> int:
        self._stream.write(ids.mask_text(text, self._app_name, self._idents))
        return len(text)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._stream, name)


# --------------------------------------------------------------------------
# output
# --------------------------------------------------------------------------


def summary_tests(agg: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    for t in agg:
        reps = []
        for r in t["repeats"]:
            reps.append(
                {
                    "repeat": int(r.get("repeat") or 1),
                    "status": r.get("status"),
                    "platform_ids": r.get("platform_ids") or {},
                    "tool_mode": r.get("tool_mode"),
                    "fake_verified": r.get("fake_verified"),
                    "duration_s": r.get("duration_s"),
                    "message": str(r.get("message") or "")[:300],
                }
            )
        first_ids = next((r["platform_ids"] for r in reps if r["platform_ids"]), {})
        out.append(
            {
                "id": t["id"],
                "layer": t["layer"],
                "status": t["status"],
                "repeat_statuses": t["repeat_statuses"],
                "tool_mode": t["tool_mode"],
                "fake_verified": t["fake_verified"],
                "platform_ids": first_ids,
                "repeats": reps,
            }
        )
    return out


def _short_ids(pids: dict[str, str]) -> str:
    for key in ("evaluation_run", "conversation", "tool"):
        if pids.get(key):
            return pids[key]
    return "-"


def print_table(summary: dict[str, Any]) -> None:
    rows = summary["tests"]
    width = max([len(r["id"]) for r in rows] + [4])
    fv = {True: "yes", False: "no", None: "n/a"}
    print(f"\n{'TEST'.ljust(width)}  {'STATUS':<12} {'REPEATS':<22} {'TOOLS':<5} FAKE✓  PLATFORM IDS (app-relative)")
    for r in rows:
        ids_txt = " | ".join(
            f"r{rep['repeat']}:{_short_ids(rep['platform_ids'])}" for rep in r["repeats"]
        )
        print(
            f"{r['id'].ljust(width)}  {r['status']:<12} {','.join(r['repeat_statuses'])[:22]:<22} "
            f"{r['tool_mode']:<5} {fv.get(r['fake_verified'], '?'):<6} {ids_txt}"
        )
    print("\nLayers:")
    for layer, c in summary["layers"].items():
        pr = "n/a" if c["pass_rate"] is None else f"{c['pass_rate']:.1%}"
        print(
            f"  {layer:<16} pass={c['pass']} fail={c['fail']} infra={c['infra_error']} "
            f"skipped={c['skipped']} pass_rate={pr}"
        )
    runs = sorted(
        {
            rep["platform_ids"].get("evaluation_run")
            for r in rows
            for rep in r["repeats"]
            if rep["platform_ids"].get("evaluation_run")
        }
    )
    print(f"\nevaluationRuns: {', '.join(runs) or '-'}")
    pr = summary["pass_rate"]
    bpr = summary["baseline_pass_rate"]
    print(
        f"target={summary['target']} tool_mode={summary['tool_mode']} "
        f"fake_verified={summary['fake_verified']} pass_rate="
        f"{'n/a' if pr is None else f'{pr:.1%}'} baseline="
        f"{'n/a' if bpr is None else f'{bpr:.1%}'} duration={summary['duration_s']}s"
    )
    print(f"VERDICT: {summary['verdict']}")
    for reason in summary["reasons"]:
        print(f"  - {reason}")


# --------------------------------------------------------------------------
# main
# --------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="totto_suite ci-gate",
        description="Run the CXAS eval gate on the staging app and apply the gate rule.",
    )
    p.add_argument("--target", choices=ids.APP_REFS, default="staging",
                   help="which app this is (recorded as app_ref; default staging)")
    p.add_argument("--app-name", default=None,
                   help="projects/<p>/locations/<l>/apps/<id> (default: env/gecx-config.json)")
    p.add_argument("--run-id", default=None, help="run id (default ci-local-<UTC stamp>)")
    p.add_argument("--tool-mode", choices=("fake", "real"), default="fake",
                   help="fake = platform tool fakes (toolCallBehaviour FAKE / use_tool_fakes)")
    p.add_argument("--baseline", default=None,
                   help="gate_summary.json of the last green main run (optional)")
    p.add_argument("--repeats", type=int, default=2, help="repeats for LLM layers (default 2)")
    p.add_argument("--layers", default=None,
                   help=f"comma list (default {','.join(DEFAULT_LAYERS)}; known {','.join(KNOWN_LAYERS)})")
    p.add_argument("--out", default="gate_summary.json", help="summary path (default gate_summary.json)")
    p.add_argument("--commit", default=None, help="commit SHA (default $GITHUB_SHA or git HEAD)")
    p.add_argument("--run-url", default=None, help="CI run URL (default from GITHUB_* env)")
    p.add_argument("--now", default=None, help="ISO-8601 UTC override for date oracles")
    p.add_argument("--thresholds", default=str(THRESHOLDS_PATH), help=argparse.SUPPRESS)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    started = datetime.now(timezone.utc)
    t0 = time.monotonic()

    try:
        app_name = ids.resolve_app_name(args.app_name, args.target)
        layer_names = select_layers(args.layers)
    except ValueError as exc:
        print(f"ci-gate: error: {exc}", file=sys.stderr)
        return EXIT_CRASH

    # Everything below may print library output (SCRAPI) that contains full
    # resource names; the CI log must stay identifier-free.
    with (
        contextlib.redirect_stdout(RedactingStream(sys.stdout, app_name)),
        contextlib.redirect_stderr(RedactingStream(sys.stderr, app_name)),
    ):
        return _gate(args, app_name, layer_names, started, t0)


def _gate(
    args: argparse.Namespace,
    app_name: str,
    layer_names: list[str],
    started: datetime,
    t0: float,
) -> int:
    from totto_suite.live.runner import fetch_live_cxas_metadata  # heavy import (SCRAPI)

    meta = fetch_live_cxas_metadata(app_name, app_ref=args.target)
    if meta.get("metadata_error"):
        print(
            "ci-gate: error: cannot read the target app: "
            + ids.redact_text(meta["metadata_error"], app_name),
            file=sys.stderr,
        )
        return EXIT_CRASH
    display = str(meta.get("app_display_name") or "")
    if args.target == "staging" and not display.endswith(STAGING_SUFFIX):
        print(
            f"ci-gate: error: --target staging but the app's displayName {display!r} does not end "
            f"with {STAGING_SUFFIX!r}; refusing to run the gate against a non-staging app",
            file=sys.stderr,
        )
        return EXIT_CRASH

    commit = args.commit or os.environ.get("GITHUB_SHA", "").strip() or gitinfo.head_commit()
    run_id = args.run_id or f"ci-local-{started.strftime('%Y%m%dT%H%M%SZ')}"
    if records.record_path(run_id).exists():
        print(f"ci-gate: error: record for run id {run_id} already exists", file=sys.stderr)
        return EXIT_CRASH
    run_url = args.run_url or default_run_url()
    thresholds = load_thresholds(args.tool_mode, Path(args.thresholds))
    baseline, warn = load_baseline(args.baseline)
    if warn:
        print(f"ci-gate: warning: {warn}", flush=True)

    artifacts_dir = config.ARTIFACTS_DIR / run_id
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    from totto_suite import oracle

    now_dt = oracle.parse_utc(args.now) if args.now else started
    ctx = {
        "repo_root": str(config.REPO_ROOT),
        "app_dir": str(config.DEFAULT_APP_DIR),
        "mode": "live",
        "repeats": max(1, args.repeats),
        "now": now_dt.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "now_dt": now_dt,
        "run_id": run_id,
        "artifacts_dir": str(artifacts_dir),
        "app_name": app_name,
        "tool_mode": args.tool_mode,
    }
    mods = {m.name: m for m in layers_pkg.discover("live")}
    print(
        f"[ci-gate] run {run_id}: target={args.target} tool_mode={args.tool_mode} "
        f"repeats={ctx['repeats']} layers={','.join(layer_names)} model={meta.get('model')}",
        flush=True,
    )

    raw_tests: list[dict[str, Any]] = []
    layer_durations: dict[str, float] = {}
    for name in layer_names:
        mod = mods.get(name)
        if mod is None:
            print(f"ci-gate: error: live layer module for {name!r} not found", file=sys.stderr)
            return EXIT_CRASH
        print(f"[ci-gate] running live_{name} ...", flush=True)
        outcome = layers_pkg.run_layer(mod, ctx)
        layer_durations[f"live_{name}"] = round(outcome.duration_s, 2)
        if outcome.crashed:
            err = ids.redact_text(str(outcome.error or ""), app_name)
            print(f"[ci-gate] live_{name} CRASHED:\n{err}", file=sys.stderr, flush=True)
            from totto_suite.live.runner import is_quota_or_infra_error

            raw_tests.append(
                {
                    "id": f"live_{name}::__layer_crash__",
                    "layer": f"live_{name}",
                    "repeat": 1,
                    "status": "INFRA_ERROR" if is_quota_or_infra_error(err) else "FAIL",
                    "message": f"layer crashed: {err.strip().splitlines()[-1] if err.strip() else 'unknown'}",
                    "platform_ids": {},
                    "tool_mode": args.tool_mode,
                }
            )
            continue
        print(
            f"[ci-gate] live_{name}: {len(outcome.results)} results in {outcome.duration_s:.1f}s",
            flush=True,
        )
        raw_tests.extend(outcome.results)

    # Platform evidence of fake vs real tool calls (conversation spans).
    tool_names: set[str] = set()
    ch_client = None
    try:
        from cxas_scrapi.core.conversation_history import ConversationHistory
        from cxas_scrapi.core.tools import Tools

        tool_names = {str(t.display_name) for t in Tools(app_name=app_name).list_tools()}
        try:
            ch_client = ConversationHistory(app_name=app_name, transport="rest")
        except TypeError:
            ch_client = ConversationHistory(app_name=app_name)
    except Exception as exc:  # noqa: BLE001
        print(f"ci-gate: warning: cannot load tools/conversations: {ids.redact_text(str(exc), app_name)}")
    tests: list[dict[str, Any]] = []
    for t in raw_tests:
        conv = (t.get("platform_ids") or {}).get("conversation")
        evidence = None
        if conv and ch_client is not None and t.get("status") != "SKIPPED":
            evidence, err = conversation_evidence(ch_client, str(conv), tool_names)
            if err:
                t.setdefault("metrics", {})["conversation_fetch_error"] = err
        tests.append(finalize_test(t, args.tool_mode, app_name, evidence))
    tests.sort(key=lambda t: (layer_names.index(str(t["layer"]).removeprefix("live_"))
                              if str(t["layer"]).removeprefix("live_") in layer_names else 99,
                              t["id"], int(t.get("repeat") or 1)))

    agg = gate_rule.aggregate_repeats(tests)
    result = gate_rule.evaluate(agg, thresholds, baseline, args.tool_mode)
    version_hint = next(
        (t["platform_ids"].get("app_version") for t in tests if t["platform_ids"].get("app_version")),
        None,
    )
    if version_hint:
        meta = fetch_live_cxas_metadata(
            app_name, app_ref=args.target, version_hint=ids.to_full(app_name, version_hint)
        )
    finished = datetime.now(timezone.utc)
    duration_s = round(time.monotonic() - t0, 2)
    run_fake_verified = fakes.run_fake_verified(tests, args.tool_mode)

    summary = {
        "schema": SCHEMA,
        "commit": commit,
        "run_id": run_id,
        "run_url": run_url,
        "target": args.target,
        "tool_mode": args.tool_mode,
        "fake_verified": run_fake_verified,
        "pass_rate": result["pass_rate"],
        "baseline_pass_rate": result["baseline_pass_rate"],
        "verdict": result["verdict"],
        "reasons": result["reasons"],
        "thresholds": result["thresholds"],
        "counts": result["counts"],
        "infra_ratio": result["infra_ratio"],
        "new_failures_vs_baseline": result["new_failures_vs_baseline"],
        "layers": result["layers"],
        "layer_durations_s": layer_durations,
        "repeats": ctx["repeats"],
        "model": meta.get("model"),
        "app_version": meta.get("version_id") or None,
        "started_at": gitinfo.iso_utc(started),
        "finished_at": gitinfo.iso_utc(finished),
        "duration_s": duration_s,
        "tests": summary_tests(agg),
    }
    summary = ids.redact_obj(summary, app_name)

    # Record (per-repeat results) so verify-ids can check every platform ID.
    rel_app = config.repo_relative(config.DEFAULT_APP_DIR)
    dirty = gitinfo.dirty_state(agent_path=rel_app, include_suite=True)
    from totto_suite import cxasapi

    cxas_block = {k: meta.get(k) for k in records.CXAS_KEYS}
    record = records.build_record(
        mode="ci",
        run_id=run_id,
        started_at=gitinfo.iso_utc(started),
        finished_at=gitinfo.iso_utc(finished),
        point_time=gitinfo.iso_utc(started),
        agent={
            "commit": commit,
            "path": rel_app,
            "tree_hash": cxasapi.app_tree_hash(config.DEFAULT_APP_DIR),
            "dirty": dirty["dirty"],
            "dirty_paths_relevant": dirty["dirty_paths_relevant"],
            "dirty_paths_unrelated": dirty["dirty_paths_unrelated"],
        },
        suite={
            "commit": commit,
            "dirty": dirty["suite_dirty"],
            "dirty_paths": dirty["suite_dirty_paths"],
        },
        cxas=ids.redact_obj(cxas_block, app_name),
        rationale=f"ci-gate {args.tool_mode} on {args.target} for {commit[:12]}",
        tests=[{k: v for k, v in t.items() if k != "deterministic"} for t in tests],
        extra={
            "app_ref": args.target,
            "tool_mode": args.tool_mode,
            "fake_verified": run_fake_verified,
            "repeats": ctx["repeats"],
            "duration_s": duration_s,
            "run_url": run_url,
            "gate": {k: summary[k] for k in ("verdict", "pass_rate", "baseline_pass_rate", "reasons")},
        },
    )
    rec_path = records.write_record(record)
    redacted = redact_artifacts(artifacts_dir, app_name)

    out_path = Path(args.out)
    if out_path.parent and not out_path.parent.exists():
        out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    print_table(summary)
    print(f"\nrecord: {config.repo_relative(rec_path)} (artifacts redacted: {redacted} files)")
    print(f"summary: {out_path}")
    print(
        f"verify: python -m totto_suite verify-ids --app-name <same app> --run-id {run_id}",
        flush=True,
    )
    return gate_rule.EXIT_CODES[summary["verdict"]]
