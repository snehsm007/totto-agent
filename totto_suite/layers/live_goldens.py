"""Live layer: live_goldens (sequential NAIVE golden evaluations on the live app)."""

from __future__ import annotations

import time
from typing import Any

from cxas_scrapi.core.evaluations import Evaluations
from cxas_scrapi.utils.eval_utils import EvalUtils
from totto_suite.live.runner import (
    DEFAULT_APP_NAME,
    LIVE_VERSION_ID,
    is_quota_or_infra_error,
    save_layer_artifact,
    slugify,
    with_quota_retry,
)
from totto_suite.config import REPO_ROOT

LAYER = "live_goldens"
GOLDENS_YAML = REPO_ROOT / "evals" / "goldens" / "goldens.yaml"
DISPLAY_PREFIX = "r4-totto-"


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


def _wait_for_run_results(
    ev: Evaluations,
    run_name: str,
    eval_name: str,
    before_names: set[str],
    expected_count: int,
    timeout_s: int = 300,
) -> list[Any]:
    """Wait for an evaluation run to finish and return its `EvaluationResult` objects."""
    start = time.monotonic()
    while time.monotonic() - start < timeout_s:
        if run_name:
            try:
                run_obj = ev.get_evaluation_run(run_name)
                state_val = int(getattr(run_obj, "state", 0))
                state_name = getattr(getattr(run_obj, "state", None), "name", "")
                if state_val in (2, 3) or state_name in ("COMPLETED", "ERROR", "FAILED"):
                    res_list = list(ev.list_evaluation_results_by_run(run_name))
                    if res_list:
                        return res_list
            except Exception:  # noqa: BLE001
                pass
        try:
            fresh = [
                r
                for r in ev.list_evaluation_results(eval_name)
                if r.name not in before_names
            ]
            if len(fresh) >= expected_count and all(
                int(getattr(r, "execution_state", 0)) in (2, 3) for r in fresh
            ):
                return fresh
        except Exception:  # noqa: BLE001
            pass
        time.sleep(6)
    if run_name:
        try:
            return list(ev.list_evaluation_results_by_run(run_name))
        except Exception:  # noqa: BLE001
            pass
    return [
        r
        for r in ev.list_evaluation_results(eval_name)
        if r.name not in before_names
    ]


