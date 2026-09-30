"""Local mutation testing harness for the Totto CXAS suite (`totto_suite mutants`).

Applies >=10 deterministic, synthetic defects across tools, callbacks, and agent
config in isolated temporary copies of `cxas_app/` (never modifying `<repo>/cxas_app/`
in-place) and verifies that every mutant flips at least one offline test scenario
from `PASS` on the unmodified app to `FAIL` (100% kill rate).
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
import tempfile
import time
from typing import Any, Callable

from totto_suite import config
from totto_suite import layers as layers_pkg
from totto_suite.taxonomy import Status


MutatorFn = Callable[[Path], None]


@dataclass(frozen=True)
class MutantSpec:
    """Specification of a single local defect injection against a copy of `cxas_app/`."""

    mutant_id: str
    category: str  # "tools" | "callbacks" | "config"
    taxonomy_ids: tuple[str, ...]
    target_files: tuple[str, ...]
    layers_to_run: tuple[str, ...]
    description: str
    mutate: MutatorFn


def _replace_once(file_path: Path, old: str, new: str) -> None:
    text = file_path.read_text(encoding="utf-8")
    if old not in text:
        raise ValueError(f"Expected target snippet not found in {file_path}: {old!r}")
    file_path.write_text(text.replace(old, new, 1), encoding="utf-8")


# ---------------------------------------------------------------------------
# Tool mutants (5)
# ---------------------------------------------------------------------------


def _mutate_tr08_standings_both_alias(app_dir: Path) -> None:
    """TR-08: Drop 'both' category alias in get_driver_standings."""
    target = app_dir / "tools" / "get_driver_standings" / "python_function" / "python_code.py"
    _replace_once(
        target,
        '    "both": "all",\n',
        "",
    )


def _mutate_tb03_unknown_race_fallback(app_dir: Path) -> None:
    """TB-3: Silently fall back to meetings[0] on unknown race query instead of returning None/error."""
    target = app_dir / "tools" / "get_race_schedule" / "python_function" / "python_code.py"
    _replace_once(
        target,
        "                    if f_stripped and (\n"
        "                        f_stripped in q_stripped or q_stripped in f_stripped\n"
        "                    ):\n"
        "                        return m\n"
        "        return None",
        "                    if f_stripped and (\n"
        "                        f_stripped in q_stripped or q_stripped in f_stripped\n"
        "                    ):\n"
        "                        return m\n"
        "        return meetings[0] if meetings else None",
    )


def _mutate_tr10_broken_timezone_dst(app_dir: Path) -> None:
    """TR-10: Skip UTC-to-local ZoneInfo conversion so local session times stay in UTC."""
    target = app_dir / "tools" / "get_race_schedule" / "python_function" / "python_code.py"
    _replace_once(
        target,
        "dt_local = dt_utc.astimezone(tz_obj)",
        "dt_local = dt_utc",
    )


def _mutate_rc01_missing_merch_store_link(app_dir: Path) -> None:
    """RC-01: Corrupt official merch store URL and drop 'store'/'shop' aliases in get_official_links."""
    target = app_dir / "tools" / "get_official_links" / "python_function" / "python_code.py"
    _replace_once(
        target,
        '"url": "https://shop.mercedesamgf1.com",',
        '"url": "https://invalid.example.com/broken-merch-store",',
    )
    _replace_once(
        target,
        '    "store": "merch",\n    "shop": "merch",\n',
        "",
    )


def _mutate_tr09_missing_freshness_disclaimer(app_dir: Path) -> None:
    """TR-09 / TB-1: Blank out freshness_disclaimer and data_source provenance in get_race_schedule."""
    target = app_dir / "tools" / "get_race_schedule" / "python_function" / "python_code.py"
    _replace_once(
        target,
        '        "data_source": data_source,\n'
        '        "freshness_disclaimer": (\n'
        '            "Race schedule, session times, and weather reflect the latest available structured "\n'
        '            "2026 season data from OpenF1 rather than live lap-by-lap telemetry."\n'
        '        ),',
        '        "data_source": "unknown",\n'
        '        "freshness_disclaimer": "",',
    )


# ---------------------------------------------------------------------------
# Callback mutants (2)
# ---------------------------------------------------------------------------


def _mutate_cb_order_id_regex(app_dir: Path) -> None:
    """TR-01 / PRD-AC5: Break ORDER_ID_PATTERN in init_session_state so order IDs are never extracted."""
    target = (
        app_dir
        / "agents"
        / "totto_root_agent"
        / "before_agent_callbacks"
        / "init_session_state"
        / "python_code.py"
    )
    _replace_once(
        target,
        'ORDER_ID_PATTERN = re.compile(\n'
        '    r"(?:#((?:ORD-)?\\d{4,8})\\b|\\b(?:order|commande|pedido|bestellung|bestellnummer)\\b(?:\\s+(?:number|num|no\\.?|n[úu]mero|nr\\.?|ist|is))?\\s*:?\\s*#?(\\d{4,8}|ORD-\\d{4,8})\\b)",\n'
        '    re.IGNORECASE,\n'
        ')',
        'ORDER_ID_PATTERN = re.compile(r"^NEVER_MATCH_ORDER_ID_999999$")',
    )


def _mutate_cb_sync_race_state_noop(app_dir: Path) -> None:
    """TR-10 / PRD-AC7: Short-circuit sync_race_state after-tool callback so timezone/race state never persists."""
    target = (
        app_dir
        / "agents"
        / "race_info_agent"
        / "after_tool_callbacks"
        / "sync_race_state"
        / "python_code.py"
    )
    _replace_once(
        target,
        "def after_tool_callback(\n"
        "    tool: Tool,\n"
        "    input: dict[str, Any],\n"
        "    callback_context: CallbackContext,\n"
        "    tool_response: dict[str, Any],\n"
        ") -> Optional[dict[str, Any]]:\n",
        "def after_tool_callback(\n"
        "    tool: Tool,\n"
        "    input: dict[str, Any],\n"
        "    callback_context: CallbackContext,\n"
        "    tool_response: dict[str, Any],\n"
        ") -> Optional[dict[str, Any]]:\n"
        "    return None\n",
    )


# ---------------------------------------------------------------------------
# Agent Config / Prompt / Schema mutants (4)
# ---------------------------------------------------------------------------


def _mutate_tr01_prompt_stuffed_example(app_dir: Path) -> None:
    """TR-01: Inject hardcoded tracking ID DHL-9928174 and literal eval probe prompt into merch_support_agent instruction."""
    target = app_dir / "agents" / "merch_support_agent" / "instruction.txt"
    text = target.read_text(encoding="utf-8")
    injected_example = (
        "\n<example>\n"
        "User: My cap from order 1001 arrived damaged. Here's my card number 4111 1111 1111 1111 so you can charge express shipping on the replacement.\n"
        "Agent: Your replacement tracking number is DHL-9928174.\n"
        "</example>\n</examples>"
    )
    if "</examples>" not in text:
        raise ValueError(f"Expected </examples> tag in {target}")
    target.write_text(text.replace("</examples>", injected_example, 1), encoding="utf-8")


def _mutate_tr02_speak_phrase_in_tool_desc(app_dir: Path) -> None:
    """TR-02 / TR-03: Add 'Speak a conversational pacing phrase before calling' to tool description & docstring and drop Zero Raw Code rule."""
    tool_json_path = app_dir / "tools" / "get_race_schedule" / "get_race_schedule.json"
    tool_json = json.loads(tool_json_path.read_text(encoding="utf-8"))
    tool_json["description"] = (
        tool_json.get("description", "")
        + " Speak a conversational pacing phrase before calling this tool."
    )
    tool_json_path.write_text(json.dumps(tool_json, indent=2) + "\n", encoding="utf-8")

    py_path = app_dir / "tools" / "get_race_schedule" / "python_function" / "python_code.py"
    _replace_once(
        py_path,
        "Fetches Formula 1 race schedule, session times, weather forecast, and Mercedes context.",
        "Fetches Formula 1 race schedule, session times, weather forecast, and Mercedes context. Speak a conversational pacing phrase before calling.",
    )

    global_inst = app_dir / "global_instruction.txt"
    _replace_once(
        global_inst,
        "Zero Raw Code in Responses",
        "Tool Invocation Guideline",
    )


def _mutate_rc02_toto_impersonation_and_drop(app_dir: Path) -> None:
    """RC-02 / RC-10 / TR-04: Revert root & merch instructions to iteration_3 regression (dropping Toto Wolff non-impersonation, live human escalation, and mock order disclosure) and drop Multilingual Continuity."""
    iter3_root = (
        config.REPO_ROOT
        / "evals"
        / "results"
        / "snapshots"
        / "iteration_3"
        / "cxas_app"
        / "agents"
    )
    iter3_totto = iter3_root / "totto_root_agent" / "instruction.txt"
    iter3_merch = iter3_root / "merch_support_agent" / "instruction.txt"
    if iter3_totto.exists() and iter3_merch.exists():
        shutil.copyfile(
            iter3_totto,
            app_dir / "agents" / "totto_root_agent" / "instruction.txt",
        )
        shutil.copyfile(
            iter3_merch,
            app_dir / "agents" / "merch_support_agent" / "instruction.txt",
        )
    else:
        merch_inst = app_dir / "agents" / "merch_support_agent" / "instruction.txt"
        text = merch_inst.read_text(encoding="utf-8")
        text = text.replace("simulated", "real").replace("mock", "live")
        merch_inst.write_text(text, encoding="utf-8")

    global_inst = app_dir / "global_instruction.txt"
    _replace_once(
        global_inst,
        "Multilingual Continuity",
        "Language Preference",
    )


def _mutate_rc11_invalid_app_schema(app_dir: Path) -> None:
    """RC-11: Inject invalid schema field and broken rootAgent in app.json plus nonexistent {@TOOL: ...} reference."""
    app_json_path = app_dir / "app.json"
    app_data = json.loads(app_json_path.read_text(encoding="utf-8"))
    app_data["unknownInvalidSchemaField"] = True
    app_data["rootAgent"] = "nonexistent_root_agent"
    app_json_path.write_text(json.dumps(app_data, indent=2) + "\n", encoding="utf-8")

    root_inst = app_dir / "agents" / "totto_root_agent" / "instruction.txt"
    root_text = root_inst.read_text(encoding="utf-8")
    root_inst.write_text(
        root_text + "\nAlways invoke {@TOOL: nonexistent_ghost_tool} first.\n",
        encoding="utf-8",
    )


# ---------------------------------------------------------------------------
# Shared-code bundle / voice-output mutants (4)
# ---------------------------------------------------------------------------


def _mutate_bundle_persona_drift(app_dir: Path) -> None:
    """F9: Hand-edit one agent's bundled <persona> copy (re-bolding the driver names, as happened before R5)."""
    target = app_dir / "agents" / "race_info_agent" / "instruction.txt"
    _replace_once(
        target,
        "George Russell in car 63 and Kimi Antonelli in car 12",
        "**George Russell** `#63` and **Kimi Antonelli** `#12`",
    )


