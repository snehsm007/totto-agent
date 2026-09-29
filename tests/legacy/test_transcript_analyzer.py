"""Unit tests for deterministic transcript grounding analyzer (`scripts/analyze_transcripts.py`)."""

import importlib.util
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
ANALYZER_PATH = PROJECT_ROOT / "scripts" / "analyze_transcripts.py"


def _load_analyzer():
    spec = importlib.util.spec_from_file_location("analyze_transcripts", ANALYZER_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_analyzer_catches_all_5_defect_types_from_test_report() -> None:
    analyzer = _load_analyzer()
    defective_trace = [
        # 1. Dead-air handoff + 2. Code leak
        (
            "User Query: When is the next race?\n"
            "Agent Transfer: totto_root_agent -> race_info_agent\n"
            "Agent Text: Let me check the race schedule for you. default_api.get_race_schedule(race_query='next')"
        ),
        # 3. Race facts without tool call
        (
            "User Query: What time in Sydney?\n"
            "Agent Text: Qualifying at Silverstone is at 14:00 UTC on October 10, 2026."
        ),
        # 4. Order facts without tool call + 5. Tool error
        (
            "User Query: Check order #1001\n"
            "Tool Call: get_driver_standings {'category': 'both'}\n"
            "Tool Response: {'status': 'error', 'error_message': 'Invalid category'}\n"
            "Agent Text: Your order #1001 is Shipped via DHL-9928174 and in transit."
        ),
    ]
    flags: set[str] = set()
    for entry in defective_trace:
        f, _ = analyzer.turn_flags(entry)
        flags.update(f)
    flags.update(analyzer.grounding_flags(defective_trace))

    assert "code_leak" in flags
    assert "dead_air_handoff" in flags
    assert "race_facts_without_tool" in flags
    assert "order_facts_without_tool" in flags
    assert "tool_error" in flags


def test_analyzer_passes_clean_grounded_transcript() -> None:
    analyzer = _load_analyzer()
    clean_trace = [
        (
            "User Query: When is the next race and what is the status of order #1001?\n"
            "Agent Transfer: totto_root_agent -> race_info_agent\n"
            "Tool Call: get_race_schedule {'race_query': 'next', 'user_timezone': 'UTC'}\n"
            "Tool Response: {'status': 'success'}\n"
            "Agent Text: The upcoming 2026 British Grand Prix at Silverstone takes place October 9-11, 2026 "
            "with Qualifying at 14:00 UTC and the Sunday Grand Prix at 14:00 UTC. What timezone are you watching from so I can convert these times for you?"
        ),
        (
            "User Query: And order #1001?\n"
            "Agent Transfer: race_info_agent -> merch_support_agent\n"
            "Tool Call: lookup_mock_merch_order {'order_id': '1001'}\n"
            "Tool Response: {'status': 'success'}\n"
            "Agent Text: In our simulated demo system, order #1001 (Mercedes-AMG Petronas 2026 Team Driver Cap) "
            "is Delivered via DHL-GB-8849201, and it is eligible for our 30-day return or damaged-item exchange policy."
        ),
    ]
    flags: list[str] = []
    for entry in clean_trace:
        f, _ = analyzer.turn_flags(entry)
        flags.extend(f)
    flags.extend(analyzer.grounding_flags(clean_trace))
    assert flags == []
