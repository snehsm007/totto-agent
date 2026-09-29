"""Static PIF XML instruction, routing, global instruction, and contract tests (layer: config)."""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from totto_suite.config import REPO_ROOT

EVALS_DIR = REPO_ROOT / "evals"

EXPECTED_AGENTS = (
    "totto_root_agent",
    "race_info_agent",
    "merch_support_agent",
    "ticketing_agent",
)
REQUIRED_XML_TAGS = ("<role>", "<persona>", "<constraints>", "<taskflow>", "<examples>")
BANNED_XML_TAGS = ("<context>", "<Context>", "<state>", "<transitions>", "<reasoning>", "<thought>")


@pytest.mark.finding("TR-01", "TR-02", "TR-03", "TR-04", "TR-05", "TR-06")
def test_app_json_and_global_instruction_configuration(agent_dir: Path) -> None:
    app_data = json.loads((agent_dir / "app.json").read_text(encoding="utf-8"))
    assert app_data["displayName"] == "totto-mercedes-f1-fan-agent"
    assert app_data["rootAgent"] == "totto_root_agent"
    assert app_data.get("globalInstruction") == "global_instruction.txt"

    global_inst_path = agent_dir / "global_instruction.txt"
    assert global_inst_path.exists(), "Missing global_instruction.txt"
    global_inst = global_inst_path.read_text(encoding="utf-8").lower()
    assert "multilingual continuity" in global_inst
    assert "seamless single persona" in global_inst
    assert "strict tool grounding" in global_inst
    assert "zero raw code in responses" in global_inst
    assert "silent, immediate handoffs" in global_inst

    declared_vars = {v["name"] for v in app_data.get("variableDeclarations", [])}
    assert {"user_timezone", "user_location", "order_id", "is_mock_mode"}.issubset(declared_vars)


@pytest.mark.finding("TR-01", "TR-02", "TR-05")
def test_all_agents_use_pif_xml_and_no_hallucination_or_leak_traps(agent_dir: Path) -> None:
    tool_ref_re = re.compile(r"\{@TOOL:\s*([^}]+)\}")
    agent_ref_re = re.compile(r"\{@AGENT:\s*([^}]+)\}")

    for agent_name in EXPECTED_AGENTS:
        adir = agent_dir / "agents" / agent_name
        cfg_path = adir / f"{agent_name}.json"
        inst_path = adir / "instruction.txt"
        assert cfg_path.exists(), f"Missing {cfg_path}"
        assert inst_path.exists(), f"Missing {inst_path}"

        cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
        inst = inst_path.read_text(encoding="utf-8")

        for tag in REQUIRED_XML_TAGS:
            assert tag in inst, f"{agent_name}/instruction.txt missing required PIF tag {tag}"
        assert "<subtask" in inst or "<step" in inst, f"{agent_name} taskflow missing <subtask>/<step>"
        assert "{current_date}" in inst, f"{agent_name} missing {{current_date}} (I014)"

        for banned in BANNED_XML_TAGS:
            assert banned not in inst, f"{agent_name} contains banned XML tag {banned} (I015)"

        examples_section = inst.split("<examples>", 1)[1] if "<examples>" in inst else ""
        assert "DHL-9928174" not in examples_section, (
            f"{agent_name} <examples> contains literal tracking number DHL-9928174 that causes hallucination"
        )
        assert "[Calls {@TOOL:" not in examples_section, (
            f"{agent_name} <examples> contains bracketed [Calls {{@TOOL:...}}] that causes code leaks"
        )
        assert "via {@AGENT:" not in examples_section, (
            f"{agent_name} <examples> contains 'via {{@AGENT:...}}' in spoken quote that leaks internal agent names"
        )

        # Bidirectional tool check (I012 / I013)
        config_tools = set(cfg.get("tools", []))
        referenced_tools = {m.group(1).strip() for m in tool_ref_re.finditer(inst)}
        assert referenced_tools.issubset(config_tools), (
            f"{agent_name} references tools not in JSON: {referenced_tools - config_tools}"
        )
        non_terminal_cfg_tools = config_tools - {"end_session"}
        assert non_terminal_cfg_tools.issubset(referenced_tools), (
            f"{agent_name} lists unused tools in JSON: {non_terminal_cfg_tools - referenced_tools}"
        )

        # Agent reference check (I008)
        referenced_agents = {m.group(1).strip() for m in agent_ref_re.finditer(inst)}
        assert referenced_agents.issubset(set(EXPECTED_AGENTS)), (
            f"{agent_name} references unknown agents: {referenced_agents - set(EXPECTED_AGENTS)}"
        )