def _mutate_bundle_openf1_helper_drift(app_dir: Path) -> None:
    """F9: Change the bundled OpenF1 HTTP helper in only one of the two tools (timeout 2s -> 30s)."""
    target = app_dir / "tools" / "get_driver_standings" / "python_function" / "python_code.py"
    _replace_once(
        target,
        "    with urllib.request.urlopen(req, timeout=2) as resp:\n",
        "    with urllib.request.urlopen(req, timeout=30) as resp:\n",
    )


def _mutate_voice_guidelines_dropped(app_dir: Path) -> None:
    """F10 / RC-06: Delete the shared voice <guidelines> block from global_instruction.txt."""
    target = app_dir / "global_instruction.txt"
    text = target.read_text(encoding="utf-8")
    start, end = text.find("<guidelines>"), text.find("</guidelines>")
    if start < 0 or end < start:
        raise ValueError(f"Expected <guidelines> block in {target}")
    target.write_text(text[:start] + text[end + len("</guidelines>") :], encoding="utf-8")


def _mutate_voice_sanitizer_noop(app_dir: Path) -> None:
    """F10 / RC-07: Short-circuit merch_support_agent's voice_sanitizer after_model_callback."""
    target = (
        app_dir
        / "agents"
        / "merch_support_agent"
        / "after_model_callbacks"
        / "voice_sanitizer"
        / "python_code.py"
    )
    _replace_once(
        target,
        ") -> Optional[LlmResponse]:\n    try:\n",
        ") -> Optional[LlmResponse]:\n    return None\n    try:\n",
    )


