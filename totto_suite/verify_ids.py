"""Platform ID verification (`python -m totto_suite verify-ids`).

Independently fetches every `platform_ids` entry recorded in a run record
(`conversation`, `session_id`, `evaluation`, `evaluation_run`,
`evaluation_result`, `tool`, `app_version`) from the CXAS API and writes
`evals/history/artifacts/<run_id>/verify_ids.json`.

Records store IDs relative to the app (``evaluationRuns/<uuid>``,
``sessions/<uuid>``, ...) plus an ``app_ref``; this command prefixes them with
``--app-name`` (default: resolved from the environment / gitignored
gecx-config.json for the record's ``app_ref``). Legacy records stored full
resource names; those are fetched as-is, except sanitized placeholders
(``projects/your-gcp-project/...``), which can never resolve and are reported
as ``legacy_unverifiable`` instead of failures.

The report itself contains no project or app identifiers.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
from typing import Any

from totto_suite import config, ids, records

PRIMARY_KINDS = (
    "conversation",
    "session_id",
    "evaluation",
    "evaluation_run",
    "evaluation_result",
    "tool",
)
VERIFIABLE_MODES = ("live", "ci")


def _find_latest_run() -> Path:
    all_recs = records.load_all()
    candidates = [r for r in all_recs if r["mode"] in VERIFIABLE_MODES]
    if not candidates:
        raise FileNotFoundError("No live/ci run records found in evals/history/runs/")
    latest_rec = max(candidates, key=lambda r: (r["started_at"], r["run_id"]))
    return records.record_path(latest_rec["run_id"])


def _full_name(app_name: str, kind: str, value: str) -> str:
    """Full resource name for one platform_ids value (legacy names pass through)."""
    rel = ids.relative_id(kind, value)
    if kind == "session_id":
        # A session's transcript is stored as the conversation with the same id.
        rel = f"conversations/{ids.last_segment(rel)}"
    return ids.to_full(app_name, rel)


def verify_run_record(
    record: dict[str, Any],
    *,
    app_name: str,
    ch_client: Any = None,
    ev_client: Any = None,
    tools_client: Any = None,
    versions_client: Any = None,
) -> dict[str, Any]:
    """Verify all `platform_ids` in `record` against CXAS APIs of ``app_name``."""
    run_id = str(record.get("run_id") or "unknown")

    def lazy(client, factory):
        state = {"c": client}

        def get():
            if state["c"] is None:
                state["c"] = factory()
            return state["c"]

        return get

    # pylint: disable=import-outside-toplevel
    def _ch():
        from cxas_scrapi.core.conversation_history import ConversationHistory

        return ConversationHistory(app_name=app_name, transport="rest")

    def _ev():
        from cxas_scrapi.core.evaluations import Evaluations

        return Evaluations(app_name=app_name)

    def _tl():
        from cxas_scrapi.core.tools import Tools

        return Tools(app_name=app_name)

    def _vr():
        from cxas_scrapi.core.versions import Versions

        return Versions(app_name=app_name)

    # pylint: enable=import-outside-toplevel
    ch, ev = lazy(ch_client, _ch), lazy(ev_client, _ev)
    tl, vr = lazy(tools_client, _tl), lazy(versions_client, _vr)

    resource_cache: dict[str, dict[str, Any]] = {}

    def check_resource(kind: str, raw_id: str) -> dict[str, Any]:
        rel = ids.relative_id(kind, raw_id)
        cache_key = f"{kind}:{rel}"
        if cache_key in resource_cache:
            return resource_cache[cache_key]
        res: dict[str, Any] = {"kind": kind, "id": ids.redact_text(rel, app_name)}
        if ids.is_placeholder_id(raw_id):
            res.update(
                ok=None,
                legacy=True,
                note="legacy_unverifiable: sanitized placeholder full name from a"
                " record written before app-relative IDs",
            )
            resource_cache[cache_key] = res
            return res
        if ids.is_legacy_id(raw_id):
            res["legacy"] = True
        full = _full_name(app_name, kind, raw_id)
        try:
            if kind in ("conversation", "session_id"):
                obj = ch().get_conversation(full)
                res["turns_count"] = len(getattr(obj, "turns", []) or [])
            elif kind == "evaluation":
                obj = ev().get_evaluation(full)
                res["display_name"] = str(getattr(obj, "display_name", ""))
            elif kind == "evaluation_run":
                obj = ev().get_evaluation_run(full)
                res["state"] = str(getattr(obj, "state", ""))
            elif kind == "evaluation_result":
                obj = ev().get_evaluation_result(full)
                res["evaluation_status"] = int(getattr(obj, "evaluation_status", 0) or 0)
            elif kind == "tool":
                obj = tl().get_tool(full)
                res["display_name"] = str(getattr(obj, "display_name", ""))
            elif kind == "app_version":
                obj = vr().get_version(ids.last_segment(full))
                res["display_name"] = str(getattr(obj, "display_name", ""))
            else:
                res.update(ok=None, note="unrecognized kind; not checked")
                resource_cache[cache_key] = res
                return res
            name = str(getattr(obj, "name", ""))
            res["ok"] = bool(name)
            res["resource_name"] = ids.to_app_relative(name)
        except Exception as exc:  # noqa: BLE001
            res["ok"] = False
            res["error"] = ids.redact_text(f"{type(exc).__name__}: {exc}", app_name)
        resource_cache[cache_key] = res
        return res

    entries: list[dict[str, Any]] = []
    verified_count = failed_count = legacy_count = 0

    for test in record.get("tests") or []:
        t_id = str(test.get("id") or "")
        rep = int(test.get("repeat") or 1)
        pids = {k: v for k, v in (test.get("platform_ids") or {}).items() if v}
        entry: dict[str, Any] = {
            "id": t_id,
            "repeat": rep,
            "layer": test.get("layer"),
            "status": test.get("status"),
        }
        if not pids:
            entry.update(ok=False, error="platform_ids is empty", checks={})
            entries.append(entry)
            failed_count += 1
            continue

        checks = {k: check_resource(k, str(v)) for k, v in pids.items()}
        oks = [c.get("ok") for c in checks.values()]
        primary = [checks[k].get("ok") for k in PRIMARY_KINDS if k in checks]
        if any(o is False for o in oks):
            ok: bool | None = False
        elif any(p is True for p in primary):
            ok = True
        elif primary and all(p is None for p in primary):
            ok = None  # nothing checkable: legacy placeholders only
        else:
            ok = False  # no primary id at all
        entry.update(ok=ok, checks=checks)
        if ok is None:
            entry["legacy"] = True
            legacy_count += 1
        elif ok:
            verified_count += 1
        else:
            failed_count += 1
        entries.append(entry)

    unique_checked = [v for v in resource_cache.values() if v.get("ok") is not None]
    return {
        "run_id": run_id,
        "verified_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "app_ref": record.get("app_ref") or "legacy",
        "total_test_entries": len(entries),
        "verified_test_entries": verified_count,
        "failed_test_entries": failed_count,
        "legacy_unverifiable_entries": legacy_count,
        "unique_resources_checked": len(unique_checked),
        "unique_resources_verified": sum(1 for v in unique_checked if v.get("ok")),
        "all_verified": verified_count > 0 and failed_count == 0,
        "entries": entries,
        "resource_cache": resource_cache,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="totto_suite verify-ids",
        description="Verify that every platform_ids entry in a run record is fetchable.",
    )
    parser.add_argument(
        "--run-id",
        default=None,
        help="Run ID to verify (defaults to the latest live/ci run).",
    )
    parser.add_argument(
        "--app-name",
        default=None,
        help="Full CXAS app resource name the record's app-relative IDs belong to"
        " (default: $TOTTO_APP_NAME / env / gecx-config.json for the record's app_ref).",
    )
    args = parser.parse_args(argv)

    run_path = records.record_path(args.run_id) if args.run_id else _find_latest_run()
    if not run_path.exists():
        print(f"error: run record not found: {run_path}", file=sys.stderr)
        return 1

    record = records.load_record(run_path)
    run_id = str(record.get("run_id") or run_path.stem)
    target = "staging" if record.get("app_ref") == "staging" else "live"
    try:
        app_name = ids.resolve_app_name(args.app_name, target=target)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    report = verify_run_record(record, app_name=app_name)

    art_dir = config.ARTIFACTS_DIR / run_id
    art_dir.mkdir(parents=True, exist_ok=True)
    out_path = art_dir / "verify_ids.json"
    out_path.write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    print(
        f"[verify-ids] run_id={run_id} app_ref={report['app_ref']}: "
        f"{report['verified_test_entries']}/{report['total_test_entries']} test entries verified, "
        f"{report['failed_test_entries']} failed, "
        f"{report['legacy_unverifiable_entries']} legacy (unverifiable placeholders); "
        f"{report['unique_resources_verified']}/{report['unique_resources_checked']}"
        " unique platform resources fetched.",
        flush=True,
    )
    print(f"[verify-ids] Report written: {config.repo_relative(out_path)}", flush=True)
    return 0 if report["all_verified"] else 1
