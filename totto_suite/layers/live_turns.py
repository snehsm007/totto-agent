"""Live layer: live_turns (TurnEvals across all 4 subagents)."""

from __future__ import annotations

import time
from typing import Any

from cxas_scrapi.core.conversation_history import ConversationHistory
from cxas_scrapi.evals.turn_evals import TurnEvals
from totto_suite.live.runner import (
    DEFAULT_APP_NAME,
    LIVE_VERSION_ID,
    is_quota_or_infra_error,
    resolve_conversation_resource,
    save_layer_artifact,
    slugify,
    with_quota_retry,
)
from totto_suite.config import REPO_ROOT

LAYER = "live_turns"
TURN_EVALS_YAML = REPO_ROOT / "evals" / "turn_evals" / "turn_evals.yaml"


def run(ctx: dict[str, Any]) -> list[dict[str, Any]]:
    app_name = str(ctx.get("app_name") or DEFAULT_APP_NAME)
    repeats = max(1, int(ctx.get("repeats") or 3))

    turn_evals = TurnEvals(app_name=app_name)
    ch_client = ConversationHistory(app_name=app_name, transport="rest")
    cases = turn_evals.load_turn_test_cases_from_file(str(TURN_EVALS_YAML))

    results: list[dict[str, Any]] = []
    raw_artifacts: list[dict[str, Any]] = []

    for rep_idx in range(1, repeats + 1):
        for tc in cases:
            t0 = time.monotonic()
            error_msg: str | None = None
            rows: list[dict[str, Any]] = []
            try:
                df, _ = with_quota_retry(
                    lambda c=tc: turn_evals.run_turn_tests([c]),
                    label=f"run_turn_tests[{tc.name}:r{rep_idx}]",
                )
                if df is not None and not df.empty:
                    rows = df.to_dict(orient="records")
            except Exception as exc:  # noqa: BLE001
                error_msg = f"{type(exc).__name__}: {exc}"

            duration_ms = round((time.monotonic() - t0) * 1000.0, 2)
            session_id = ""
            findings: list[str] = []
            failed_rows = 0

            for r in rows:
                if r.get("session_id") and not session_id:
                    session_id = str(r["session_id"])
                if str(r.get("status", "")).upper() in ("FAILURE", "FAILED", "ERROR"):
                    failed_rows += 1
                    err_detail = str(r.get("errors") or r.get("llm_results") or "")
                    findings.append(
                        f"Turn {r.get('turn') or 1}: {err_detail} "
                        f"(expected={r.get('expected')!r}, actual={r.get('actual')!r})"
                    )
                    if is_quota_or_infra_error(err_detail) and not error_msg:
                        error_msg = err_detail

            if error_msg:
                findings.append(error_msg)

            if error_msg and is_quota_or_infra_error(error_msg):
                status = "INFRA_ERROR"
            elif error_msg or failed_rows > 0 or not rows:
                status = "FAIL"
            else:
                status = "PASS"

            conv_name = resolve_conversation_resource(
                app_name, session_id, ch_client=ch_client
            )
            art_payload = {
                "name": tc.name,
                "repeat": rep_idx,
                "session_id": session_id,
                "conversation": conv_name,
                "status": status,
                "duration_ms": duration_ms,
                "rows": rows,
                "findings": findings,
            }
            raw_artifacts.append(art_payload)
            art_path = save_layer_artifact(
                ctx,
                f"live_turns/{slugify(tc.name)}_r{rep_idx}.json",
                art_payload,
            )

            results.append(
                {
                    "id": f"{LAYER}::{slugify(tc.name)}",
                    "layer": LAYER,
                    "repeat": rep_idx,
                    "status": status,
                    "duration_s": round(duration_ms / 1000.0, 3),
                    "duration_ms": duration_ms,
                    "message": "; ".join(findings) if findings else "ok",
                    "platform_ids": {
                        "session_id": session_id,
                        "conversation": conv_name,
                        "app_version": LIVE_VERSION_ID,
                    },
                    "metrics": {
                        "checks_count": len(rows),
                        "failed_checks_count": failed_rows,
                    },
                    "findings": findings,
                    "evidence": art_path,
                    "raw_artifact_path": art_path,
                }
            )

    save_layer_artifact(ctx, "live_turns/summary.json", raw_artifacts)
    return results