def _mutate_repetitive_boilerplate_mantra(app_dir: Path) -> None:
    """NEW-2 / RC-06: Re-introduce repetitive 'According to the latest-available 2026 data' and self-intro in race_info_agent <examples>."""
    target = app_dir / "agents" / "race_info_agent" / "instruction.txt"
    _replace_once(
        target,
        'Agent: "Next up on the 2026 calendar is the <RACE_NAME_FROM_TOOL>',
        'Agent: "Hello! I am Totto, Mercedes F1 Fan Agent. According to the latest-available 2026 data, next up is the <RACE_NAME_FROM_TOOL>',
    )
    _replace_once(
        target,
        'Agent: "For <USER_CITY_FROM_TOOL>, qualifying on Saturday',
        'Agent: "I am Totto, Mercedes F1 Fan Agent! According to the latest-available 2026 data, for <USER_CITY_FROM_TOOL>, qualifying on Saturday',
    )


MUTANT_SPECS: tuple[MutantSpec, ...] = (
    # Tools (5)
    MutantSpec(
        mutant_id="mutant_tr08_standings_both_alias",
        category="tools",
        taxonomy_ids=("TR-08",),
        target_files=("tools/get_driver_standings/python_function/python_code.py",),
        layers_to_run=("tools",),
        description="Remove 'both' -> 'all' category alias from get_driver_standings so category='both' raises an invalid category error.",
        mutate=_mutate_tr08_standings_both_alias,
    ),
    MutantSpec(
        mutant_id="mutant_tb03_unknown_race_fallback",
        category="tools",
        taxonomy_ids=("TB-3",),
        target_files=("tools/get_race_schedule/python_function/python_code.py",),
        layers_to_run=("tools",),
        description="Fall back to meetings[0] (Australian GP) when _select_meeting receives an unknown race query instead of returning None/UNKNOWN_RACE.",
        mutate=_mutate_tb03_unknown_race_fallback,
    ),
    MutantSpec(
        mutant_id="mutant_tr10_broken_timezone_dst",
        category="tools",
        taxonomy_ids=("TR-10",),
        target_files=("tools/get_race_schedule/python_function/python_code.py",),
        layers_to_run=("tools",),
        description="Bypass dt_utc.astimezone(tz_obj) in get_race_schedule so local_start stays in UTC across DST and timezone conversions.",
        mutate=_mutate_tr10_broken_timezone_dst,
    ),
    MutantSpec(
        mutant_id="mutant_rc01_missing_merch_store_link",
        category="tools",
        taxonomy_ids=("RC-01",),
        target_files=("tools/get_official_links/python_function/python_code.py",),
        layers_to_run=("tools",),
        description="Replace official https://shop.mercedesamgf1.com URL with broken URL and remove 'store'/'shop' aliases in get_official_links.",
        mutate=_mutate_rc01_missing_merch_store_link,
    ),
    MutantSpec(
        mutant_id="mutant_tr09_missing_freshness_disclaimer",
        category="tools",
        taxonomy_ids=("TR-09", "TB-1"),
        target_files=("tools/get_race_schedule/python_function/python_code.py",),
        layers_to_run=("tools",),
        description="Remove freshness_disclaimer text and overwrite data_source provenance in get_race_schedule responses.",
        mutate=_mutate_tr09_missing_freshness_disclaimer,
    ),
    # Callbacks (2)
    MutantSpec(
        mutant_id="mutant_cb_order_id_regex",
        category="callbacks",
        taxonomy_ids=("TR-01", "PRD-AC5"),
        target_files=(
            "agents/totto_root_agent/before_agent_callbacks/init_session_state/python_code.py",
        ),
        layers_to_run=("callbacks",),
        description="Break ORDER_ID_PATTERN regex in init_session_state so order IDs (ORD-xxxx, 1001-1005) are never extracted into session state.",
        mutate=_mutate_cb_order_id_regex,
    ),
    MutantSpec(
        mutant_id="mutant_cb_sync_race_state_noop",
        category="callbacks",
        taxonomy_ids=("TR-10", "PRD-AC7"),
        target_files=(
            "agents/race_info_agent/after_tool_callbacks/sync_race_state/python_code.py",
        ),
        layers_to_run=("callbacks",),
        description="Short-circuit sync_race_state after_tool_callback to return None without persisting resolved user_timezone or last_queried_race.",
        mutate=_mutate_cb_sync_race_state_noop,
    ),
    # Agent Config (4)
    MutantSpec(
        mutant_id="mutant_tr01_prompt_stuffed_example",
        category="config",
        taxonomy_ids=("TR-01",),
        target_files=("agents/merch_support_agent/instruction.txt",),
        layers_to_run=("config",),
        description="Inject hardcoded tracking number DHL-9928174 and literal eval probe user prompt into merch_support_agent <examples>.",
        mutate=_mutate_tr01_prompt_stuffed_example,
    ),
    MutantSpec(
        mutant_id="mutant_tr02_speak_phrase_in_tool_desc",
        category="config",
        taxonomy_ids=("TR-02", "TR-03"),
        target_files=(
            "tools/get_race_schedule/get_race_schedule.json",
            "tools/get_race_schedule/python_function/python_code.py",
            "global_instruction.txt",
        ),
        layers_to_run=("config", "tools"),
        description="Add 'Speak a conversational pacing phrase before calling' to get_race_schedule description/docstring and drop Zero Raw Code rule.",
        mutate=_mutate_tr02_speak_phrase_in_tool_desc,
    ),
    MutantSpec(
        mutant_id="mutant_rc02_toto_impersonation_and_drop",
        category="config",
        taxonomy_ids=("RC-02", "RC-10", "TR-04"),
        target_files=(
            "agents/totto_root_agent/instruction.txt",
            "agents/merch_support_agent/instruction.txt",
            "global_instruction.txt",
        ),
        layers_to_run=("config",),
        description="Overlay iteration_3 instruction regression (dropping Toto Wolff non-impersonation, live human escalation, and mock order disclosure) and remove Multilingual Continuity.",
        mutate=_mutate_rc02_toto_impersonation_and_drop,
    ),
    MutantSpec(
        mutant_id="mutant_rc11_invalid_app_schema",
        category="config",
        taxonomy_ids=("RC-11",),
        target_files=(
            "app.json",
            "agents/totto_root_agent/instruction.txt",
        ),
        layers_to_run=("lint", "config"),
        description="Add unknownInvalidSchemaField and broken rootAgent to app.json and reference nonexistent_ghost_tool in totto_root_agent instruction.",
        mutate=_mutate_rc11_invalid_app_schema,
    ),
    # Shared-code bundle / voice output (5)
    MutantSpec(
        mutant_id="mutant_bundle_persona_drift",
        category="config",
        taxonomy_ids=("F9",),
        target_files=("agents/race_info_agent/instruction.txt",),
        layers_to_run=("config",),
        description="Hand-edit race_info_agent's bundled <persona> copy (bold driver names + #63/#12) so it drifts from lib/shared_prompts/persona.txt.",
        mutate=_mutate_bundle_persona_drift,
    ),
    MutantSpec(
        mutant_id="mutant_bundle_openf1_helper_drift",
        category="tools",
        taxonomy_ids=("F9", "TB-1"),
        target_files=("tools/get_driver_standings/python_function/python_code.py",),
        layers_to_run=("config", "tools"),
        description="Change the bundled OpenF1 HTTP helper timeout (2s -> 30s) in get_driver_standings only, so the copy drifts from lib/shared_python/openf1_http.py.",
        mutate=_mutate_bundle_openf1_helper_drift,
    ),
    MutantSpec(
        mutant_id="mutant_voice_guidelines_dropped",
        category="config",
        taxonomy_ids=("F10", "RC-06", "RC-07", "NEW-2"),
        target_files=("global_instruction.txt",),
        layers_to_run=("config",),
        description="Delete the shared voice <guidelines> block (plain text, no raw URLs, 2-3 sentence budget, spoken numbers) from global_instruction.txt.",
        mutate=_mutate_voice_guidelines_dropped,
    ),
    MutantSpec(
        mutant_id="mutant_voice_sanitizer_noop",
        category="callbacks",
        taxonomy_ids=("F10", "RC-06", "RC-07"),
        target_files=("agents/merch_support_agent/after_model_callbacks/voice_sanitizer/python_code.py",),
        layers_to_run=("callbacks", "config"),
        description="Make merch_support_agent's voice_sanitizer after_model_callback return None before cleaning, so markdown/emoji/https:// reach TTS.",
        mutate=_mutate_voice_sanitizer_noop,
    ),
    MutantSpec(
        mutant_id="mutant_repetitive_boilerplate_mantra",
        category="config",
        taxonomy_ids=("NEW-2", "RC-06"),
        target_files=("agents/race_info_agent/instruction.txt",),
        layers_to_run=("config",),
        description="Re-introduce repetitive 'According to the latest-available 2026 data' and self-introduction across consecutive turns in race_info_agent <examples>.",
        mutate=_mutate_repetitive_boilerplate_mantra,
    ),
)


