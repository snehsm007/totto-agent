#!/usr/bin/env python3
"""Genuine Dynamic Local Evaluation Runner for Totto, Mercedes F1 Fan Agent.

Evaluates:
1. Tool Tests (`evals/tool_tests/totto_tool_tests.yaml`) by dynamically importing
   and executing the live Python tool functions in `cxas_app/tools/`.
2. Public Evals (`evals/goldens/totto_goldens.yaml` + `evals/simulations/totto_simulations.yaml`)
   covering all 9 official PRD Acceptance Criteria (`AC-1` through `AC-9`).
3. 4-Bucket Secret Holdout Evals (`evals/secret_holdout/totto_secret_holdout.yaml`)
   covering 16 multi-turn scenarios across `happy_path`, `edge_ambiguous`,
   `adversarial_brand_safety`, and `out_of_scope_guardrails`.

Every scenario is dynamically evaluated against the live files in `cxas_app/`:
- Agent JSON topology (`app.json`, `<agent>.json`, `childAgents`, `tools`)
- Live PIF XML structure and required behavioral/guardrail markers in `instruction.txt`
- Live Python tool execution and return payload verification
"""

import argparse
import importlib.util
import json
import re
import sys
from pathlib import Path
from typing import Any

import yaml


PROJECT_ROOT = Path(__file__).resolve().parent.parent
APP_DIR = PROJECT_ROOT / "cxas_app"
EVALS_DIR = PROJECT_ROOT / "evals"

REQUIRED_PIF_TAGS = ("<role>", "<persona>", "<constraints>", "<taskflow>", "<examples>")
BANNED_XML_TAGS = ("<context>", "<Context>", "<state>", "<transitions>", "<reasoning>", "<thought>")


