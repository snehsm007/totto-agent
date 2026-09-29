"""Shared live evaluation runner helpers, quota retry, and artifact utilities."""

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import time
from typing import Any, Callable

from cxas_scrapi.core.apps import Apps
from cxas_scrapi.core.conversation_history import ConversationHistory
from cxas_scrapi.core.response_parser import ParsedSessionResponse
from cxas_scrapi.evals.simulation_evals import SimulationEvals
from cxas_scrapi.utils.eval_utils import evaluate_expectations
from totto_suite import config
from totto_suite import grader
from totto_suite import oracle

REPO_ROOT = config.REPO_ROOT
DEFAULT_APP_NAME = config.DEFAULT_APP_NAME
FAST_SIM_MODEL = "gemini-3.1-flash-lite"
FALLBACK_SIM_MODEL = "gemini-2.5-flash"
QUOTA_BACKOFF_S = (10, 20, 40, 60, 60)
TOOL_MODES = ("fake", "real")


def use_tool_fakes(ctx: dict[str, Any]) -> bool:
    """True when the layer context asks for platform tool fakes (R2)."""
    return str(ctx.get("tool_mode") or "real").lower() == "fake"

_OPENF1_FIXTURE_DIR = REPO_ROOT / "tests" / "fixtures" / "openf1"


def slugify(name: str) -> str:
    """Convert a test or scenario name into a stable test ID slug."""
    out = []
    for ch in str(name).lower():
        if ch.isalnum():
            out.append(ch)
        else:
            out.append("_")
    slug = "".join(out).strip("_")
    while "__" in slug:
        slug = slug.replace("__", "_")
    return slug or "unnamed"


def is_quota_or_infra_error(err_msg: str | None) -> bool:
    """Return True if an error message represents a 429/quota or transient infra error."""
    if not err_msg:
        return False
    kind = grader.infra_kind(err_msg)
    return kind in ("quota", "deadline", "server", "network", "bidi")


def with_quota_retry(
    fn: Callable[[], Any],
    *,
    label: str = "live_op",
    backoffs: tuple[int, ...] = QUOTA_BACKOFF_S,
) -> tuple[Any, float]:
    """Execute `fn()` with exponential backoff on 429/transient errors.

    Returns `(result, waited_seconds)`.
    """
    waited = 0.0
    last_exc: Exception | None = None
    for attempt in range(len(backoffs) + 1):
        try:
            res = fn()
            if isinstance(res, dict) and res.get("error"):
                if is_quota_or_infra_error(str(res.get("error"))) and attempt < len(backoffs):
                    wait_s = backoffs[attempt]
                    print(
                        f"  [retry] {label} hit transient/quota error "
                        f"({res.get('error')!r}); sleeping {wait_s}s...",
                        file=sys.stderr,
                    )
                    time.sleep(wait_s)
                    waited += wait_s
                    continue
            return res, waited
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            if is_quota_or_infra_error(str(exc)) and attempt < len(backoffs):
                wait_s = backoffs[attempt]
                print(
                    f"  [retry] {label} raised transient/quota exception "
                    f"({exc!r}); sleeping {wait_s}s...",
                    file=sys.stderr,
                )
                time.sleep(wait_s)
                waited += wait_s
                continue
            raise
    if last_exc is not None:
        raise last_exc
    return None, waited


def resolve_now(ctx: dict[str, Any]) -> datetime:
    """Extract UTC datetime from layer context `ctx`."""
    now_val = ctx.get("now_dt") or ctx.get("now")
    if isinstance(now_val, datetime):
        return now_val.astimezone(timezone.utc)
    if isinstance(now_val, str) and now_val:
        return oracle.parse_utc(now_val)
    return datetime.now(timezone.utc)


def resolve_dynamic_expectations(
    expectations: list[str], now_dt: datetime
) -> list[str]:
    """Attach runtime date context from `totto_suite.oracle` to expectations when relevant."""
    try:
        meetings, sessions = oracle.load_calendar(_OPENF1_FIXTURE_DIR)
        nxt = oracle.next_race(meetings, now_dt, sessions)
    except Exception:  # noqa: BLE001
        nxt = None
    date_str = now_dt.strftime("%Y-%m-%d")
    next_summary = (
        f"{nxt['meeting_name']} in {nxt['location']} "
        f"({nxt['date_start'][:10]}..{nxt['date_end'][:10]})"
        if nxt
        else "none remaining in 2026"
    )
    resolved: list[str] = []
    for exp in expectations:
        text = (
            str(exp)
            .replace("{{CURRENT_DATE}}", date_str)
            .replace("{{NEXT_RACE}}", next_summary)
        )
        resolved.append(text)
    return resolved