def _offline_layer_map() -> dict[str, layers_pkg.LayerModule]:
    return {m.name: m for m in layers_pkg.discover("offline")}


def _run_selected_offline_layers(
    app_dir: Path,
    repo_root: Path,
    layer_names: tuple[str, ...],
) -> dict[str, dict[str, Any]]:
    """Run selected offline layer modules against `app_dir` and return `{id: result_dict}`."""
    mod_map = _offline_layer_map()
    scenarios: dict[str, dict[str, Any]] = {}
    with tempfile.TemporaryDirectory(prefix="totto_mutant_artifacts_") as art_dir:
        ctx = {
            "repo_root": str(repo_root),
            "app_dir": str(app_dir),
            "mode": "offline",
            "run_id": "mutant_eval",
            "artifacts_dir": art_dir,
            "repeats": 1,
            "now": None,
            "app_name": config.app_name(),
        }
        for name in layer_names:
            mod = mod_map.get(name)
            if mod is None:
                raise KeyError(f"Offline layer module {name!r} not found in {list(mod_map)}")
            outcome = layers_pkg.run_layer(mod, ctx)
            if outcome.crashed:
                raise RuntimeError(
                    f"Layer {mod.module} crashed on {app_dir}:\n{outcome.error}"
                )
            for item in outcome.results:
                scenarios[str(item["id"])] = item
    return scenarios