@pytest.mark.finding("PRD-AC5", "TR-09", "NEW-2")
def test_instruction_mock_freshness_and_conciseness_rules(agent_dir: Path) -> None:
    """Verify mock disclosure, freshness disclosure, and concise reply length rules exist."""
    global_inst = (agent_dir / "global_instruction.txt").read_text(encoding="utf-8").lower()
    race_inst = (
        agent_dir / "agents" / "race_info_agent" / "instruction.txt"
    ).read_text(encoding="utf-8").lower()
    merch_inst = (
        agent_dir / "agents" / "merch_support_agent" / "instruction.txt"
    ).read_text(encoding="utf-8").lower()

    # Concise reply length (NEW-2)
    assert "concise" in global_inst and ("2–4 sentences" in global_inst or "2-4 sentences" in global_inst)
    # Freshness disclosure (TR-09)
    assert "latest-available" in race_inst or "latest available" in race_inst
    # Mock disclosure (PRD-AC5, TR-09)
    assert "simulated" in merch_inst and "mock" in merch_inst


@pytest.mark.finding("RC-06", "RC-07", "NEW-2")
def test_global_instruction_forbids_emojis_and_markdown_for_tts(agent_dir: Path) -> None:
    """Voice/TTS safety requires explicit instructions forbidding emojis and markdown formatting."""
    global_inst = (agent_dir / "global_instruction.txt").read_text(encoding="utf-8").lower()
    has_no_emoji_rule = bool(
        re.search(r"\b(?:no|never|without|avoid)\b[^.\n]{0,60}\bemojis?\b", global_inst)
    )
    has_no_markdown_rule = bool(
        re.search(
            r"\b(?:no|never|without|avoid|plain text)\b[^.\n]{0,80}\b(?:markdown|asterisks|bullet)\b",
            global_inst,
        )
    )
    assert has_no_emoji_rule and has_no_markdown_rule, (
        "global_instruction.txt lacks explicit TTS/voice constraints forbidding emojis and markdown "
        "formatting (causes RC-06/RC-07 voice TTS artifacts)"
    )


@pytest.mark.finding("NEW-3")
def test_global_or_root_instruction_enforces_pci_credit_card_refusal(agent_dir: Path) -> None:
    """Root/global instructions must enforce PCI credit-card refusal so card numbers are never echoed."""
    global_inst = (agent_dir / "global_instruction.txt").read_text(encoding="utf-8").lower()
    root_inst = (
        agent_dir / "agents" / "totto_root_agent" / "instruction.txt"
    ).read_text(encoding="utf-8").lower()
    combined = global_inst + "\n" + root_inst
    assert "credit card" in combined or "payment card" in combined, (
        "Neither global_instruction.txt nor totto_root_agent/instruction.txt contains a credit-card / "
        "PCI refusal constraint (NEW-3)"
    )


@pytest.mark.finding("RC-01", "RC-02", "RC-10")
def test_all_agents_cover_no_live_human_escalation_policy(agent_dir: Path) -> None:
    """Every sub-agent (or global_instruction.txt) must know how to handle live human escalation requests."""
    global_inst = (agent_dir / "global_instruction.txt").read_text(encoding="utf-8").lower()
    if "human escalation" in global_inst or "human agent" in global_inst:
        return
    missing = []
    for agent_name in EXPECTED_AGENTS:
        inst = (
            agent_dir / "agents" / agent_name / "instruction.txt"
        ).read_text(encoding="utf-8").lower()
        if "human escalation" not in inst and "human agent" not in inst:
            missing.append(agent_name)
    assert not missing, (
        f"global_instruction.txt and specialist agents {missing} lack live human escalation handling "
        "instructions (RC-01, RC-02, RC-10)"
    )


def test_callbacks_synced_with_shared_imports() -> None:
    """Verify agent callbacks are in sync withshared/ via bundle_shared_imports.py --check."""
    proc = subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts" / "bundle_shared_imports.py"), "--check"],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, f"bundle_shared_imports.py --check failed:\n{proc.stdout}\n{proc.stderr}"


def test_public_evals_cover_all_9_prd_acceptance_criteria() -> None:
    goldens = yaml.safe_load(
        (EVALS_DIR / "goldens" / "goldens.yaml").read_text(encoding="utf-8")
    )
    sims = yaml.safe_load(
        (EVALS_DIR / "simulations" / "simulations.yaml").read_text(encoding="utf-8")
    )

    assert "common_session_parameters" in goldens
    golden_convs = goldens.get("conversations", [])
    sim_evals = sims.get("evals", [])
    assert len(golden_convs) >= 5
    assert len(sim_evals) >= 10

    for i in range(1, 10):
        ac_tag = f"AC-{i}"
        assert any(ac_tag in s.get("tags", []) for s in sim_evals) or any(
            ac_tag in c.get("tags", []) for c in golden_convs
        ), f"Missing {ac_tag} in public evals"


