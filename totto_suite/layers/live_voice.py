"""Live layer: live_voice (audio modality sessions graded for voice conciseness, latency, and TTS formatting)."""

from __future__ import annotations

from typing import Any
import yaml

from cxas_scrapi.core.conversation_history import ConversationHistory
from cxas_scrapi.evals.simulation_evals import SimulationEvals
from totto_suite.live.runner import (
    DEFAULT_APP_NAME,
    FAST_SIM_MODEL,
    grade_and_build_test_result,
    resolve_now,
    run_instrumented_probe,
    save_layer_artifact,
    slugify,
    use_tool_fakes,
)
from totto_suite.config import REPO_ROOT

LAYER = "live_voice"
VOICE_YAML = REPO_ROOT / "evals" / "voice" / "voice_evals.yaml"


def run(ctx: dict[str, Any]) -> list[dict[str, Any]]:
    app_name = str(ctx.get("app_name") or DEFAULT_APP_NAME)
    repeats = max(1, int(ctx.get("repeats") or 3))
    now_dt = resolve_now(ctx)

    data = yaml.safe_load(VOICE_YAML.read_text(encoding="utf-8")) or {}
    probes = list(data.get("probes", []))

    sim = SimulationEvals(app_name=app_name)
    ch_client = ConversationHistory(app_name=app_name, transport="rest")

    results: list[dict[str, Any]] = []
    all_artifacts: list[dict[str, Any]] = []

    for probe in probes:
        p_name = str(probe["name"])
        exp_count = len(probe.get("expectations") or [])
        for rep_idx in range(1, repeats + 1):
            row = run_instrumented_probe(
                sim,
                probe,
                rep_idx,
                modality="audio",
                judge_model=FAST_SIM_MODEL,
                now_dt=now_dt,
                ch_client=ch_client,
                use_tool_fakes=use_tool_fakes(ctx),
            )
            art_path = save_layer_artifact(
                ctx, f"live_voice/{slugify(p_name)}_r{rep_idx}.json", row
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
                modality="audio",
                is_simulation=False,
            )
            entry["tool_mode"] = row.get("tool_mode", "real")
            results.append(entry)

    save_layer_artifact(ctx, "live_voice/summary.json", all_artifacts)
    return results