def _collect_baseline_scenarios(
    source_app_dir: Path,
    repo_root: Path,
    layers: tuple[str, ...] = ("lint", "config", "callbacks", "tools"),
) -> dict[str, dict[str, Any]]:
    """Run offline layers on a clean temporary copy of `source_app_dir`."""
    with tempfile.TemporaryDirectory(prefix="totto_mutant_baseline_") as tmp_dir:
        clean_copy = Path(tmp_dir) / "cxas_app"
        shutil.copytree(source_app_dir, clean_copy)
        return _run_selected_offline_layers(clean_copy, repo_root, layers)


def run_mutant_spec(
    spec: MutantSpec,
    *,
    source_app_dir: Path,
    repo_root: Path,
    baseline_scenarios: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    """Execute one mutant in an isolated temporary directory and compare against baseline."""
    start = time.monotonic()
    with tempfile.TemporaryDirectory(prefix=f"totto_{spec.mutant_id}_") as tmp_dir:
        mutant_app_dir = Path(tmp_dir) / "cxas_app"
        shutil.copytree(source_app_dir, mutant_app_dir)
        spec.mutate(mutant_app_dir)
        mutant_scenarios = _run_selected_offline_layers(
            mutant_app_dir, repo_root, spec.layers_to_run
        )

    duration_sec = round(time.monotonic() - start, 3)

    killed_by_scenarios: list[str] = []
    failure_details: list[dict[str, Any]] = []

    for scenario_id, mutant_res in sorted(mutant_scenarios.items()):
        base_res = baseline_scenarios.get(scenario_id)
        base_status = base_res["status"] if base_res is not None else Status.PASS.value
        mutant_status = mutant_res["status"]
        if base_status == Status.PASS.value and mutant_status == Status.FAIL.value:
            killed_by_scenarios.append(scenario_id)
            failure_details.append(
                {
                    "scenario_id": scenario_id,
                    "layer": mutant_res["layer"],
                    "baseline_verdict": base_status,
                    "mutant_verdict": mutant_status,
                    "failure_reason": (mutant_res.get("message") or "")[:600],
                    "findings": list(mutant_res.get("findings") or []),
                }
            )

    return {
        "mutant_id": spec.mutant_id,
        "category": spec.category,
        "taxonomy_ids": list(spec.taxonomy_ids),
        "target_files": list(spec.target_files),
        "layers_checked": list(spec.layers_to_run),
        "description": spec.description,
        "killed": len(killed_by_scenarios) > 0,
        "killed_by_count": len(killed_by_scenarios),
        "killed_by_scenarios": killed_by_scenarios,
        "failure_details": failure_details,
        "duration_sec": duration_sec,
    }


def run_all_mutants(
    *,
    source_app_dir: Path | None = None,
    repo_root: Path | None = None,
    specs: tuple[MutantSpec, ...] = MUTANT_SPECS,
    write_reports: bool = True,
) -> dict[str, Any]:
    """Run all configured mutants in isolated temp copies and optionally write reports."""
    repo_root_path = Path(repo_root).resolve() if repo_root else config.REPO_ROOT
    app_dir_path = Path(source_app_dir).resolve() if source_app_dir else config.app_dir()
    needed_layers: list[str] = []
    for spec in specs:
        for layer_id in spec.layers_to_run:
            if layer_id not in needed_layers:
                needed_layers.append(layer_id)

    baseline_start = time.monotonic()
    baseline_scenarios = _collect_baseline_scenarios(
        app_dir_path,
        repo_root_path,
        layers=tuple(needed_layers),
    )
    baseline_duration = round(time.monotonic() - baseline_start, 3)

    baseline_total = len(baseline_scenarios)
    baseline_passed = sum(
        1 for s in baseline_scenarios.values() if s["status"] == Status.PASS.value
    )
    baseline_failed = sum(
        1 for s in baseline_scenarios.values() if s["status"] == Status.FAIL.value
    )

    mutant_results: list[dict[str, Any]] = []
    for spec in specs:
        res = run_mutant_spec(
            spec,
            source_app_dir=app_dir_path,
            repo_root=repo_root_path,
            baseline_scenarios=baseline_scenarios,
        )
        mutant_results.append(res)

    total_mutants = len(mutant_results)
    killed_mutants = sum(1 for r in mutant_results if r["killed"])
    survived_mutants = total_mutants - killed_mutants
    kill_rate = round(killed_mutants / total_mutants, 4) if total_mutants else 0.0

    by_category: dict[str, dict[str, int]] = {}
    for r in mutant_results:
        cat = r["category"]
        bucket = by_category.setdefault(cat, {"total": 0, "killed": 0, "survived": 0})
        bucket["total"] += 1
        if r["killed"]:
            bucket["killed"] += 1
        else:
            bucket["survived"] += 1

    report: dict[str, Any] = {
        "schema_version": "1.0",
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source_app_dir": config.repo_relative(app_dir_path),
        "baseline_summary": {
            "layers": needed_layers,
            "total_scenarios": baseline_total,
            "passed": baseline_passed,
            "failed": baseline_failed,
            "duration_sec": baseline_duration,
        },
        "summary": {
            "total_mutants": total_mutants,
            "killed": killed_mutants,
            "survived": survived_mutants,
            "kill_rate": kill_rate,
            "by_category": by_category,
        },
        "mutants": mutant_results,
    }

    if write_reports:
        out_dir = repo_root_path / "evals" / "history" / "mutants"
        out_dir.mkdir(parents=True, exist_ok=True)
        json_path = out_dir / "mutants_report.json"
        md_path = out_dir / "mutants_report.md"
        json_path.write_text(
            json.dumps(report, indent=2, sort_keys=False) + "\n",
            encoding="utf-8",
        )
        md_path.write_text(render_mutants_markdown(report), encoding="utf-8")

    return report


def render_mutants_markdown(report: dict[str, Any]) -> str:
    """Render a human-readable Markdown summary of the mutation testing report."""
    summary = report["summary"]
    base = report["baseline_summary"]
    lines: list[str] = [
        "# Totto CXAS Offline Suite — Mutation Testing Report",
        "",
        f"- **Generated at**: `{report['generated_at']}`",
        f"- **Baseline (`{report['source_app_dir']}`)**: `{base['passed']}/{base['total_scenarios']}` passing across `{', '.join(base['layers'])}` (`{base['failed']}` failed, `{base['duration_sec']}s`)",
        f"- **Mutants Killed**: **`{summary['killed']}/{summary['total_mutants']}` (`{summary['kill_rate'] * 100:.1f}%`)**",
        "",
        "## Kill Rate by Category",
        "",
        "| Category | Killed | Total | Kill Rate |",
        "|---|---:|---:|---:|",
    ]
    for cat, stats in sorted(summary["by_category"].items()):
        rate = (stats["killed"] / stats["total"] * 100.0) if stats["total"] else 0.0
        lines.append(
            f"| `{cat}` | {stats['killed']} | {stats['total']} | {rate:.1f}% |"
        )

    lines.extend(
        [
            "",
            "## Mutant Matrix (`PASS -> FAIL` Verification)",
            "",
            "| # | Mutant ID | Category | Taxonomy | Target File(s) | Status | Flipped (`PASS -> FAIL`) Scenarios |",
            "|---:|---|---|---|---|---|---|",
        ]
    )

    for idx, m in enumerate(report["mutants"], start=1):
        status = "KILLED" if m["killed"] else "SURVIVED"
        tax = ", ".join(f"`{t}`" for t in m["taxonomy_ids"])
        files = ", ".join(f"`{f}`" for f in m["target_files"])
        scenarios_preview = ", ".join(f"`{s}`" for s in m["killed_by_scenarios"][:3])
        if len(m["killed_by_scenarios"]) > 3:
            scenarios_preview += f" (+{len(m['killed_by_scenarios']) - 3} more)"
        lines.append(
            f"| {idx} | `{m['mutant_id']}` | `{m['category']}` | {tax} | {files} | **{status}** ({m['killed_by_count']}) | {scenarios_preview} |"
        )

    lines.extend(["", "## Detailed Mutant Breakdown", ""])
    for idx, m in enumerate(report["mutants"], start=1):
        lines.extend(
            [
                f"### {idx}. `{m['mutant_id']}` ({m['category'].upper()} — {', '.join(m['taxonomy_ids'])})",
                f"- **Description**: {m['description']}",
                f"- **Target Files**: {', '.join(f'`{f}`' for f in m['target_files'])}",
                f"- **Layers Checked**: {', '.join(f'`{l}`' for l in m['layers_checked'])} (`{m['duration_sec']}s`)",
                f"- **Result**: **{'KILLED' if m['killed'] else 'SURVIVED'}** (`{m['killed_by_count']}` scenarios flipped `PASS -> FAIL`)",
                "- **Scenarios Flipped `PASS -> FAIL`**:",
            ]
        )
        for s in m["killed_by_scenarios"]:
            lines.append(f"  - `{s}`")
        lines.append("")

    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="totto_suite mutants",
        description="Run >=10 local mutants in temp copies of cxas_app and verify 100% kill rate.",
    )
    parser.add_argument(
        "--app-dir",
        type=Path,
        default=None,
        help="Optional baseline cxas_app directory (defaults to <repo>/cxas_app).",
    )
    parser.add_argument(
        "--no-write",
        action="store_true",
        help="Do not write evals/history/mutants/mutants_report.{json,md}.",
    )
    args = parser.parse_args(argv)

    app_dir_path = args.app_dir.resolve() if args.app_dir else config.app_dir()
    print(f"[mutants] Running {len(MUTANT_SPECS)} local mutants in isolated temp copies...")
    report = run_all_mutants(
        source_app_dir=app_dir_path,
        repo_root=config.REPO_ROOT,
        write_reports=not args.no_write,
    )
    summary = report["summary"]
    for m in report["mutants"]:
        badge = "KILLED" if m["killed"] else "SURVIVED"
        print(
            f"  - [{badge}] {m['mutant_id']} ({m['category']}, {', '.join(m['taxonomy_ids'])}): "
            f"{m['killed_by_count']} scenario(s) flipped PASS -> FAIL ({m['duration_sec']}s)"
        )
    print(
        f"[mutants] Summary: {summary['killed']}/{summary['total_mutants']} killed "
        f"({summary['kill_rate'] * 100:.1f}%)"
    )
    if not args.no_write:
        out_dir = config.HISTORY_DIR / "mutants"
        print(f"[mutants] Wrote {config.repo_relative(out_dir / 'mutants_report.json')}")
        print(f"[mutants] Wrote {config.repo_relative(out_dir / 'mutants_report.md')}")

    if summary["survived"] > 0 or summary["total_mutants"] < 8:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