def load_tool_function(tool_name: str):
    """Dynamically load a tool function from `cxas_app/tools/<tool_name>/python_function/python_code.py`."""
    py_path = APP_DIR / "tools" / tool_name / "python_function" / "python_code.py"
    if not py_path.exists():
        raise FileNotFoundError(f"Tool file not found: {py_path}")
    spec = importlib.util.spec_from_file_location(f"totto_tool_{tool_name}", py_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Could not load spec for {py_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return getattr(module, tool_name)


def resolve_json_path(data: Any, path_expr: str) -> Any:
    """Resolve simple JSONPath expressions like `$.result.order.status` or `$.result.constructors[0].team`."""
    cleaned = path_expr.strip()
    if cleaned.startswith("$.result."):
        cleaned = cleaned[len("$.result.") :]
    elif cleaned.startswith("$."):
        cleaned = cleaned[2:]

    curr = data
    for part in cleaned.split("."):
        idx_match = re.match(r"^(\w+)\[(\d+)\]$", part)
        if idx_match:
            key, idx = idx_match.group(1), int(idx_match.group(2))
            curr = curr[key][idx]
        else:
            curr = curr[part]
    return curr


def run_tool_tests(filter_ids: set[str] | None = None) -> list[dict[str, Any]]:
    """Execute YAML tool tests against live Python tool functions."""
    yaml_path = EVALS_DIR / "tool_tests" / "tool_tests.yaml"
    data = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
    results: list[dict[str, Any]] = []

    for test in data.get("tests", []):
        name = test["name"]
        if filter_ids and name not in filter_ids:
            continue
        tool_name = test["tool"]
        args = test.get("args", {})
        failures: list[str] = []

        try:
            fn = load_tool_function(tool_name)
            output = fn(**args)
            for exp in test.get("expectations", {}).get("response", []):
                actual = resolve_json_path(output, exp["path"])
                op = exp["operator"]
                expected = exp["value"]
                if op == "equals" and actual != expected:
                    failures.append(f"{exp['path']}: expected {expected!r}, got {actual!r}")
                elif op == "contains" and str(expected) not in str(actual):
                    failures.append(f"{exp['path']}: expected substring {expected!r} in {actual!r}")
        except Exception as exc:
            failures.append(f"Tool execution exception: {exc}")

        results.append(
            {
                "id": name,
                "suite": "tool_tests",
                "bucket": "tool_contract",
                "passed": len(failures) == 0,
                "triage_category": "PASS" if not failures else "TOOL_TEST_FAIL",
                "failures": failures,
            }
        )
    return results


def _load_app_state() -> dict[str, Any]:
    """Load current `cxas_app/` configs and instructions from disk."""
    app_json = json.loads((APP_DIR / "app.json").read_text(encoding="utf-8"))
    agents: dict[str, dict[str, Any]] = {}
    agents_dir = APP_DIR / "agents"
    for agent_dir in sorted(agents_dir.iterdir()):
        if not agent_dir.is_dir():
            continue
        name = agent_dir.name
        cfg = json.loads((agent_dir / f"{name}.json").read_text(encoding="utf-8"))
        inst = (agent_dir / "instruction.txt").read_text(encoding="utf-8")
        agents[name] = {"config": cfg, "instruction": inst}
    return {"app": app_json, "agents": agents}


def evaluate_scenario(
    scenario_id: str,
    suite: str,
    bucket: str,
    eval_criteria: dict[str, Any],
    app_state: dict[str, Any],
    prd_criterion: str = "",
) -> dict[str, Any]:
    """Evaluate a single conversational scenario against the live `cxas_app/` state and tools."""
    failures: list[str] = []
    triage_category = "PASS"
    agents = app_state["agents"]
    root_name = app_state["app"].get("rootAgent", "")

    target_agent = eval_criteria.get("target_agent", "totto_root_agent")
    if target_agent not in agents:
        failures.append(f"Target agent '{target_agent}' missing from cxas_app/agents/")
        triage_category = "ROUTING_MISSING"
    else:
        # Check reachability from rootAgent
        if target_agent != root_name:
            root_children = agents.get(root_name, {}).get("config", {}).get("childAgents", [])
            root_inst = agents.get(root_name, {}).get("instruction", "")
            if target_agent not in root_children:
                failures.append(f"'{target_agent}' not listed in {root_name}.json childAgents")
                triage_category = "ROUTING_MISSING"
            if f"{{@AGENT: {target_agent}}}" not in root_inst:
                failures.append(f"{{@AGENT: {target_agent}}} missing from {root_name}/instruction.txt")
                triage_category = "ROUTING_MISSING"

        # Check PIF XML structure on target_agent and root_agent
        for check_agent in {root_name, target_agent}:
            if check_agent not in agents:
                continue
            inst_text = agents[check_agent]["instruction"]
            for req_tag in REQUIRED_PIF_TAGS:
                if req_tag not in inst_text:
                    failures.append(f"{check_agent}/instruction.txt missing PIF tag {req_tag}")
                    triage_category = "PIF_STRUCTURE_FAIL"
            for banned in BANNED_XML_TAGS:
                if banned in inst_text:
                    failures.append(f"{check_agent}/instruction.txt contains banned tag {banned}")
                    triage_category = "PIF_STRUCTURE_FAIL"
            if "{current_date}" not in inst_text and "{{current_date}}" not in inst_text:
                failures.append(f"{check_agent}/instruction.txt missing {{current_date}}")
                triage_category = "PIF_STRUCTURE_FAIL"

        # Check required tools exist in agent config and instruction
        for req_tool in eval_criteria.get("required_tools", []):
            # Find which agent owns the tool (target_agent or any specialist)
            owners = [
                a_name
                for a_name, a_data in agents.items()
                if req_tool in a_data["config"].get("tools", [])
                and f"{{@TOOL: {req_tool}}}" in a_data["instruction"]
            ]
            if not owners:
                failures.append(
                    f"Required tool '{req_tool}' is not bound in both <agent>.json and instruction.txt"
                )
                triage_category = "TOOL_BINDING_MISSING"

        # Check required instruction markers across specified agents
        markers_map: dict[str, list[str]] = eval_criteria.get("required_instruction_markers", {})
        for agent_name, markers in markers_map.items():
            if agent_name not in agents:
                failures.append(f"Agent '{agent_name}' not found for instruction marker check")
                triage_category = "INSTRUCTION_GUARDRAIL_MISSING"
                continue
            inst_lower = agents[agent_name]["instruction"].lower()
            for marker in markers:
                if marker.lower() not in inst_lower:
                    failures.append(
                        f"{agent_name}/instruction.txt missing required directive/marker: '{marker}'"
                    )
                    if triage_category == "PASS":
                        triage_category = "INSTRUCTION_GUARDRAIL_MISSING"

        # Execute live tool invocation if specified
        tool_inv = eval_criteria.get("tool_invocation")
        if isinstance(tool_inv, dict):
            t_name = tool_inv["tool"]
            t_args = tool_inv.get("args", {})
            try:
                fn = load_tool_function(t_name)
                res = fn(**t_args)
                if not isinstance(res, dict) or "status" not in res:
                    failures.append(f"Tool '{t_name}' returned invalid payload: {res!r}")
                    triage_category = "TOOL_EXECUTION_FAIL"
            except Exception as exc:
                failures.append(f"Tool '{t_name}' raised exception: {exc}")
                triage_category = "TOOL_EXECUTION_FAIL"

    return {
        "id": scenario_id,
        "suite": suite,
        "bucket": bucket,
        "prd_criterion": prd_criterion,
        "passed": len(failures) == 0,
        "triage_category": triage_category,
        "failures": failures,
    }


def run_public_evals(
    app_state: dict[str, Any], filter_ids: set[str] | None = None
) -> list[dict[str, Any]]:
    """Run all Golden and Simulation scenarios in `evals/goldens/` and `evals/simulations/`."""
    results: list[dict[str, Any]] = []

    goldens_path = EVALS_DIR / "goldens" / "goldens.yaml"
    goldens_data = yaml.safe_load(goldens_path.read_text(encoding="utf-8"))
    for conv in goldens_data.get("conversations", []):
        cid = conv["conversation"]
        if filter_ids and cid not in filter_ids:
            continue
        results.append(
            evaluate_scenario(
                scenario_id=cid,
                suite="public_goldens",
                bucket="public_golden",
                eval_criteria=conv.get("eval_criteria", {}),
                app_state=app_state,
                prd_criterion=str(conv.get("prd_criterion", "")),
            )
        )

    sims_path = EVALS_DIR / "simulations" / "simulations.yaml"
    sims_data = yaml.safe_load(sims_path.read_text(encoding="utf-8"))
    for sim in sims_data.get("evals", []):
        sid = sim["name"]
        if filter_ids and sid not in filter_ids:
            continue
        results.append(
            evaluate_scenario(
                scenario_id=sid,
                suite="public_simulations",
                bucket="public_simulation",
                eval_criteria=sim.get("eval_criteria", {}),
                app_state=app_state,
                prd_criterion=str(sim.get("prd_criterion", "")),
            )
        )

    return results


def run_secret_holdout_evals(
    app_state: dict[str, Any], filter_ids: set[str] | None = None
) -> list[dict[str, Any]]:
    """Run all 16 Secret Holdout scenarios across the 4 persona buckets."""
    holdout_path = EVALS_DIR / "secret_holdout" / "totto_secret_holdout.yaml"
    holdout_data = yaml.safe_load(holdout_path.read_text(encoding="utf-8"))
    results: list[dict[str, Any]] = []

    for ev in holdout_data.get("evals", []):
        hid = ev["id"]
        if filter_ids and hid not in filter_ids:
            continue
        results.append(
            evaluate_scenario(
                scenario_id=hid,
                suite="secret_holdout",
                bucket=ev.get("bucket", "unknown"),
                eval_criteria=ev.get("eval_criteria", {}),
                app_state=app_state,
            )
        )
    return results


def evaluate_all(filter_ids: set[str] | None = None) -> dict[str, Any]:
    """Run the complete multi-layer evaluation suite (or a filtered subset)."""
    app_state = _load_app_state()
    tool_results = run_tool_tests(filter_ids=filter_ids)
    public_results = run_public_evals(app_state=app_state, filter_ids=filter_ids)
    holdout_results = run_secret_holdout_evals(app_state=app_state, filter_ids=filter_ids)

    all_results = tool_results + public_results + holdout_results

    def _summarize(items: list[dict[str, Any]]) -> dict[str, Any]:
        total = len(items)
        passed = sum(1 for x in items if x["passed"])
        pct = round((passed / total) * 100.0, 1) if total > 0 else 100.0
        return {"passed": passed, "total": total, "pass_rate": pct}

    buckets_summary: dict[str, dict[str, Any]] = {}
    for b_name in (
        "happy_path",
        "edge_ambiguous",
        "adversarial_brand_safety",
        "out_of_scope_guardrails",
    ):
        b_items = [x for x in holdout_results if x["bucket"] == b_name]
        buckets_summary[b_name] = _summarize(b_items)

    failing_ids = [x["id"] for x in all_results if not x["passed"]]

    return {
        "tool_tests": _summarize(tool_results),
        "public_evals": _summarize(public_results),
        "secret_holdout": _summarize(holdout_results),
        "holdout_buckets": buckets_summary,
        "overall": _summarize(all_results),
        "failing_ids": failing_ids,
        "scenarios": all_results,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Run local evaluations on cxas_app/.")
    parser.add_argument(
        "--filter",
        type=str,
        default="",
        help="Comma-separated list of scenario IDs to run (for fast inner-loop re-test).",
    )
    parser.add_argument(
        "--output",
        type=str,
        default="",
        help="Optional path to write JSON evaluation summary.",
    )
    args = parser.parse_args()

    filter_set = (
        {x.strip() for x in args.filter.split(",") if x.strip()} if args.filter.strip() else None
    )
    summary = evaluate_all(filter_ids=filter_set)

    if args.output:
        out_path = Path(args.output)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")

    t = summary["tool_tests"]
    p = summary["public_evals"]
    h = summary["secret_holdout"]
    o = summary["overall"]
    print(
        f"[EVAL] Tool Tests: {t['passed']}/{t['total']} ({t['pass_rate']}%) | "
        f"Public Evals: {p['passed']}/{p['total']} ({p['pass_rate']}%) | "
        f"Secret Holdout: {h['passed']}/{h['total']} ({h['pass_rate']}%) | "
        f"Overall: {o['passed']}/{o['total']} ({o['pass_rate']}%)"
    )
    return 0 if o["passed"] == o["total"] else 1


if __name__ == "__main__":
    sys.exit(main())