def get_artifact_dir(ctx: dict[str, Any]) -> Path:
    """Return the `evals/history/artifacts/<run_id>` directory, creating it if needed."""
    if ctx.get("artifacts_dir"):
        art_dir = Path(str(ctx["artifacts_dir"]))
    else:
        run_id = ctx.get("run_id") or "live-adhoc"
        art_dir = config.ARTIFACTS_DIR / str(run_id)
    art_dir.mkdir(parents=True, exist_ok=True)
    return art_dir


def save_layer_artifact(
    ctx: dict[str, Any], filename: str, payload: Any
) -> str:
    """Write `payload` as JSON under `evals/history/artifacts/<run_id>/<filename>` and return relative path."""
    art_dir = get_artifact_dir(ctx)
    target = art_dir / filename
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False, default=str) + "\n",
        encoding="utf-8",
    )
    return config.repo_relative(target)


def resolve_conversation_resource(
    app_name: str,
    session_id: str,
    ch_client: ConversationHistory | None = None,
) -> str:
    """Resolve and verify the persisted CES Conversation resource name for `session_id`."""
    canonical = f"{app_name}/conversations/{session_id}"
    if not session_id:
        return ""
    client = ch_client or ConversationHistory(app_name=app_name, transport="rest")
    try:
        conv_obj = client.get_conversation(session_id)
        if conv_obj and getattr(conv_obj, "name", ""):
            return str(conv_obj.name)
    except Exception:  # noqa: BLE001
        pass
    return canonical


def run_instrumented_probe(
    sim: SimulationEvals,
    probe: dict[str, Any],
    run_idx: int,
    *,
    modality: str = "text",
    judge_model: str = FAST_SIM_MODEL,
    now_dt: datetime | None = None,
    ch_client: ConversationHistory | None = None,
    use_tool_fakes: bool = False,
) -> dict[str, Any]:
    """Run a scripted multi-turn probe (text or audio) with per-turn latency measurement.

    Returns a dictionary matching the harness probe row format (`name`, `run`, `session_id`,
    `conversation_name`, `passed`, `duration_s`, `quota_wait_s`, `turn_count`, `turns`,
    `detailed_trace`, `expectation_details`, `error`, `modality`).
    """
    name = str(probe.get("name", "unnamed_probe"))
    raw_turns = list(probe.get("turns") or [])
    raw_expectations = list(probe.get("expectations") or [])
    expectations = (
        resolve_dynamic_expectations(raw_expectations, now_dt)
        if now_dt is not None
        else raw_expectations
    )
    raw_vars = probe.get("variables") or probe.get("session_parameters") or None
    if isinstance(raw_vars, dict):
        variables: dict[str, Any] | None = dict(raw_vars)
        if isinstance(variables.get("is_mock_mode"), str):
            variables["is_mock_mode"] = (
                variables["is_mock_mode"].strip().lower() == "true"
            )
    else:
        variables = None
    hist_ctx = probe.get("historical_contexts") or None

    session_id = sim.sessions_client.create_session_id()
    turns: list[dict[str, Any]] = []
    trace: list[str] = []
    start = time.monotonic()
    quota_wait = 0.0
    error_msg: str | None = None

    include_welcome = probe.get(
        "include_welcome", hist_ctx is None and modality == "text"
    )
    turn_sequence: list[Any] = ([None] if include_welcome else []) + raw_turns

    try:
        for idx, item in enumerate(turn_sequence):
            t0 = time.monotonic()
            turn_vars = variables if idx == 0 else None
            turn_hist = hist_ctx if idx == 0 else None

            if item is None:
                res, waited = with_quota_retry(
                    lambda v=turn_vars, h=turn_hist: sim.sessions_client.run(
                        session_id=session_id,
                        event="welcome",
                        variables=v,
                        historical_contexts=h,
                        modality=modality,
                        use_tool_fakes=use_tool_fakes,
                    ),
                    label=f"probe[{name}:welcome]",
                )
                user_label = "<welcome>"
                trace.append("User: <event>welcome</event>")
            else:
                if isinstance(item, dict):
                    line_text = str(item.get("text") or item.get("user") or "")
                    if item.get("variables"):
                        turn_vars = item["variables"]
                else:
                    line_text = str(item)
                res, waited = with_quota_retry(
                    lambda txt=line_text, v=turn_vars, h=turn_hist: sim.sessions_client.run(
                        session_id=session_id,
                        text=txt,
                        variables=v,
                        historical_contexts=h,
                        modality=modality,
                        use_tool_fakes=use_tool_fakes,
                    ),
                    label=f"probe[{name}:turn_{idx}]",
                )
                user_label = line_text
                trace.append(f"User: {line_text}")

            quota_wait += waited
            latency = max(0.0, time.monotonic() - t0 - waited)
            parsed = ParsedSessionResponse(res, tools_map=sim.tools_map)
            transfer = parsed.agent_transfer
            if transfer is not None and not isinstance(transfer, str):
                transfer = getattr(transfer, "display_name", None) or str(transfer)

            turns.append(
                {
                    "user": user_label,
                    "agent": parsed.agent_texts,
                    "tools": [
                        {"name": tc.name, "args": tc.args}
                        for tc in parsed.tool_calls
                    ],
                    "tool_responses": [
                        {"name": tr.name, "response": tr.response}
                        for tr in parsed.tool_responses
                    ],
                    "transfer": transfer,
                    "latency_s": round(latency, 2),
                    "session_ended": parsed.session_ended,
                }
            )
            trace.append(
                "\n".join(parsed.detailed_trace) or "Agent Text: <no response>"
            )
            if parsed.session_ended:
                break
    except Exception as exc:  # noqa: BLE001
        error_msg = f"{type(exc).__name__}: {exc}"

    duration_s = round(max(0.0, time.monotonic() - start - quota_wait), 2)
    conversation_name = resolve_conversation_resource(
        sim.app_name, session_id, ch_client=ch_client
    )

    details: list[dict[str, Any]] = []
    passed = error_msg is None
    if not error_msg and expectations:
        try:
            judged, waited = with_quota_retry(
                lambda: evaluate_expectations(
                    sim.genai_client, judge_model, trace, expectations
                ),
                label=f"judge[{name}]",
            )
            quota_wait += waited
            details = [
                {
                    "expectation": j.expectation,
                    "status": getattr(j.status, "value", str(j.status)),
                    "justification": j.justification,
                }
                for j in (judged or [])
            ]
            passed = len(details) == len(expectations) and all(
                d["status"] == "Met" for d in details
            )
        except Exception as judge_exc:  # noqa: BLE001
            error_msg = f"JudgeError: {type(judge_exc).__name__}: {judge_exc}"
            passed = False

    row: dict[str, Any] = {
        "name": name,
        "run": run_idx,
        "session_id": session_id,
        "conversation_name": conversation_name,
        "passed": passed,
        "duration_s": duration_s,
        "quota_wait_s": round(quota_wait, 2),
        "turn_count": len(turns),
        "turns": turns,
        "detailed_trace": trace,
        "expectation_details": details,
        "modality": modality,
        "tool_mode": "fake" if use_tool_fakes else "real",
    }
    if error_msg:
        row["error"] = error_msg
    return row


