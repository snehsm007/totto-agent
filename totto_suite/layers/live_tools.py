"""Live layer: live_tools (ToolEvals + direct execute_tool defect/oracle probes)."""

from __future__ import annotations

import time
from typing import Any

from cxas_scrapi.evals.tool_evals import ToolEvals
from totto_suite import oracle
from totto_suite.live.runner import (
    DEFAULT_APP_NAME,
    is_quota_or_infra_error,
    resolve_now,
    save_layer_artifact,
    slugify,
    with_quota_retry,
)
from totto_suite.config import REPO_ROOT

LAYER = "live_tools"
TOOL_TESTS_YAML = REPO_ROOT / "evals" / "tool_tests" / "tool_tests.yaml"
OPENF1_FIXTURES = REPO_ROOT / "tests" / "fixtures" / "openf1"

# executeTool has no fake switch (ExecuteToolRequest only has args/variables/
# context/mockConfig), so every tool test here calls the REAL tool code on the
# platform: tool_mode is always "real" for this layer, whatever the run asked.
TOOL_MODE = "real"

# Probes whose purpose is to check the external OpenF1 API itself. A
# tool_mode=fake gate must not depend on OpenF1 (R2), so they are SKIPPED there.
EXTERNAL_API_PROBES = {"probe_tb1_openf1_live_reachable_in_cxas_sandbox"}


def _unwrap_result(resp: Any) -> dict[str, Any]:
    """Extract the inner dict from `execute_tool` response (`{"response": {"result": {...}}}` or direct dict)."""
    cur = resp
    if isinstance(cur, dict) and isinstance(cur.get("response"), dict):
        cur = cur["response"]
    if isinstance(cur, dict) and isinstance(cur.get("result"), dict):
        cur = cur["result"]
    return cur if isinstance(cur, dict) else {}


def _has_past_signal(res: dict[str, Any]) -> bool:
    for key, value in res.items():
        k = key.lower()
        if k in ("status", "agent_action"):
            continue
        if any(tok in k for tok in ("past", "complet", "finished", "concluded")):
            if isinstance(value, str):
                return value.strip().lower() in (
                    "true",
                    "yes",
                    "completed",
                    "past",
                    "finished",
                    "over",
                    "concluded",
                )
            return bool(value)
    action = str(res.get("agent_action", "")).upper()
    return any(tok in action for tok in ("PAST", "COMPLETED", "ALREADY"))


def resolve_tool_test_yaml(text: str, now_dt: Any, fixtures_dir: Any = OPENF1_FIXTURES) -> str:
    """Fills date-dependent placeholders in tool_tests.yaml from the oracle.

    ``{{NEXT_RACE_NAME}}`` / ``{{NEXT_RACE_LOCATION}}`` become the next race
    (by the captured OpenF1 calendar in tests/fixtures/openf1) at ``now``, so
    a ``race_query: next`` expectation never goes stale as the season moves.
    After the last race they become ``none remaining in 2026``, which no
    success payload contains (the case then fails loudly instead of lying).
    """
    if "{{NEXT_RACE_" not in text:
        return text
    meetings, sessions = oracle.load_calendar(fixtures_dir)
    nxt = oracle.next_race(meetings, now_dt, sessions)
    name = nxt["meeting_name"] if nxt else "none remaining in 2026"
    location = nxt["location"] if nxt else "none remaining in 2026"
    return text.replace("{{NEXT_RACE_NAME}}", name).replace("{{NEXT_RACE_LOCATION}}", location)


