"""Historical run backfill (`totto_suite backfill`).

Populates `evals/history/runs/` with 6 historical points (plan.md §5.2):
1. Three reproduced historical commits (`mode="reproduced"`, `imported=False`):
   - `bdb8f3b` (2026-09-28T17:14:30Z) — Initial baseline commit + Iteration 1 static checks (26/42)
   - `1a17988` (2026-09-28T17:21:42Z) — Iteration 2 PIF XML + OpenF1 + Merc standings (42/42)
   - `a7c3094` (2026-09-28T18:10:07Z) — Iteration 3 prompt-trimming snapshot regression (34/42)
2. Three imported historical live evaluation points (`mode="imported"`, `imported=True`):
   - `20260928T184131Z_imported_a7c3094` — Gemini 2.5 Flash live baseline (v1 `8f80d3eb...`)
   - `20260928T191853Z_imported_a7c3094` — Gemini 3 Flash model switch (v1 `8f80d3eb...`)
   - `20260928T205030Z_imported_f073e02` — Gemini 3 Flash Round 2 pinned instructions (hidden version `534c9b06...`)

All imported live transcripts are re-graded deterministically via `totto_suite.grader`
while preserving every platform `session_id`, `evaluation_run`, and `conversation` ID
and separating HTTP 429 quota errors into `INFRA_ERROR[quota]`.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import tempfile
from typing import Any

from totto_suite import config, cxasapi, gitinfo, grader, records, trend
from totto_suite import layers as layers_pkg
from totto_suite.grader import adapters as grader_adapters
from totto_suite.grader import regrade as grader_regrade
from totto_suite.taxonomy import Status


AGENT_OFFLINE_LAYERS = ("lint", "config", "callbacks", "tools", "dates")


def _run_offline_on_tree(app_dir: Path, repo_root: Path) -> list[dict[str, Any]]:
    """Run the 5 agent-dependent offline layers against an extracted historical `cxas_app`."""
    discovered = {m.name: m for m in layers_pkg.discover("offline")}
    out: list[dict[str, Any]] = []
    prev = os.environ.get("TOTTO_APP_DIR")
    os.environ["TOTTO_APP_DIR"] = str(app_dir)
    try:
        with tempfile.TemporaryDirectory(prefix="totto_backfill_art_") as art_dir:
            ctx = {
                "repo_root": str(repo_root),
                "app_dir": str(app_dir),
                "mode": "reproduced",
                "run_id": "backfill_reproduced",
                "artifacts_dir": art_dir,
                "repeats": 1,
                "now": None,
                "app_name": config.app_name(),
            }
            for name in AGENT_OFFLINE_LAYERS:
                mod = discovered.get(name)
                if mod is None:
                    continue
                outcome = layers_pkg.run_layer(mod, ctx)
                if not outcome.crashed:
                    out.extend(outcome.results)
    finally:
        if prev is None:
            os.environ.pop("TOTTO_APP_DIR", None)
        else:
            os.environ["TOTTO_APP_DIR"] = prev
    return out


def _legacy_static_tests_from_state(
    repo_root: Path, iteration_num: int
) -> list[dict[str, Any]]:
    """Convert `evals/results/state.json` iteration check results into schema-v1 TestResults."""
    state_path = repo_root / "evals" / "results" / "state.json"
    if not state_path.is_file():
        return []
    data = json.loads(state_path.read_text(encoding="utf-8"))
    iterations = data.get("iterations") or []
    target = next(
        (it for it in iterations if int(it.get("iteration", -1)) == iteration_num),
        None,
    )
    if not target:
        return []

    tests: list[dict[str, Any]] = []
    for chk in target.get("checks") or []:
        cid = str(chk.get("id") or "check")
        passed = bool(chk.get("passed"))
        detail = str(chk.get("detail") or "")
        tests.append(
            {
                "id": f"legacy_static::{cid}",
                "layer": "legacy_static",
                "status": Status.PASS.value if passed else Status.FAIL.value,
                "repeat": 1,
                "duration_s": 0.0,
                "message": "" if passed else detail,
                "findings": [
                    str(chk.get("category") or "STATIC")
                ],
                "platform_ids": {},
                "evidence": detail or None,
                "deterministic": {"passed": passed, "category": chk.get("category")},
                "judge": None,
            }
        )
    return tests


def _build_reproduced_records(repo_root: Path) -> list[dict[str, Any]]:
    """Build the 3 reproduced historical commit records."""
    suite_head = gitinfo.head_commit(repo=repo_root)
    suite_dirty = gitinfo.dirty_state(include_suite=True, repo=repo_root)
    specs = [
        {
            "short": "bdb8f3b",
            "run_id": "20260928T171430Z_reproduced_bdb8f3b",
            "point_time": "2026-09-28T17:14:30Z",
            "iteration": 1,
            "overlay_snapshot": None,
            "rationale": (
                "Initial commit bdb8f3b: baseline multi-agent Totto scaffolding before "
                "PIF XML rewrite and OpenF1/Mercedes standings tools (reproduced offline + iteration 1 static checks 26/42)"
            ),
        },
        {
            "short": "1a17988",
            "run_id": "20260928T172142Z_reproduced_1a17988",
            "point_time": "2026-09-28T17:21:42Z",
            "iteration": 2,
            "overlay_snapshot": None,
            "rationale": (
                "Iteration 2 commit 1a17988: PIF XML instructions, OpenF1 2026 schedule, "
                "Mercedes standings, and 42/42 static eval pass (reproduced offline)"
            ),
        },
        {
            "short": "a7c3094",
            "run_id": "20260928T181007Z_reproduced_a7c3094",
            "point_time": "2026-09-28T18:10:07Z",
            "iteration": 3,
            "overlay_snapshot": "evals/results/snapshots/iteration_3/cxas_app",
            "rationale": (
                "Iteration 3 snapshot on commit a7c3094: shortened totto_root_agent and "
                "merch_support_agent instructions causing config/static regression (42/42 -> 34/42)"
            ),
        },
    ]

    out_records: list[dict[str, Any]] = []
    for sp in specs:
        full_sha = gitinfo.resolve(sp["short"], repo=repo_root)
        with tempfile.TemporaryDirectory(prefix=f"totto_repro_{sp['short']}_") as td:
            extracted_app = gitinfo.archive_subdir(
                full_sha, "cxas_app", Path(td), repo=repo_root
            )
            agent_rel_path = "cxas_app"
            if sp["overlay_snapshot"]:
                snap_src = repo_root / sp["overlay_snapshot"]
                if snap_src.is_dir():
                    for src_file in snap_src.rglob("*"):
                        if src_file.is_file():
                            rel = src_file.relative_to(snap_src)
                            dst_file = extracted_app / rel
                            dst_file.parent.mkdir(parents=True, exist_ok=True)
                            shutil.copyfile(src_file, dst_file)
                    agent_rel_path = sp["overlay_snapshot"]

            offline_tests = _run_offline_on_tree(extracted_app, repo_root)
            static_tests = _legacy_static_tests_from_state(repo_root, sp["iteration"])
            all_tests = sorted(
                offline_tests + static_tests,
                key=lambda t: (str(t["id"]), int(t.get("repeat", 1))),
            )
            tree_hash = cxasapi.app_tree_hash(extracted_app)
            app_json_path = extracted_app / "app.json"
            model = "gemini-2.5-flash"
            if app_json_path.is_file():
                try:
                    raw_app = json.loads(app_json_path.read_text(encoding="utf-8"))
                    model = (
                        (raw_app.get("modelSettings") or {}).get("model")
                        or "gemini-2.5-flash"
                    )
                except Exception:
                    model = "gemini-2.5-flash"

        now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        rec = records.build_record(
            mode="reproduced",
            run_id=sp["run_id"],
            started_at=now_iso,
            finished_at=now_iso,
            point_time=sp["point_time"],
            agent={
                "commit": full_sha,
                "path": agent_rel_path,
                "tree_hash": tree_hash,
                "dirty": False,
                "dirty_paths_relevant": [],
                "dirty_paths_unrelated": [],
            },
            suite={
                "commit": suite_head,
                "dirty": suite_dirty["suite_dirty"],
                "dirty_paths": suite_dirty["suite_dirty_paths"],
            },
            cxas={
                "app": config.app_name(),
                "version_id": None,
                "version_status": "not_deployed",
                "model": model,
                "app_update_time": None,
                "app_etag": None,
            },
            rationale=sp["rationale"],
            tests=all_tests,
            imported=False,
            import_source=(
                f"git archive {sp['short']}:cxas_app + evals/results/state.json#iteration_{sp['iteration']}"
            ),
        )
        out_records.append(rec)
    return out_records


def _grade_sim_or_probe_file(
    filename: str,
    *,
    point_time: str,
    kind: str,
    layer_override: str | None = None,
    id_prefix: str | None = None,
) -> list[dict[str, Any]]:
    """Load a recorded sims or probes JSON file and grade every row with `totto_suite.grader`."""
    path = grader_regrade.resolve_recorded_file(filename)
    data = json.loads(path.read_text(encoding="utf-8"))
    rows = data.get("results", data) if isinstance(data, dict) else data
    convs = grader.load_conversations(data, kind=kind, source=filename)

    out: list[dict[str, Any]] = []
    for idx, (row, conv) in enumerate(zip(rows, convs), start=1):
        modality = conv.get("modality") or "text"
        layer = layer_override or (
            "live_voice"
            if modality == "audio"
            else ("live_probes" if kind == "probes" else "live_sims")
        )
        det = grader.grade(
            conv,
            {
                "now": point_time,
                "expected_language": "auto",
                "voice": modality == "audio",
            },
        )
        judge = grader.judge_from_row(row)
        err_str = str(row.get("error") or "").strip()
        status = grader.combine(det, judge, row_error=err_str or None)

        base_name = str(row.get("name") or f"item_{idx}")
        if id_prefix:
            base_name = f"{id_prefix}_{base_name}"
        repeat_num = int(row.get("run") or 1)

        fail_checks = [c for c in det["checks"] if c["status"] == "fail"]
        findings: list[str] = []
        for fc in fail_checks:
            for f in fc.get("findings") or []:
                if f not in findings:
                    findings.append(f)

        if status == Status.INFRA_ERROR.value:
            msg = f"INFRA_ERROR[quota]: {err_str[:240]}" if "429" in err_str or "RESOURCE_EXHAUSTED" in err_str else f"INFRA_ERROR[error]: {err_str[:240]}"
        elif fail_checks:
            msg = "; ".join(f"{c['name']}: {c.get('evidence', '')}" for c in fail_checks[:4])
        elif status == Status.FAIL.value:
            msg = "Judge marked conversation failed"
        else:
            msg = ""

        out.append(
            {
                "id": f"{layer}::{base_name}",
                "layer": layer,
                "status": status,
                "repeat": repeat_num,
                "duration_s": float(row.get("duration_s") or 0.0),
                "message": msg[:500],
                "findings": findings,
                "platform_ids": {
                    "session_id": conv.get("session_id"),
                    "source_file": filename,
                },
                "evidence": msg[:500] or None,
                "deterministic": {
                    "passed": det["passed"],
                    "fail_checks": [c["name"] for c in fail_checks],
                    "warn_checks": [
                        c["name"] for c in det["checks"] if c["status"] == "warn"
                    ],
                },
                "judge": judge,
            }
        )
    return out


def _grade_goldens_file(filename: str) -> list[dict[str, Any]]:
    """Parse a recorded CXAS golden evaluation results JSON file into schema-v1 TestResults."""
    path = grader_regrade.resolve_recorded_file(filename)
    items = json.loads(path.read_text(encoding="utf-8"))
    out: list[dict[str, Any]] = []
    for idx, item in enumerate(items, start=1):
        res_name = str(item.get("name") or "")
        short_res_id = res_name.rsplit("/", 1)[-1] if "/" in res_name else f"golden_{idx}"
        eval_run = str(item.get("evaluation_run") or "")
        replays = (item.get("golden_result") or {}).get("turn_replay_results") or []
        conv_ids = [str(r.get("conversation") or "") for r in replays if r.get("conversation")]
        sim_outcomes = [
            int((r.get("semantic_similarity_result") or {}).get("outcome", 0))
            for r in replays
        ]
        passed = bool(sim_outcomes) and all(o == 1 for o in sim_outcomes)
        explanations = [
            str((r.get("semantic_similarity_result") or {}).get("explanation") or "").splitlines()[0]
            for r in replays
            if (r.get("semantic_similarity_result") or {}).get("explanation")
        ]
        msg = "" if passed else ("; ".join(explanations)[:400] or "Golden turn replay outcome != 1")
        out.append(
            {
                "id": f"live_goldens::golden_{idx:02d}_{short_res_id[:8]}",
                "layer": "live_goldens",
                "status": Status.PASS.value if passed else Status.FAIL.value,
                "repeat": 1,
                "duration_s": 0.0,
                "message": msg,
                "findings": [],
                "platform_ids": {
                    "evaluation_result": res_name,
                    "evaluation_run": eval_run,
                    "conversations": conv_ids,
                    "source_file": filename,
                },
                "evidence": (explanations[0][:400] if explanations else None),
                "deterministic": {"passed": passed, "turn_count": len(replays)},
                "judge": {"passed": passed},
            }
        )
    return out


def _grade_tools_file(filename: str) -> list[dict[str, Any]]:
    """Parse a recorded `tools_text_*.json` or `tool_probes_*.json` file into schema-v1 TestResults."""
    path = grader_regrade.resolve_recorded_file(filename)
    data = json.loads(path.read_text(encoding="utf-8"))
    out: list[dict[str, Any]] = []

    if isinstance(data, list):
        for idx, item in enumerate(data, start=1):
            tname = str(item.get("test_name") or f"tool_test_{idx}")
            raw_status = str(item.get("status") or "").upper()
            passed = raw_status in ("PASSED", "PASS")
            err = str(item.get("errors") or "")
            dur = round(float(item.get("latency (ms)") or 0.0) / 1000.0, 4)
            out.append(
                {
                    "id": f"live_tools::{tname}",
                    "layer": "live_tools",
                    "status": Status.PASS.value if passed else Status.FAIL.value,
                    "repeat": 1,
                    "duration_s": dur,
                    "message": "" if passed else err[:300],
                    "findings": [],
                    "platform_ids": {
                        "tool": item.get("tool"),
                        "source_file": filename,
                    },
                    "evidence": err[:300] or None,
                    "deterministic": {"passed": passed},
                    "judge": None,
                }
            )
    elif isinstance(data, dict) and isinstance(data.get("cases"), list):
        for idx, case in enumerate(data["cases"], start=1):
            cname = str(case.get("case") or f"probe_{idx}")
            err = case.get("error")
            resp = ((case.get("response") or {}).get("response") or {}).get("result") or {}
            tool_res_id = (case.get("response") or {}).get("tool")
            passed = err is None and isinstance(resp, dict) and resp.get("status") in ("success", "error")
            dur = round(float(case.get("latency_ms") or 0.0) / 1000.0, 4)
            out.append(
                {
                    "id": f"live_tools::probe_{cname}",
                    "layer": "live_tools",
                    "status": Status.PASS.value if passed else Status.FAIL.value,
                    "repeat": 1,
                    "duration_s": dur,
                    "message": "" if passed else str(err or "invalid tool response")[:300],
                    "findings": [],
                    "platform_ids": {
                        "tool_resource": tool_res_id,
                        "tool": case.get("tool"),
                        "source_file": filename,
                    },
                    "evidence": None,
                    "deterministic": {"passed": passed, "result_status": resp.get("status")},
                    "judge": None,
                }
            )
    return out


def _build_imported_records(repo_root: Path) -> list[dict[str, Any]]:
    """Build the 3 imported historical live-run records graded with `totto_suite.grader`."""
    suite_head = gitinfo.head_commit(repo=repo_root)
    suite_dirty = gitinfo.dirty_state(include_suite=True, repo=repo_root)
    now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    def _commit_tree_hash(short_rev: str) -> tuple[str, str]:
        full = gitinfo.resolve(short_rev, repo=repo_root)
        with tempfile.TemporaryDirectory(prefix="totto_imp_tree_") as td:
            app_p = gitinfo.archive_subdir(full, "cxas_app", Path(td), repo=repo_root)
            return full, cxasapi.app_tree_hash(app_p)

    sha_a7c, tree_a7c = _commit_tree_hash("a7c3094")
    sha_f07, tree_f07 = _commit_tree_hash("f073e02")

    # 1. 2026-09-28T18:41:31Z — Gemini 2.5 Flash baseline live runs (v1 8f80d3eb...)
    p1_time = "2026-09-28T18:41:31Z"
    p1_tests = (
        _grade_tools_file("tools_text_20260928_182511.json")
        + _grade_goldens_file("goldens_text_20260928_182733.json")
        + _grade_sim_or_probe_file(
            "probes_text_20260928_183505.json", point_time=p1_time, kind="probes"
        )
        + _grade_sim_or_probe_file(
            "sims_repo_text_20260928_184131.json", point_time=p1_time, kind="sims"
        )
        + _grade_sim_or_probe_file(
            "sims_audiocheck_audio_20260928_184320.json", point_time=p1_time, kind="sims"
        )
        + _grade_sim_or_probe_file(
            "probes_text_20260928_182711.json",
            point_time="2026-09-28T18:27:11Z",
            kind="probes",
            id_prefix="burst1827",
        )
        + _grade_sim_or_probe_file(
            "sims_repo_text_20260928_182715.json",
            point_time="2026-09-28T18:27:15Z",
            kind="sims",
            id_prefix="burst1827",
        )
    )
    p1_tests.sort(key=lambda t: (str(t["id"]), int(t.get("repeat", 1))))
    rec1 = records.build_record(
        mode="imported",
        run_id="20260928T184131Z_imported_a7c3094",
        started_at="2026-09-28T18:25:11Z",
        finished_at="2026-09-28T18:43:20Z",
        point_time=p1_time,
        agent={
            "commit": sha_a7c,
            "path": "cxas_app",
            "tree_hash": tree_a7c,
            "dirty": False,
            "dirty_paths_relevant": [],
            "dirty_paths_unrelated": [],
        },
        suite={
            "commit": suite_head,
            "dirty": suite_dirty["suite_dirty"],
            "dirty_paths": suite_dirty["suite_dirty_paths"],
        },
        cxas={
            "app": config.app_name(),
            "version_id": "8f80d3eb-8290-419a-94d7-ceff64b804c1",
            "version_status": "in_version_list",
            "model": "gemini-2.5-flash",
            "app_update_time": "2026-09-28T18:25:00Z",
            "app_etag": None,
        },
        rationale=(
            "Imported Gemini 2.5 Flash live baseline (Version 1 8f80d3eb): re-graded "
            "sims (184131, 182715), probes (183505, 182711), audio (184320), goldens (182733), "
            "and remote tool tests (182511) with totto_suite.grader; 429 quota bursts isolated as INFRA_ERROR[quota]"
        ),
        tests=p1_tests,
        imported=True,
        import_source=(
            "scratch/results/{tools_text_20260928_182511.json,goldens_text_20260928_182733.json,"
            "probes_text_20260928_182711.json,sims_repo_text_20260928_182715.json,"
            "probes_text_20260928_183505.json,sims_repo_text_20260928_184131.json,"
            "sims_audiocheck_audio_20260928_184320.json}"
        ),
        extra={"backfilled_at": now_iso},
    )

    # 2. 2026-09-28T19:18:53Z — Gemini 3 Flash model switch on same prompt tree (v1 8f80d3eb...)
    p2_time = "2026-09-28T19:18:53Z"
    p2_tests = (
        _grade_sim_or_probe_file(
            "probes_text_20260928_190909.json", point_time=p2_time, kind="probes"
        )
        + _grade_sim_or_probe_file(
            "sims_smoke3flash_audio_audio_20260928_191635.json",
            point_time=p2_time,
            kind="sims",
        )
        + _grade_sim_or_probe_file(
            "sims_baseline1831_on3flash_text_20260928_191853.json",
            point_time=p2_time,
            kind="sims",
        )
    )
    p2_tests.sort(key=lambda t: (str(t["id"]), int(t.get("repeat", 1))))
    rec2 = records.build_record(
        mode="imported",
        run_id="20260928T191853Z_imported_a7c3094",
        started_at="2026-09-28T19:09:09Z",
        finished_at="2026-09-28T19:18:53Z",
        point_time=p2_time,
        agent={
            "commit": sha_a7c,
            "path": "cxas_app",
            "tree_hash": tree_a7c,
            "dirty": False,
            "dirty_paths_relevant": [],
            "dirty_paths_unrelated": [],
        },
        suite={
            "commit": suite_head,
            "dirty": suite_dirty["suite_dirty"],
            "dirty_paths": suite_dirty["suite_dirty_paths"],
        },
        cxas={
            "app": config.app_name(),
            "version_id": "8f80d3eb-8290-419a-94d7-ceff64b804c1",
            "version_status": "in_version_list",
            "model": "gemini-3.0-flash-001",
            "app_update_time": "2026-09-28T19:08:00Z",
            "app_etag": None,
        },
        rationale=(
            "Imported Gemini 3 Flash model upgrade on baseline prompts (a7c3094): "
            "eliminated dead-air handoffs and raw Python code leaks in text sims, while "
            "totto_suite.grader catches past-race British GP date drift and freshness disclosure omissions"
        ),
        tests=p2_tests,
        imported=True,
        import_source=(
            "scratch/results/{probes_text_20260928_190909.json,"
            "sims_smoke3flash_audio_audio_20260928_191635.json,"
            "sims_baseline1831_on3flash_text_20260928_191853.json}"
        ),
        extra={"backfilled_at": now_iso},
    )

    # 3. 2026-09-28T20:50:30Z — Gemini 3 Flash Round 2 pinned instructions (f073e02, hidden version 534c9b06...)
    p3_time = "2026-09-28T20:50:30Z"
    p3_tests = (
        _grade_tools_file("tool_probes_20260928_203656.json")
        + _grade_tools_file("tools_text_20260928_203713.json")
        + _grade_sim_or_probe_file(
            "sims_round2_baseline1831_text_20260928_204506.json",
            point_time=p3_time,
            kind="sims",
        )
        + _grade_sim_or_probe_file(
            "probes_text_20260928_204757.json", point_time=p3_time, kind="probes"
        )
        + _grade_sim_or_probe_file(
            "sims_round2_audio_audio_20260928_204951.json",
            point_time=p3_time,
            kind="sims",
        )
        + _grade_goldens_file("goldens_text_20260928_205030.json")
    )
    p3_tests.sort(key=lambda t: (str(t["id"]), int(t.get("repeat", 1))))
    rec3 = records.build_record(
        mode="imported",
        run_id="20260928T205030Z_imported_f073e02",
        started_at="2026-09-28T20:36:56Z",
        finished_at="2026-09-28T20:50:30Z",
        point_time=p3_time,
        agent={
            "commit": sha_f07,
            "path": "cxas_app",
            "tree_hash": tree_f07,
            "dirty": False,
            "dirty_paths_relevant": [],
            "dirty_paths_unrelated": [],
        },
        suite={
            "commit": suite_head,
            "dirty": suite_dirty["suite_dirty"],
            "dirty_paths": suite_dirty["suite_dirty_paths"],
        },
        cxas={
            "app": config.app_name(),
            "version_id": "534c9b06-bd43-41c3-9f8c-abe31d6f8b4c",
            "version_status": "hidden_fetchable",
            "model": "gemini-3.0-flash-001",
            "app_update_time": "2026-09-28T20:55:38.643615Z",
            "app_etag": "00001053-0000-2320-a1f6-f4f5e80a8398",
        },
        rationale=(
            "Imported Gemini 3 Flash Round 2 evaluation (commit f073e02, hidden fetchable "
            "version 534c9b06): PIF XML prompt & tool fixes across sims (204506), probes (204757), "
            "audio (204951), goldens (205030), and remote tool probes (203656/203713)"
        ),
        tests=p3_tests,
        imported=True,
        import_source=(
            "scratch/results/{tool_probes_20260928_203656.json,tools_text_20260928_203713.json,"
            "sims_round2_baseline1831_text_20260928_204506.json,probes_text_20260928_204757.json,"
            "sims_round2_audio_audio_20260928_204951.json,goldens_text_20260928_205030.json}"
        ),
        extra={"backfilled_at": now_iso},
    )

    return [rec1, rec2, rec3]


def run_backfill(
    *,
    repo_root: Path | None = None,
    runs_dir: Path | None = None,
    overwrite: bool = True,
    regenerate_trend: bool = True,
) -> dict[str, Any]:
    """Generate the 6 historical backfill records and update trend artifacts."""
    repo_root_path = Path(repo_root).resolve() if repo_root else config.REPO_ROOT
    target_runs_dir = (
        Path(runs_dir).resolve()
        if runs_dir
        else (repo_root_path / "evals" / "history" / "runs")
    )
    target_runs_dir.mkdir(parents=True, exist_ok=True)

    reproduced = _build_reproduced_records(repo_root_path)
    imported = _build_imported_records(repo_root_path)
    all_backfilled = reproduced + imported

    written_paths: list[str] = []
    for rec in all_backfilled:
        rpath = records.record_path(rec["run_id"], runs_dir=target_runs_dir)
        if rpath.exists() and overwrite:
            rpath.unlink()
        if not rpath.exists():
            records.write_record(rec, runs_dir=target_runs_dir)
        written_paths.append(str(rpath))

    trend_info = None
    if regenerate_trend and target_runs_dir == config.RUNS_DIR:
        trend_info = trend.generate()

    return {
        "reproduced_count": len(reproduced),
        "imported_count": len(imported),
        "total_backfilled": len(all_backfilled),
        "run_ids": [r["run_id"] for r in all_backfilled],
        "written_paths": written_paths,
        "trend_info": trend_info,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="totto_suite backfill",
        description="Backfill 3 reproduced historical commits and 3 imported live evaluation runs.",
    )
    parser.add_argument(
        "--runs-dir",
        type=Path,
        default=None,
        help="Optional target runs directory (default: evals/history/runs).",
    )
    parser.add_argument(
        "--no-trend",
        action="store_true",
        help="Skip regenerating evals/history/{index.json,TREND.md,trend.html}.",
    )
    args = parser.parse_args(argv)

    print("[backfill] Generating 3 reproduced commit records + 3 imported live-run records...", flush=True)
    res = run_backfill(
        runs_dir=args.runs_dir,
        overwrite=True,
        regenerate_trend=not args.no_trend,
    )
    for rid, p in zip(res["run_ids"], res["written_paths"]):
        print(f"  - {rid} -> {config.repo_relative(p)}", flush=True)
    if res.get("trend_info"):
        ti = res["trend_info"]
        print(
            f"[backfill] Trend regenerated: {ti['points']} total points, {ti['regressions']} regression flags",
            flush=True,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
