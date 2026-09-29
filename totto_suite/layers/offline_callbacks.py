"""Offline layer: callbacks (pytest state callback tests + SCRAPI CallbackEvals)."""

from __future__ import annotations

import os
from pathlib import Path
import time
from typing import Any

from cxas_scrapi.evals.callback_evals import CallbackEvals

from totto_suite import config
from totto_suite.layers._pytest_runner import run_pytest_layer


def run(ctx: dict[str, Any]) -> list[dict[str, Any]]:
    results = run_pytest_layer(ctx, "callbacks")

    repo_root = Path(ctx.get("repo_root") or config.REPO_ROOT).resolve()
    app_dir = Path(ctx.get("app_dir") or config.DEFAULT_APP_DIR).resolve()
    cb_tests_dir = repo_root / "evals" / "callback_tests"
    if not cb_tests_dir.is_dir():
        return results

    prev_app_dir = os.environ.get("TOTTO_APP_DIR")
    os.environ["TOTTO_APP_DIR"] = str(app_dir)
    t0 = time.monotonic()
    try:
        df = CallbackEvals().test_all_callbacks_in_app_dir(str(cb_tests_dir))
    finally:
        if prev_app_dir is None:
            os.environ.pop("TOTTO_APP_DIR", None)
        else:
            os.environ["TOTTO_APP_DIR"] = prev_app_dir
    dur = round((time.monotonic() - t0) / max(len(df), 1), 6)

    scrapi_results: list[dict[str, Any]] = []
    for _, row in df.iterrows():
        agent_name = str(row.get("agent_name", ""))
        test_name = str(row.get("test_name", ""))
        raw_status = str(row.get("status", "")).upper()
        status = "PASS" if raw_status == "PASSED" else "FAIL"
        err = str(row.get("error_message") or "").strip()
        if err:
            err = err.splitlines()[0].replace(str(app_dir), "<APP_DIR>")
        test_id = f"callbacks::scrapi::{agent_name}::{test_name}"
        scrapi_results.append(
            {
                "id": test_id,
                "layer": "callbacks",
                "status": status,
                "repeat": 1,
                "duration_s": dur,
                "message": "" if status == "PASS" else err,
                "findings": ["PRD-AC5", "PRD-AC7", "TR-10"],
                "platform_ids": {},
                "evidence": None if status == "PASS" else err,
                "deterministic": {"passed": status == "PASS"},
                "judge": None,
            }
        )

    scrapi_results.sort(key=lambda r: r["id"])
    return results + scrapi_results
