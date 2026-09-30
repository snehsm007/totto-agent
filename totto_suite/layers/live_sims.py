"""Live layer: live_sims (multi-turn simulations + scripted probes, parallel=1, repeats>=3)."""

from __future__ import annotations

from typing import Any
import yaml

from cxas_scrapi.core.conversation_history import ConversationHistory
from cxas_scrapi.evals.simulation_evals import SimulationEvals
from totto_suite.live.runner import (
    DEFAULT_APP_NAME,
    FAST_SIM_MODEL,
    grade_and_build_test_result,
    resolve_conversation_resource,
    resolve_dynamic_expectations,
    resolve_now,
    run_instrumented_probe,
    save_layer_artifact,
    slugify,
    use_tool_fakes,
    with_quota_retry,
)
from totto_suite.config import REPO_ROOT

LAYER = "live_sims"
SIMS_YAML = REPO_ROOT / "evals" / "simulations" / "simulations.yaml"
PROBES_YAML = REPO_ROOT / "evals" / "probes" / "probes.yaml"


CORE_SIM_NAMES = {
    "sim_ac1_ac7_next_race_and_timezone_clarification",
    "sim_ac2_mercedes_standings_priority",
    "sim_ac5_mock_merch_order_lookup_and_damaged_item",
}


def _load_simulations(now_dt: Any) -> list[dict[str, Any]]:
    data = yaml.safe_load(SIMS_YAML.read_text(encoding="utf-8")) or {}
    evals = data.get("evals", []) if isinstance(data, dict) else data
    common = data.get("common_expectations", []) if isinstance(data, dict) else []
    cases: list[dict[str, Any]] = []
    for ev in evals:
        name = str(ev.get("name", ""))
        if name not in CORE_SIM_NAMES:
            continue
        raw_exps = list(ev.get("expectations", [])) + list(common)
        exps = resolve_dynamic_expectations(raw_exps, now_dt)
        steps = []
        cap = 2 if "ac1" in name else 1
        for st in ev.get("steps", []):
            st_copy = dict(st)
            st_copy["max_turns"] = min(int(st_copy.get("max_turns", cap)), cap)
            steps.append(st_copy)
        cases.append(
            {
                "name": name,
                "steps": steps,
                "expectations": exps,
                "audio_expectations": ev.get("audio_expectations", []),
                "session_parameters": ev.get("session_parameters", {}),
                "metadata": {"tags": ev.get("tags", [])},
            }
        )
    return cases


SIM_PROBE_NAMES = {
    "probe_handoff_memory_tokyo",
    "probe_timezone_gate_sydney",
    "probe_french_across_handoff",
}


def _load_probes() -> list[dict[str, Any]]:
    data = yaml.safe_load(PROBES_YAML.read_text(encoding="utf-8")) or {}
    probes = [
        p for p in data.get("probes", []) if p.get("name") in SIM_PROBE_NAMES
    ]
    probes.append(
        {
            "name": "probe_tr10_unseen_cities_vienna_and_edinburgh",
            "variables": {"is_mock_mode": True},
            "turns": [
                "Hi Totto! What time does qualifying start for the next race? I'm watching from Vienna, Austria, and my friend is watching from Edinburgh, Scotland.",
            ],
            "expectations": [
                "The agent provided the qualifying time for the upcoming race converted to Vienna time (CEST / Europe/Vienna) and Edinburgh / UK time (BST / Europe/London) without fabricating session times.",
            ],
        }
    )
    return probes


def run(ctx: dict[str, Any]) -> list[dict[str, Any]]:
    app_name = str(ctx.get("app_name") or DEFAULT_APP_NAME)
    repeats = max(1, int(ctx.get("repeats") or 3))
    now_dt = resolve_now(ctx)

    sim = SimulationEvals(app_name=app_name)
    sim.max_retries = 6
    sim.retry_delay_base = 3
    try:
        ch_client = ConversationHistory(app_name=app_name, transport="rest")
    except TypeError:
        ch_client = ConversationHistory(app_name=app_name)
    fake = use_tool_fakes(ctx)
    tool_mode = "fake" if fake else "real"

    results: list[dict[str, Any]] = []
    all_artifacts: list[dict[str, Any]] = []

    # 1. Run multi-turn simulations sequentially (parallel=1)
    sim_cases = _load_simulations(now_dt)
    for case in sim_cases:
        c_name = str(case["name"])
        exp_count = len(case.get("expectations") or [])
        for rep_idx in range(1, repeats + 1):
            sim_rows: list[dict[str, Any]] = []
            try:
                sim_rows, _ = with_quota_retry(
                    lambda c=case: sim.run_simulations(
                        test_cases=[c],
                        runs=1,
                        parallel=1,
                        sim_user_model=FAST_SIM_MODEL,
                        eval_model=FAST_SIM_MODEL,
                        modality="text",
                        use_tool_fakes=fake,
                    ),
                    label=f"sim[{c_name}:r{rep_idx}]",
                )
            except Exception as exc:  # noqa: BLE001
                sim_rows = [
                    {
                        "name": c_name,
                        "run": rep_idx,
                        "passed": False,
                        "error": f"{type(exc).__name__}: {exc}",
                        "detailed_trace": [],
                        "expectation_details": [],
                    }
                ]

            row = dict(sim_rows[0]) if sim_rows else {"name": c_name, "run": rep_idx}
            row["run"] = rep_idx
            row["tool_mode"] = tool_mode
            session_id = str(row.get("session_id") or "")
            row["conversation_name"] = resolve_conversation_resource(
                app_name, session_id, ch_client=ch_client
            )

            art_path = save_layer_artifact(
                ctx, f"live_sims/{slugify(c_name)}_r{rep_idx}.json", row
            )
            all_artifacts.append(row)

            entry = grade_and_build_test_result(
                layer=LAYER,
                test_id=slugify(c_name),
                repeat=rep_idx,
                row=row,
                expectations_count=exp_count,
                now_dt=now_dt,
                raw_artifact_path=art_path,
                app_name=app_name,
                modality="text",
                is_simulation=True,
            )
            entry["tool_mode"] = tool_mode
            results.append(entry)

    # 2. Run scripted multi-turn probes sequentially (parallel=1)
    probes = _load_probes()
    for probe in probes:
        p_name = str(probe["name"])
        exp_count = len(probe.get("expectations") or [])
        for rep_idx in range(1, repeats + 1):
            row = run_instrumented_probe(
                sim,
                probe,
                rep_idx,
                modality="text",
                judge_model=FAST_SIM_MODEL,
                now_dt=now_dt,
                ch_client=ch_client,
                use_tool_fakes=fake,
            )
            art_path = save_layer_artifact(
                ctx, f"live_sims/{slugify(p_name)}_r{rep_idx}.json", row
            )
            all_artifacts.append(row)

            entry = grade_and_build_test_result(
                layer=LAYER,
                test_id=slugify(p_name),
                repeat=rep_idx,
                row=row,
                expectations_count=exp_count,
                now_dt=now_dt,
                raw_artifact_path=art_path,
                app_name=app_name,
                modality="text",
                is_simulation=False,
            )
            entry["tool_mode"] = tool_mode
            results.append(entry)

    save_layer_artifact(ctx, "live_sims/summary.json", all_artifacts)
    return results