def grade_and_build_test_result(
    *,
    layer: str,
    test_id: str,
    repeat: int,
    row: dict[str, Any],
    expectations_count: int,
    now_dt: datetime,
    raw_artifact_path: str,
    app_name: str = DEFAULT_APP_NAME,
    modality: str = "text",
    is_simulation: bool = False,
    extra_metrics: dict[str, Any] | None = None,
    extra_findings: list[str] | None = None,
    override_checks: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Grade a probe or simulation row with `totto_suite.grader` and build a layer test entry."""
    if is_simulation:
        conv = grader.from_sim_row(row, modality=modality, source=layer)
    else:
        conv = grader.from_probe_row(row, source=layer)
        conv["modality"] = modality

    gctx: dict[str, Any] = {
        "now": now_dt.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "voice": modality == "audio",
        "expected_language": "auto",
    }
    det = grader.grade(conv, gctx)
    if override_checks:
        for chk in override_checks:
            chk_norm = {
                "name": chk.get("name") or chk.get("id") or "custom_check",
                "passed": bool(chk.get("passed", True)),
                "status": "pass" if chk.get("passed", True) else "fail",
                "turn_index": chk.get("turn_index"),
                "trace_index": chk.get("trace_index"),
                "evidence": chk.get("evidence") or "; ".join(chk.get("findings") or []),
                "findings": chk.get("findings") or [],
            }
            det["checks"].append(chk_norm)
            if not chk_norm["passed"]:
                det["passed"] = False

    row_error = row.get("error")
    judge = grader.judge_from_row(row, expected_expectations=expectations_count)
    status = grader.combine(
        det,
        judge,
        row_error=row_error,
        expectations_exist=expectations_count > 0,
    )

    findings: list[str] = []
    for f_chk in grader.failing(det):
        chk_name = f_chk.get("name") or f_chk.get("id") or "check"
        ev_text = f_chk.get("evidence") or ""
        f_tags = ", ".join(f_chk.get("findings") or [])
        tag_prefix = f"[{chk_name}:{f_tags}]" if f_tags else f"[{chk_name}]"
        findings.append(f"{tag_prefix} {ev_text}".strip())
    for exp_item in row.get("expectation_details") or []:
        if exp_item.get("status") not in ("Met", "MET", "met"):
            findings.append(
                f"[judge] NOT MET: {exp_item.get('expectation', '')} — "
                f"{exp_item.get('justification', '')}"
            )
    if row_error:
        findings.append(f"[error] {row_error}")
    if extra_findings:
        findings.extend(extra_findings)

    session_id = str(row.get("session_id") or "")
    conversation_name = str(
        row.get("conversation_name")
        or (f"{app_name}/conversations/{session_id}" if session_id else "")
    )
    platform_ids = {
        "session_id": session_id,
        "conversation": conversation_name,
    }

    agent_turns = [t for t in (conv.get("turns") or []) if t.get("role") == "agent"]
    latencies_s = [
        float(t["latency_s"])
        for t in agent_turns
        if t.get("latency_s") is not None and not t.get("greeting")
    ]
    metrics: dict[str, Any] = {
        "deterministic_passed": det["passed"],
        "deterministic_failed_checks": [
            c.get("name") or c.get("id") for c in grader.failing(det)
        ],
        "judge_passed": judge.get("passed") if judge else None,
        "turns_count": len(agent_turns),
    }
    if latencies_s:
        metrics["max_turn_latency_s"] = round(max(latencies_s), 2)
        metrics["mean_turn_latency_s"] = round(sum(latencies_s) / len(latencies_s), 2)
    if extra_metrics:
        metrics.update(extra_metrics)

    duration_s = round(float(row.get("duration_s") or 0.0), 2)
    msg = "; ".join(findings) if findings else "ok"

    return {
        "id": f"{layer}::{test_id}",
        "layer": layer,
        "repeat": repeat,
        "status": status,
        "duration_s": duration_s,
        "duration_ms": round(duration_s * 1000.0, 2),
        "message": msg,
        "findings": findings,
        "platform_ids": platform_ids,
        "evidence": raw_artifact_path,
        "raw_artifact_path": raw_artifact_path,
        "deterministic": det,
        "judge": judge,
        "metrics": metrics,
    }


def fetch_live_cxas_metadata(
    app_name: str = DEFAULT_APP_NAME,
    *,
    app_ref: str = "explicit",
    version_hint: str | None = None,
) -> dict[str, Any]:
    """Fetch target-app metadata for the Run Record `cxas` block (`CXAS_KEYS`).

    Everything comes from the target app at runtime. ``version_hint`` is the
    app version the platform actually evaluated (e.g. an EvaluationResult's
    ``app_version``); session-based layers run against the app draft, so
    without a hint the status is ``draft`` and ``version_id`` is empty.
    ``app`` holds only the ``app_ref`` (staging/live/explicit) so records carry
    no project or app identifiers.
    """
    from totto_suite import ids  # local import: ids imports config only

    meta: dict[str, Any] = {
        "app": app_ref,
        "version_id": "",
        "version_status": "draft",
        "model": "unknown",
        "app_update_time": None,
        "app_etag": "",
    }
    try:
        parsed = config.parse_app_name(app_name)
        app_obj = Apps(project_id=parsed["project"], location=parsed["location"]).get_app(
            app_name
        )
        ut = getattr(app_obj, "update_time", None)
        if ut:
            meta["app_update_time"] = (
                ut.isoformat().replace("+00:00", "Z") if hasattr(ut, "isoformat") else str(ut)
            )
        meta["app_etag"] = str(getattr(app_obj, "etag", "") or "")
        model = getattr(getattr(app_obj, "model_settings", None), "model", "") or ""
        if model:
            meta["model"] = str(model)
        meta["app_display_name"] = str(getattr(app_obj, "display_name", "") or "")
    except Exception as exc:  # noqa: BLE001
        meta["metadata_error"] = f"{type(exc).__name__}: {str(exc)[:200]}"

    if version_hint:
        rel = ids.relative_id("app_version", version_hint)
        meta["version_id"] = rel
        meta["version_status"] = "hidden_fetchable"
        try:
            from cxas_scrapi.core.versions import Versions

            listed = {
                ids.to_app_relative(str(v.name))
                for v in Versions(app_name=app_name).list_versions()
            }
            if rel in listed:
                meta["version_status"] = "in_version_list"
        except Exception as exc:  # noqa: BLE001
            meta["version_lookup_error"] = f"{type(exc).__name__}: {str(exc)[:200]}"
    return meta