def test_secret_holdout_has_at_least_12_scenarios_across_4_buckets() -> None:
    holdout = yaml.safe_load(
        (EVALS_DIR / "secret_holdout" / "totto_secret_holdout.yaml").read_text(encoding="utf-8")
    )
    scenarios = holdout.get("evals", [])
    assert len(scenarios) >= 12

    required_buckets = {
        "happy_path",
        "edge_ambiguous",
        "adversarial_brand_safety",
        "out_of_scope_guardrails",
    }
    buckets_found = {s["bucket"] for s in scenarios}
    assert required_buckets == buckets_found

    for b in required_buckets:
        count = sum(1 for s in scenarios if s["bucket"] == b)
        assert count >= 3, f"Bucket {b} has only {count} scenarios (expected >= 3)"

    pairs = [(s["stresses"], s["edge"]) for s in scenarios]
    assert len(pairs) == len(set(pairs)), "Duplicate (stresses, edge) pairs found in secret holdout"


def test_no_test_prompts_hardcoded_in_instruction_examples(agent_dir: Path) -> None:
    """Verify no instruction.txt <examples> block contains literal user turns from probes.yaml or goldens.yaml."""
    probes = yaml.safe_load((EVALS_DIR / "probes" / "probes.yaml").read_text(encoding="utf-8"))
    goldens = yaml.safe_load((EVALS_DIR / "goldens" / "goldens.yaml").read_text(encoding="utf-8"))

    test_user_turns = []
    probe_list = probes.get("probes", []) if isinstance(probes, dict) else probes
    for p in probe_list:
        for t in p.get("turns", []):
            if len(t) > 15:
                test_user_turns.append(t.lower())
    for c in goldens.get("conversations", []):
        for t in c.get("turns", []):
            u = t.get("user", "")
            if len(u) > 15:
                test_user_turns.append(u.lower())

    inst_files = [agent_dir / "global_instruction.txt"] + [
        agent_dir / "agents" / a / "instruction.txt" for a in EXPECTED_AGENTS
    ]
    for path in inst_files:
        text = path.read_text(encoding="utf-8").lower()
        for ut in test_user_turns:
            assert ut not in text, f"{path.name} contains literal test prompt: {ut!r}"


@pytest.mark.finding("TB-1", "TR-09", "RC-01", "RC-02")
def test_all_tools_configure_and_execute_mock_tool_fakes_offline(agent_dir: Path) -> None:
    """Verify all 4 tools declare toolFakeConfig and have working offline fake_tool_call implementations."""
    expected_tools = {
        "get_race_schedule": {"race_query": "next", "user_timezone": "Europe/London"},
        "get_driver_standings": {"category": "all"},
        "lookup_mock_merch_order": {"order_id": "1001"},
        "get_official_links": {"category": "all"},
    }
    for tool_name, sample_input in expected_tools.items():
        tool_json_path = agent_dir / "tools" / tool_name / f"{tool_name}.json"
        assert tool_json_path.is_file(), f"Missing {tool_json_path}"
        tool_cfg = json.loads(tool_json_path.read_text(encoding="utf-8"))
        fake_cfg = tool_cfg.get("toolFakeConfig")
        assert isinstance(fake_cfg, dict), f"{tool_name}.json missing toolFakeConfig"
        rel_code_path = (fake_cfg.get("codeBlock") or {}).get("pythonCode")
        assert rel_code_path == f"tools/{tool_name}/tool_fake_config/code_block/python_code.py"

        fake_py_path = agent_dir / rel_code_path
        assert fake_py_path.is_file(), f"Missing fake python_code.py for {tool_name}: {fake_py_path}"
        ns: dict[str, object] = {"Tool": object, "CallbackContext": object}
        exec(compile(fake_py_path.read_text(encoding="utf-8"), str(fake_py_path), "exec"), ns)
        fn = ns.get("fake_tool_call")
        assert callable(fn), f"{fake_py_path} does not define callable fake_tool_call"
        res = fn(None, sample_input, None)
        assert isinstance(res, dict) and res.get("status") == "success", (
            f"fake_tool_call for {tool_name} failed on {sample_input}: {res}"
        )

