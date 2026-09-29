"""Platform ID verification (`python -m totto_suite verify-ids`).

Independently fetches every `platform_ids` entry recorded in a live run record
(`conversation`, `session_id`, `evaluation`, `evaluation_run`, `evaluation_result`,
`tool`, `app_version`) from the live CXAS API and writes
`evals/history/artifacts/<run_id>/verify_ids.json`.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
from typing import Any

from cxas_scrapi.core.conversation_history import ConversationHistory
from cxas_scrapi.core.evaluations import Evaluations
from cxas_scrapi.core.tools import Tools
from cxas_scrapi.core.versions import Versions
from totto_suite import config, records
from totto_suite.live.runner import DEFAULT_APP_NAME


def _find_latest_live_run() -> Path:
    all_recs = records.load_all()
    latest_rec = records.latest(all_recs, "live")
    if not latest_rec:
        raise FileNotFoundError("No live run records found in evals/history/runs/")
    return records.record_path(latest_rec["run_id"])


def verify_run_record(
    record: dict[str, Any],
    *,
    app_name: str = DEFAULT_APP_NAME,
    ch_client: Any = None,
    ev_client: Any = None,
    tools_client: Any = None,
    versions_client: Any = None,
) -> dict[str, Any]:
    """Verify all `platform_ids` in `record` against CXAS APIs."""
    run_id = str(record.get("run_id") or "unknown")
    ch = ch_client or ConversationHistory(app_name=app_name, transport="rest")
    ev = ev_client or Evaluations(app_name=app_name)
    tl = tools_client or Tools(app_name=app_name)
    vr = versions_client or Versions(app_name=app_name)

    resource_cache: dict[str, dict[str, Any]] = {}

    def check_resource(kind: str, raw_id: str) -> dict[str, Any]:
        cache_key = f"{kind}:{raw_id}"
        if cache_key in resource_cache:
            return resource_cache[cache_key]

        if not raw_id:
            res = {"kind": kind, "id": raw_id, "ok": False, "error": "empty ID"}
            resource_cache[cache_key] = res
            return res

        try:
            if kind in ("conversation", "session_id"):
                conv_obj = ch.get_conversation(raw_id)
                turns_len = len(getattr(conv_obj, "turns", []) or [])
                res = {
                    "kind": kind,
                    "id": raw_id,
                    "ok": bool(getattr(conv_obj, "name", "")),
                    "resource_name": str(getattr(conv_obj, "name", "")),
                    "turns_count": turns_len,
                }
            elif kind == "evaluation":
                eval_obj = ev.get_evaluation(raw_id)
                res = {
                    "kind": kind,
                    "id": raw_id,
                    "ok": bool(getattr(eval_obj, "name", "")),
                    "resource_name": str(getattr(eval_obj, "name", "")),
                    "display_name": str(getattr(eval_obj, "display_name", "")),
                }
            elif kind == "evaluation_run":
                run_obj = ev.get_evaluation_run(raw_id)
                res = {
                    "kind": kind,
                    "id": raw_id,
                    "ok": bool(getattr(run_obj, "name", "")),
                    "resource_name": str(getattr(run_obj, "name", "")),
                    "state": str(getattr(run_obj, "state", "")),
                }
            elif kind == "evaluation_result":
                res_obj = ev.get_evaluation_result(raw_id)
                res = {
                    "kind": kind,
                    "id": raw_id,
                    "ok": bool(getattr(res_obj, "name", "")),
                    "resource_name": str(getattr(res_obj, "name", "")),
                    "evaluation_status": int(getattr(res_obj, "evaluation_status", 0) or 0),
                }
            elif kind == "tool":
                full_tool = (
                    raw_id
                    if raw_id.startswith("projects/")
                    else f"{app_name}/tools/{raw_id}"
                )
                tool_obj = tl.get_tool(full_tool)
                res = {
                    "kind": kind,
                    "id": raw_id,
                    "ok": bool(getattr(tool_obj, "name", "")),
                    "resource_name": str(getattr(tool_obj, "name", "")),
                    "display_name": str(getattr(tool_obj, "display_name", "")),
                }
            elif kind == "app_version":
                short_ver = raw_id.split("/")[-1] if "/versions/" in raw_id else raw_id
                ver_obj = vr.get_version(short_ver)
                res = {
                    "kind": kind,
                    "id": raw_id,
                    "ok": bool(getattr(ver_obj, "name", "")),
                    "resource_name": str(getattr(ver_obj, "name", "")),
                    "display_name": str(getattr(ver_obj, "display_name", "")),
                }
            else:
                res = {"kind": kind, "id": raw_id, "ok": True, "note": "unrecognized kind"}
        except Exception as exc:  # noqa: BLE001
            res = {
                "kind": kind,
                "id": raw_id,
                "ok": False,
                "error": f"{type(exc).__name__}: {exc}",
            }

        resource_cache[cache_key] = res
        return res

    entries: list[dict[str, Any]] = []
    verified_count = 0
    failed_count = 0

    for test in record.get("tests") or []:
        t_id = str(test.get("id") or "")
        rep = int(test.get("repeat") or 1)
        pids = test.get("platform_ids") or {}
        if not pids:
            entries.append(
                {
                    "id": t_id,
                    "repeat": rep,
                    "ok": False,
                    "error": "platform_ids is empty",
                    "checks": {},
                }
            )
            failed_count += 1
            continue

        checks: dict[str, Any] = {}
        entry_ok = True
        has_primary_id = False

        for k, v in pids.items():
            if not v:
                continue
            if k in (
                "conversation",
                "session_id",
                "evaluation",
                "evaluation_run",
                "evaluation_result",
                "tool",
            ):
                has_primary_id = True
            chk = check_resource(k, str(v))
            checks[k] = chk
            if not chk.get("ok", False):
                entry_ok = False

        if not has_primary_id:
            entry_ok = False

        if entry_ok:
            verified_count += 1
        else:
            failed_count += 1

        entries.append(
            {
                "id": t_id,
                "repeat": rep,
                "layer": test.get("layer"),
                "status": test.get("status"),
                "ok": entry_ok,
                "checks": checks,
            }
        )

    total = len(entries)
    unique_total = len(resource_cache)
    unique_ok = sum(1 for v in resource_cache.values() if v.get("ok"))

    return {
        "run_id": run_id,
        "verified_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "app_name": app_name,
        "total_test_entries": total,
        "verified_test_entries": verified_count,
        "failed_test_entries": failed_count,
        "unique_resources_checked": unique_total,
        "unique_resources_verified": unique_ok,
        "all_verified": total > 0 and failed_count == 0,
        "entries": entries,
        "resource_cache": resource_cache,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="totto_suite verify-ids",
        description="Verify that every platform_ids entry in a live run record is fetchable.",
    )
    parser.add_argument(
        "--run-id",
        default=None,
        help="Run ID to verify (defaults to latest live run).",
    )
    parser.add_argument(
        "--app-name",
        default=DEFAULT_APP_NAME,
        help="Full CXAS app resource name.",
    )
    args = parser.parse_args(argv)

    if args.run_id:
        run_path = records.record_path(args.run_id)
    else:
        run_path = _find_latest_live_run()

    if not run_path.exists():
        print(f"error: run record not found: {run_path}", file=sys.stderr)
        return 1

    record = records.load_record(run_path)
    run_id = str(record.get("run_id") or run_path.stem)
    report = verify_run_record(record, app_name=args.app_name)

    art_dir = config.ARTIFACTS_DIR / run_id
    art_dir.mkdir(parents=True, exist_ok=True)
    out_path = art_dir / "verify_ids.json"
    out_path.write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    print(
        f"[verify-ids] run_id={run_id}: "
        f"{report['verified_test_entries']}/{report['total_test_entries']} test entries verified, "
        f"{report['unique_resources_verified']}/{report['unique_resources_checked']} unique platform resources fetched.",
        flush=True,
    )
    print(f"[verify-ids] Report written: {config.repo_relative(out_path)}", flush=True)
    return 0 if report["all_verified"] else 1
