"""Live layer: live_goldens (platform golden evaluations, one batched run).

All goldens from ``evals/goldens/goldens.yaml`` are synced to the target app
(created if missing, updated when the YAML changed — tracked by a
``src-<sha>`` tag) and run in ONE ``runEvaluation`` request with
``run_count = repeats`` and ``golden_run_method = NAIVE``. The request sets
``config.toolCallBehaviour`` from ``ctx["tool_mode"]`` (FAKE or REAL); SCRAPI's
``Evaluations.run_evaluation`` has no such argument, so the request is built
with ``google.cloud.ces_v1beta`` directly. The platform schedules the runs.
"""

from __future__ import annotations

import hashlib
import json
import time
from typing import Any

from google.cloud import ces_v1beta as ces

from cxas_scrapi.core.evaluations import Evaluations
from cxas_scrapi.utils.eval_utils import EvalUtils
from totto_suite import fakes
from totto_suite.live.runner import (
    DEFAULT_APP_NAME,
    is_quota_or_infra_error,
    save_layer_artifact,
    slugify,
    use_tool_fakes,
    with_quota_retry,
)
from totto_suite.config import REPO_ROOT

LAYER = "live_goldens"
GOLDENS_YAML = REPO_ROOT / "evals" / "goldens" / "goldens.yaml"
DISPLAY_PREFIX = "r4-totto-"
RUN_TIMEOUT_S = 900
POLL_S = 8
_TERMINAL_RUN_STATES = {"COMPLETED", "ERROR", "FAILED", "CANCELLED"}


def _extract_run_name(run_op: Any) -> str:
    """Extract the `projects/.../evaluationRuns/<id>` resource name from `run_evaluation` operation."""
    meta = getattr(run_op, "metadata", None)
    if meta and getattr(meta, "evaluation_run", ""):
        return str(meta.evaluation_run)
    try:
        resp = run_op.result(timeout=300)
        if getattr(resp, "evaluation_run", ""):
            return str(resp.evaluation_run)
    except Exception:  # noqa: BLE001
        pass
    return ""


def _enum_name(value: Any) -> str:
    return str(getattr(value, "name", "") or value or "")


def source_tag(golden: dict[str, Any]) -> str:
    """Content hash tag of a golden definition (excluding its tags)."""
    body = {k: v for k, v in golden.items() if k != "tags"}
    digest = hashlib.sha256(
        json.dumps(body, sort_keys=True, ensure_ascii=False, default=str).encode("utf-8")
    ).hexdigest()
    return f"src-{digest[:10]}"


def _sync_evaluations(
    ev: Evaluations, eu: EvalUtils, app_name: str
) -> list[tuple[str, str, str]]:
    """Returns [(original_name, display_name, evaluation resource name)]."""
    golden_dicts = eu.load_golden_evals_from_yaml(str(GOLDENS_YAML), auto_sideload=False)
    existing_by_display: dict[str, Any] = {}
    for e_obj in ev.list_evaluations():
        existing_by_display[str(e_obj.display_name)] = e_obj

    synced: list[tuple[str, str, str]] = []
    for g_dict in golden_dicts:
        orig_name = str(g_dict.get("displayName") or "golden")
        prefixed = orig_name if orig_name.startswith(DISPLAY_PREFIX) else f"{DISPLAY_PREFIX}{orig_name}"
        g_dict["displayName"] = prefixed
        tag = source_tag(g_dict)
        tags = [t for t in (g_dict.get("tags") or []) if not str(t).startswith("src-")]
        g_dict["tags"] = tags + ["r4-totto", tag]

        existing = existing_by_display.get(prefixed)
        if existing is None:
            eval_obj, _ = with_quota_retry(
                lambda gd=g_dict: ev.create_evaluation(evaluation=gd, app_name=app_name),
                label=f"create_evaluation[{prefixed}]",
            )
        elif tag not in list(getattr(existing, "tags", []) or []):
            g_dict["name"] = str(existing.name)
            eval_obj, _ = with_quota_retry(
                lambda gd=g_dict: ev.update_evaluation(evaluation=gd, app_name=app_name),
                label=f"update_evaluation[{prefixed}]",
            )
        else:
            eval_obj = existing
        synced.append((orig_name, prefixed, str(eval_obj.name)))
    return synced