def run(ctx: dict[str, Any]) -> list[dict[str, Any]]:
    app_name = str(ctx.get("app_name") or DEFAULT_APP_NAME)
    repeats = max(1, int(ctx.get("repeats") or 3))

    eu = EvalUtils(app_name=app_name)
    ev = Evaluations(app_name=app_name)

    golden_dicts = eu.load_golden_evals_from_yaml(
        str(GOLDENS_YAML), auto_sideload=False
    )

    existing_by_display: dict[str, Any] = {}
    try:
        for e_obj in ev.list_evaluations():
            existing_by_display[str(e_obj.display_name)] = e_obj
    except Exception:  # noqa: BLE001
        pass

    results: list[dict[str, Any]] = []
    raw_artifacts: list[dict[str, Any]] = []

    for g_dict in golden_dicts:
        orig_name = str(g_dict.get("displayName") or "golden")
        prefixed_name = (
            orig_name
            if orig_name.startswith(DISPLAY_PREFIX)
            else f"{DISPLAY_PREFIX}{orig_name}"
        )
        g_dict["displayName"] = prefixed_name
        tags = list(g_dict.get("tags") or [])
        if "r4-totto" not in tags:
            tags.append("r4-totto")
        g_dict["tags"] = tags

        # Ensure evaluation exists on the live app (and keep it for verify-ids)
        eval_obj = existing_by_display.get(prefixed_name)
        if eval_obj is None:
            eval_obj, _ = with_quota_retry(
                lambda gd=g_dict: ev.create_evaluation(
                    evaluation=gd, app_name=app_name
                ),
                label=f"create_evaluation[{prefixed_name}]",
            )
            existing_by_display[prefixed_name] = eval_obj

        eval_resource_name = str(eval_obj.name)

        # Run sequentially one evaluation and one repeat at a time with golden_run_method="NAIVE"
        for rep_idx in range(1, repeats + 1):
            before_ids: set[str] = set()
            try:
                before_ids = {
                    str(r.name) for r in ev.list_evaluation_results(eval_resource_name)
                }
            except Exception:  # noqa: BLE001
                pass

            t0 = time.monotonic()
            run_error: str | None = None
            run_name = ""
            eval_results: list[Any] = []
            try:
                run_op, _ = with_quota_retry(
                    lambda en=eval_resource_name: ev.run_evaluation(
                        evaluations=[en],
                        app_name=app_name,
                        modality="text",
                        run_count=1,
                        golden_run_method="NAIVE",
                    ),
                    label=f"run_evaluation[{prefixed_name}:r{rep_idx}]",
                )
                run_name = _extract_run_name(run_op)
                eval_results = _wait_for_run_results(
                    ev,
                    run_name=run_name,
                    eval_name=eval_resource_name,
                    before_names=before_ids,
                    expected_count=1,
                )
            except Exception as exc:  # noqa: BLE001
                run_error = f"{type(exc).__name__}: {exc}"

            per_repeat_ms = round((time.monotonic() - t0) * 1000.0, 2)
            eval_results_sorted = sorted(
                eval_results, key=lambda r: str(getattr(r, "name", ""))
            )
            res_obj = eval_results_sorted[-1] if eval_results_sorted else None
            res_dict = (
                type(res_obj).to_dict(res_obj)
                if res_obj is not None and hasattr(type(res_obj), "to_dict")
                else (res_obj if isinstance(res_obj, dict) else {})
            )
            res_name = str(getattr(res_obj, "name", "") or res_dict.get("name", ""))
            res_run = str(
                getattr(res_obj, "evaluation_run", "")
                or res_dict.get("evaluation_run", "")
                or run_name
            )
            res_app_ver_full = str(
                getattr(res_obj, "app_version", "")
                or res_dict.get("app_version", "")
            )
            res_app_ver = (
                res_app_ver_full.split("/")[-1]
                if "/versions/" in res_app_ver_full
                else LIVE_VERSION_ID
            )

            conv_name = ""
            turn_replays = (
                res_dict.get("golden_result", {}).get("turn_replay_results", [])
                if isinstance(res_dict, dict)
                else []
            )
            if turn_replays and isinstance(turn_replays[0], dict):
                conv_name = str(turn_replays[0].get("conversation") or "")

            eval_status_int = int(getattr(res_obj, "evaluation_status", 0) or 0)
            exec_state_int = int(getattr(res_obj, "execution_state", 0) or 0)

            findings: list[str] = []
            if run_error:
                findings.append(run_error)
                status = (
                    "INFRA_ERROR"
                    if is_quota_or_infra_error(run_error)
                    else "FAIL"
                )
            elif res_obj is None:
                findings.append("No EvaluationResult returned by run_evaluation.")
                status = "INFRA_ERROR"
            elif exec_state_int == 3:
                err_info = res_dict.get("error_info") or res_dict.get("error") or "Execution state ERROR"
                findings.append(f"EvaluationResult execution_state=ERROR: {err_info}")
                status = "INFRA_ERROR"
            elif eval_status_int == 1:
                status = "PASS"
            else:
                status = "FAIL"
                # Extract failure details from EvalUtils.evals_to_dataframe if available
                try:
                    dfs = eu.evals_to_dataframe(results=[res_obj])
                    f_df = dfs.get("failures")
                    if f_df is not None and not f_df.empty:
                        for _, f_row in f_df.iterrows():
                            findings.append(
                                f"[{f_row.get('failure_type')}] expected={f_row.get('expected')} | "
                                f"actual={f_row.get('actual')} (score={f_row.get('score')})"
                            )
                except Exception:  # noqa: BLE001
                    pass
                if not findings:
                    findings.append(
                        f"Golden evaluation {prefixed_name} failed (evaluation_status={eval_status_int})."
                    )

            art_payload = {
                "display_name": prefixed_name,
                "original_name": orig_name,
                "repeat": rep_idx,
                "evaluation": eval_resource_name,
                "evaluation_run": res_run,
                "evaluation_result": res_name,
                "conversation": conv_name,
                "app_version": res_app_ver,
                "status": status,
                "findings": findings,
                "raw_result": res_dict,
            }
            raw_artifacts.append(art_payload)
            art_path = save_layer_artifact(
                ctx,
                f"live_goldens/{slugify(orig_name)}_r{rep_idx}.json",
                art_payload,
            )

            platform_ids: dict[str, Any] = {
                "evaluation": eval_resource_name,
                "evaluation_run": res_run,
                "evaluation_result": res_name,
                "app_version": res_app_ver,
            }
            if conv_name:
                platform_ids["conversation"] = conv_name
                platform_ids["session_id"] = conv_name.split("/")[-1]

            results.append(
                {
                    "id": f"{LAYER}::{slugify(orig_name)}",
                    "layer": LAYER,
                    "repeat": rep_idx,
                    "status": status,
                    "duration_s": round(per_repeat_ms / 1000.0, 3),
                    "duration_ms": per_repeat_ms,
                    "message": "; ".join(findings) if findings else "ok",
                    "platform_ids": platform_ids,
                    "metrics": {
                        "evaluation_status": eval_status_int,
                        "execution_state": exec_state_int,
                        "golden_run_method": "NAIVE",
                    },
                    "findings": findings,
                    "evidence": art_path,
                    "raw_artifact_path": art_path,
                }
            )

    save_layer_artifact(ctx, "live_goldens/summary.json", raw_artifacts)
    return results