def run(ctx: dict[str, Any]) -> list[dict[str, Any]]:
    app_name = str(ctx.get("app_name") or DEFAULT_APP_NAME)
    now_dt = resolve_now(ctx)
    tool_evals = ToolEvals(app_name=app_name)
    tool_map = dict(tool_evals.tool_map or {})

    results: list[dict[str, Any]] = []
    raw_artifacts: list[dict[str, Any]] = []

    # 1. Execute all YAML tool test cases from evals/tool_tests/tool_tests.yaml
    yaml_cases = tool_evals.load_tool_test_cases_from_yaml(
        resolve_tool_test_yaml(TOOL_TESTS_YAML.read_text(encoding="utf-8"), now_dt)
    )
    for tc in yaml_cases:
        tool_resource = tool_map.get(tc.tool, f"{app_name}/tools/{tc.tool}")
        t0 = time.perf_counter()
        error_msg: str | None = None
        resp: Any = None
        validation_errors: list[str] = []
        try:
            resp, _ = with_quota_retry(
                lambda c=tc: tool_evals.tools_client.execute_tool(
                    tool_display_name=c.tool,
                    args=c.args,
                    variables=c.variables,
                    context=c.context,
                ),
                label=f"execute_tool[{tc.name}]",
            )
            validation_errors = tool_evals.validate_tool_test(tc, resp)
        except Exception as exc:  # noqa: BLE001
            error_msg = f"{type(exc).__name__}: {exc}"

        duration_ms = round((time.perf_counter() - t0) * 1000.0, 2)
        if error_msg and is_quota_or_infra_error(error_msg):
            status = "INFRA_ERROR"
        elif error_msg or validation_errors:
            status = "FAIL"
        else:
            status = "PASS"

        findings = list(validation_errors)
        if error_msg:
            findings.append(error_msg)

        art_entry = {
            "name": tc.name,
            "tool": tc.tool,
            "tool_resource": tool_resource,
            "args": tc.args,
            "response": resp,
            "validation_errors": validation_errors,
            "error": error_msg,
            "duration_ms": duration_ms,
        }
        raw_artifacts.append(art_entry)
        art_path = save_layer_artifact(
            ctx, f"live_tools/{slugify(tc.name)}.json", art_entry
        )

        results.append(
            {
                "id": f"{LAYER}::{slugify(tc.name)}",
                "layer": LAYER,
                "repeat": 1,
                "status": status,
                "duration_s": round(duration_ms / 1000.0, 3),
                "duration_ms": duration_ms,
                "message": "; ".join(findings) if findings else "ok",
                "platform_ids": {
                    "tool": tool_resource,
                },
                "tool_mode": TOOL_MODE,
                "fake_verified": False,
                "metrics": {
                    "tool_display_name": tc.tool,
                    "validation_errors_count": len(validation_errors),
                },
                "findings": findings,
                "evidence": art_path,
                "raw_artifact_path": art_path,
            }
        )

    # 2. Direct execute_tool probes for TB-1..TB-5, TR-08, TR-10, RC-01, and merch orders
    direct_probes: list[dict[str, Any]] = [
        {
            "id": "probe_tb1_tr09_schedule_data_source_label",
            "tool": "get_race_schedule",
            "args": {"race_query": "Singapore Grand Prix", "user_timezone": "UTC"},
            "check": lambda r: (
                (
                    r.get("status") == "success"
                    and bool(str(r.get("freshness_disclaimer", "")).strip())
                    and (
                        "snapshot" in str(r.get("data_source", "")).lower()
                        or "openf1" in str(r.get("data_source", "")).lower()
                    )
                ),
                f"[TB-1/TR-09] Unexpected data_source={r.get('data_source')!r} or missing freshness_disclaimer",
            ),
        },
        {
            "id": "probe_tb1_openf1_live_reachable_in_cxas_sandbox",
            "tool": "get_race_schedule",
            "args": {"race_query": "Azerbaijan Grand Prix", "user_timezone": "UTC"},
            "check": lambda r: (
                "live" in str(r.get("data_source", "")).lower()
                and str((r.get("typical_weather") or r.get("weather_forecast") or {}).get("source", "")).startswith("openf1"),
                f"[TB-1] CXAS sandbox fell back to static snapshot instead of live OpenF1 API: "
                f"data_source={r.get('data_source')!r}, weather_source={(r.get('typical_weather') or r.get('weather_forecast') or {}).get('source')!r}",
            ),
        },
        {
            "id": "probe_tb2_kuala_lumpur_openf1_meeting_1308",
            "tool": "get_race_schedule",
            "args": {"race_query": "Kuala Lumpur", "user_timezone": "UTC"},
            "check": lambda r: (
                r.get("status") == "error"
                and r.get("agent_action") == "CLARIFY_RACE_NAME"
                and r.get("meeting_key") != 1308,
                f"[TB-2] 'Kuala Lumpur' query returned status={r.get('status')!r}, "
                f"meeting_key={r.get('meeting_key')!r} instead of CLARIFY_RACE_NAME "
                "(mislabeled OpenF1 meeting 1308 'Bahrain Grand Prix' at Kuala Lumpur must be excluded)",
            ),
        },
        {
            "id": "probe_tb3_spain_substring_collision_with_spa",
            "tool": "get_race_schedule",
            "args": {"race_query": "Spain", "user_timezone": "Madrid"},
            "check": lambda r: (
                (
                    "Spain" in str(r.get("location", ""))
                    if r.get("status") == "success"
                    else r.get("agent_action") == "CLARIFY_RACE_NAME"
                ),
                f"[TB-3] 'Spain' query returned race_name={r.get('race_name')!r} in "
                f"location={r.get('location')!r} (substring 'spa' matched Belgium/Spa-Francorchamps)",
            ),
        },
        {
            "id": "probe_tb3_unknown_race_moon_gp",
            "tool": "get_race_schedule",
            "args": {"race_query": "Moon Grand Prix", "user_timezone": "UTC"},
            "check": lambda r: (
                r.get("status") == "error"
                and r.get("agent_action") == "CLARIFY_RACE_NAME"
                and "sessions" not in r,
                f"[TB-3] Unknown race 'Moon Grand Prix' did not return clean CLARIFY_RACE_NAME error: {r}",
            ),
        },
        {
            "id": "probe_tb4_future_weather_not_labelled_forecast",
            "tool": "get_race_schedule",
            "args": {"race_query": "Singapore Grand Prix", "user_timezone": "UTC"},
            "check": lambda r: (
                "weather_forecast" not in r,
                f"[TB-4] Static climatology profile is returned under key 'weather_forecast': "
                f"{r.get('weather_forecast')!r}, causing the model to present climatology as a live forecast",
            ),
        },
        {
            "id": "probe_tb5_tr08_past_race_completed_flag_british_gp",
            "tool": "get_race_schedule",
            "args": {"race_query": "British Grand Prix", "user_timezone": "Europe/London"},
            "check": lambda r: (
                r.get("status") == "success" and _has_past_signal(r),
                f"[TB-5/TR-08] Past race {r.get('race_name')!r} ({r.get('dates')!r}) has no "
                f"past/completed indicator field in tool output (keys={sorted(r.keys())})",
            ),
        },
    ]

    # TR-10 unseen non-F1 cities timezone resolution probes
    unseen_cities = [
        ("Toronto", "America/Toronto"),
        ("São Paulo", "America/Sao_Paulo"),
        ("Auckland", "Pacific/Auckland"),
        ("Vienna", "Europe/Vienna"),
        ("Mumbai", "Asia/Kolkata"),
        ("Edinburgh", "Europe/London"),
    ]
    for city, expected_iana in unseen_cities:
        direct_probes.append(
            {
                "id": f"probe_tr10_unseen_city_{slugify(city)}",
                "tool": "get_race_schedule",
                "args": {"race_query": "British Grand Prix", "user_timezone": city},
                "check": lambda r, c=city, exp=expected_iana: (
                    r.get("status") == "success"
                    and r.get("user_timezone_resolved") == exp
                    and r.get("needs_timezone_clarification") is False,
                    f"[TR-10] City {c!r} resolved to {r.get('user_timezone_resolved')!r} "
                    f"(expected {exp!r}, needs_timezone_clarification={r.get('needs_timezone_clarification')!r})",
                ),
            }
        )

    # RC-01 official merch store link & ticketing link probes
    direct_probes.append(
        {
            "id": "probe_rc01_official_merch_store_link",
            "tool": "get_official_links",
            "args": {"category": "merch"},
            "check": lambda r: (
                r.get("status") == "success"
                and isinstance(r.get("result"), dict)
                and r["result"].get("url") == "https://shop.mercedesamgf1.com",
                f"[RC-01] get_official_links(category='merch') returned {r.get('result')!r}",
            ),
        }
    )

    # Mock merch orders 1001, 1002, 1003, 9999, 123456
    merch_cases = [
        ("1001", True, "Delivered"),
        ("1002", True, "In Transit"),
        ("1003", True, "Return In Progress"),
        ("9999", False, None),
        ("123456", False, None),
    ]
    for oid, exp_found, exp_status in merch_cases:
        direct_probes.append(
            {
                "id": f"probe_merch_order_{oid}",
                "tool": "lookup_mock_merch_order",
                "args": {"order_id": oid},
                "check": lambda r, o=oid, f=exp_found, s=exp_status: (
                    (
                        r.get("found") is f
                        and r.get("is_mock_data") is True
                        and (
                            (r.get("status") == "success" and r.get("order", {}).get("status") == s)
                            if f
                            else (r.get("status") == "error" and "order" not in r)
                        )
                    ),
                    f"[AC-5] lookup_mock_merch_order({o!r}) returned unexpected payload: {r}",
                ),
            }
        )

    fake_run = str(ctx.get("tool_mode") or "real").lower() == "fake"
    for dp in direct_probes:
        t_name = dp["tool"]
        tool_resource = tool_map.get(t_name, f"{app_name}/tools/{t_name}")
        if fake_run and dp["id"] in EXTERNAL_API_PROBES:
            msg = (
                "SKIPPED in tool_mode=fake: this probe checks that the real OpenF1 API "
                "is reachable from the CXAS sandbox, which a fake-mode gate must not depend on"
            )
            results.append(
                {
                    "id": f"{LAYER}::{dp['id']}",
                    "layer": LAYER,
                    "repeat": 1,
                    "status": "SKIPPED",
                    "duration_s": 0.0,
                    "duration_ms": 0.0,
                    "message": msg,
                    "platform_ids": {"tool": tool_resource},
                    "tool_mode": TOOL_MODE,
                    "fake_verified": False,
                    "metrics": {"tool_display_name": t_name, "requires_external_api": True},
                    "findings": [],
                }
            )
            continue
        t0 = time.perf_counter()
        err_msg: str | None = None
        raw_resp: Any = None
        unwrapped: dict[str, Any] = {}
        passed = False
        finding_msg = ""

        try:
            raw_resp, _ = with_quota_retry(
                lambda p=dp: tool_evals.tools_client.execute_tool(
                    tool_display_name=p["tool"],
                    args=p["args"],
                ),
                label=f"execute_tool[{dp['id']}]",
            )
            unwrapped = _unwrap_result(raw_resp)
            passed, finding_msg = dp["check"](unwrapped)
        except Exception as exc:  # noqa: BLE001
            err_msg = f"{type(exc).__name__}: {exc}"

        duration_ms = round((time.perf_counter() - t0) * 1000.0, 2)
        if err_msg and is_quota_or_infra_error(err_msg):
            status = "INFRA_ERROR"
        elif err_msg or not passed:
            status = "FAIL"
        else:
            status = "PASS"

        findings = []
        if not passed and finding_msg:
            findings.append(finding_msg)
        if err_msg:
            findings.append(err_msg)

        art_entry = {
            "id": dp["id"],
            "tool": t_name,
            "tool_resource": tool_resource,
            "args": dp["args"],
            "now_utc": now_dt.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "response": raw_resp,
            "unwrapped": unwrapped,
            "passed": passed,
            "findings": findings,
            "duration_ms": duration_ms,
        }
        raw_artifacts.append(art_entry)
        art_path = save_layer_artifact(ctx, f"live_tools/{dp['id']}.json", art_entry)

        results.append(
            {
                "id": f"{LAYER}::{dp['id']}",
                "layer": LAYER,
                "repeat": 1,
                "status": status,
                "duration_s": round(duration_ms / 1000.0, 3),
                "duration_ms": duration_ms,
                "message": "; ".join(findings) if findings else "ok",
                "platform_ids": {
                    "tool": tool_resource,
                },
                "tool_mode": TOOL_MODE,
                "fake_verified": False,
                "metrics": {
                    "tool_display_name": t_name,
                    "tool_status": unwrapped.get("status"),
                    "requires_external_api": dp["id"] in EXTERNAL_API_PROBES,
                    "fake_marker_in_response": unwrapped.get("_fake") is True,
                },
                "findings": findings,
                "evidence": art_path,
                "raw_artifact_path": art_path,
            }
        )

    save_layer_artifact(ctx, "live_tools/summary.json", raw_artifacts)
    return results