def _start_run(
    ev: Evaluations,
    app_name: str,
    eval_names: list[str],
    repeats: int,
    fake: bool,
    display_name: str,
) -> str:
    behaviour = (
        ces.EvaluationToolCallBehaviour.FAKE if fake else ces.EvaluationToolCallBehaviour.REAL
    )
    request = ces.RunEvaluationRequest(
        app=app_name,
        evaluations=eval_names,
        display_name=display_name[:60],
        run_count=repeats,
        golden_run_method=ces.GoldenRunMethod.NAIVE,
        config=ces.EvaluationConfig(
            tool_call_behaviour=behaviour,
            evaluation_channel=ces.EvaluationConfig.EvaluationChannel.TEXT,
        ),
    )
    op, _ = with_quota_retry(
        lambda: ev.client.run_evaluation(request=request),
        label="run_evaluation[goldens batch]",
    )
    return _extract_run_name(op)


def _wait_for_run(ev: Evaluations, run_name: str, timeout_s: int = RUN_TIMEOUT_S) -> tuple[Any, list[Any]]:
    start = time.monotonic()
    run_obj = None
    while time.monotonic() - start < timeout_s:
        try:
            run_obj = ev.get_evaluation_run(run_name)
            if _enum_name(getattr(run_obj, "state", "")) in _TERMINAL_RUN_STATES:
                break
        except Exception as exc:  # noqa: BLE001
            if not is_quota_or_infra_error(str(exc)):
                raise
        time.sleep(POLL_S)
    results = list(ev.list_evaluation_results_by_run(run_name))
    return run_obj, results


def _result_status(res_obj: Any, res_dict: dict[str, Any]) -> tuple[str, list[str]]:
    findings: list[str] = []
    exec_state = _enum_name(getattr(res_obj, "execution_state", ""))
    eval_status = _enum_name(getattr(res_obj, "evaluation_status", ""))
    if exec_state == "ERROR":
        err = res_dict.get("error_info") or res_dict.get("error") or "execution_state=ERROR"
        findings.append(f"EvaluationResult execution_state=ERROR: {err}")
        return "INFRA_ERROR", findings
    if eval_status == "PASS":
        return "PASS", findings
    if exec_state and exec_state != "COMPLETED":
        findings.append(f"EvaluationResult not completed (execution_state={exec_state})")
        return "INFRA_ERROR", findings
    return "FAIL", findings


def _failure_details(eu: EvalUtils, res_obj: Any) -> list[str]:
    out: list[str] = []
    try:
        dfs = eu.evals_to_dataframe(results=[res_obj])
        f_df = dfs.get("failures")
        if f_df is not None and not f_df.empty:
            for _, f_row in f_df.iterrows():
                out.append(
                    f"[{f_row.get('failure_type')}] expected={f_row.get('expected')} | "
                    f"actual={f_row.get('actual')} (score={f_row.get('score')})"
                )
    except Exception:  # noqa: BLE001
        pass
    return out


def run(ctx: dict[str, Any]) -> list[dict[str, Any]]:
    app_name = str(ctx.get("app_name") or DEFAULT_APP_NAME)
    repeats = max(1, int(ctx.get("repeats") or 3))
    fake = use_tool_fakes(ctx)
    tool_mode = "fake" if fake else "real"

    eu = EvalUtils(app_name=app_name)
    ev = Evaluations(app_name=app_name)
    synced = _sync_evaluations(ev, eu, app_name)
    by_eval = {name: (orig, prefixed) for orig, prefixed, name in synced}

    t0 = time.monotonic()
    run_error: str | None = None
    run_name = ""
    run_obj = None
    eval_results: list[Any] = []
    try:
        run_name = _start_run(
            ev,
            app_name,
            [name for _, _, name in synced],
            repeats,
            fake,
            f"totto-{ctx.get('run_id') or 'adhoc'}-{tool_mode}",
        )
        if not run_name:
            raise RuntimeError("runEvaluation returned no evaluation_run name")
        run_obj, eval_results = _wait_for_run(ev, run_name)
    except Exception as exc:  # noqa: BLE001
        run_error = f"{type(exc).__name__}: {exc}"
    wall_s = round(time.monotonic() - t0, 2)

    run_dict = type(run_obj).to_dict(run_obj) if run_obj is not None else {}
    run_state = _enum_name(getattr(run_obj, "state", "")) if run_obj is not None else ""
    run_behaviour = _enum_name(
        getattr(getattr(run_obj, "config", None), "tool_call_behaviour", "")
    ) if run_obj is not None else ""
    save_layer_artifact(
        ctx,
        "live_goldens/evaluation_run.json",
        {"evaluation_run": run_name, "state": run_state, "wall_s": wall_s,
         "error": run_error, "raw_run": run_dict},
    )

    grouped: dict[str, list[Any]] = {name: [] for name in by_eval}
    for res in eval_results:
        parent = str(getattr(res, "name", "")).split("/results/")[0]
        grouped.setdefault(parent, []).append(res)

    results: list[dict[str, Any]] = []
    raw_artifacts: list[dict[str, Any]] = []
    for eval_name, (orig_name, prefixed) in by_eval.items():
        res_list = sorted(
            grouped.get(eval_name, []),
            key=lambda r: (str(getattr(r, "create_time", "")), str(getattr(r, "name", ""))),
        )
        for rep_idx in range(1, repeats + 1):
            res_obj = res_list[rep_idx - 1] if rep_idx <= len(res_list) else None
            res_dict = type(res_obj).to_dict(res_obj) if res_obj is not None else {}
            if run_error:
                status = "INFRA_ERROR" if is_quota_or_infra_error(run_error) else "FAIL"
                findings = [run_error]
            elif res_obj is None:
                status = "INFRA_ERROR"
                findings = [
                    f"No EvaluationResult #{rep_idx} for {prefixed} "
                    f"(run state={run_state or 'unknown'})"
                ]
            else:
                status, findings = _result_status(res_obj, res_dict)
                if status == "FAIL":
                    findings.extend(_failure_details(eu, res_obj))
                    if not findings:
                        findings.append(f"Golden evaluation {prefixed} failed.")

            conv_name = ""
            turn_replays = (res_dict.get("golden_result") or {}).get("turn_replay_results") or []
            if turn_replays and isinstance(turn_replays[0], dict):
                conv_name = str(turn_replays[0].get("conversation") or "")
            behaviour = _enum_name((res_dict.get("config") or {}).get("tool_call_behaviour", ""))
            if not behaviour and res_obj is not None:
                behaviour = _enum_name(
                    getattr(getattr(res_obj, "config", None), "tool_call_behaviour", "")
                )
            behaviour = behaviour or run_behaviour
            evidence = fakes.span_evidence(res_dict)
            result_tool_mode = (
                "fake" if behaviour == "FAKE" else ("real" if behaviour == "REAL" else tool_mode)
            )

            art_payload = {
                "display_name": prefixed,
                "original_name": orig_name,
                "repeat": rep_idx,
                "evaluation": eval_name,
                "evaluation_run": run_name,
                "evaluation_result": str(getattr(res_obj, "name", "") or ""),
                "conversation": conv_name,
                "status": status,
                "findings": findings,
                "tool_call_behaviour": behaviour,
                "fake_evidence": evidence,
                "raw_result": res_dict,
            }
            raw_artifacts.append(art_payload)
            art_path = save_layer_artifact(
                ctx, f"live_goldens/{slugify(orig_name)}_r{rep_idx}.json", art_payload
            )

            platform_ids: dict[str, Any] = {
                "evaluation": eval_name,
                "evaluation_run": run_name,
            }
            if res_obj is not None:
                platform_ids["evaluation_result"] = str(res_obj.name)
            # The run carries the auto-created version it evaluated; results
            # usually leave app_version empty.
            app_version = str(
                (getattr(res_obj, "app_version", "") if res_obj is not None else "")
                or getattr(run_obj, "app_version", "")
                or ""
            )
            if app_version:
                platform_ids["app_version"] = app_version
            if conv_name:
                platform_ids["conversation"] = conv_name
                platform_ids["session_id"] = conv_name.split("/")[-1]

            turn_latencies = [
                t.get("turn_latency") for t in turn_replays if isinstance(t, dict) and t.get("turn_latency")
            ]
            results.append(
                {
                    "id": f"{LAYER}::{slugify(orig_name)}",
                    "layer": LAYER,
                    "repeat": rep_idx,
                    "status": status,
                    "duration_s": wall_s,
                    "duration_ms": round(wall_s * 1000.0, 2),
                    "message": "; ".join(findings) if findings else "ok",
                    "platform_ids": platform_ids,
                    "tool_mode": result_tool_mode,
                    "fake_evidence": evidence,
                    "metrics": {
                        "evaluation_status": _enum_name(getattr(res_obj, "evaluation_status", "")),
                        "execution_state": _enum_name(getattr(res_obj, "execution_state", "")),
                        "golden_run_method": "NAIVE",
                        "tool_call_behaviour": behaviour,
                        "batched_run_wall_s": wall_s,
                        "turn_latency": turn_latencies,
                    },
                    "findings": findings,
                    "evidence": art_path,
                    "raw_artifact_path": art_path,
                }
            )

    save_layer_artifact(ctx, "live_goldens/summary.json", raw_artifacts)
    return results
