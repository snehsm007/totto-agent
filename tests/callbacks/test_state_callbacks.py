"""Unit tests for the 3 state callbacks of the agent in $TOTTO_APP_DIR.

Consolidated from the original tests/test_state_callbacks.py (the 5 original
cases are kept verbatim in behaviour) plus error paths: missing/None input,
non-string values, error tool responses, multilingual order phrases and false
positives. The SCRAPI-format callback tests (evals/callback_tests/**/test.py)
run against the same agent code through totto_suite/layers/offline_callbacks.py.
"""

from types import SimpleNamespace

import pytest

ROOT = ("totto_root_agent", "before_agent_callbacks", "init_session_state")
RACE = ("race_info_agent", "after_tool_callbacks", "sync_race_state")
ORDER = ("merch_support_agent", "after_tool_callbacks", "sync_order_state")


def _user_ctx(state: dict, *texts):
    parts = [SimpleNamespace(text_or_transcript=(lambda t=t: t)) for t in texts]
    return SimpleNamespace(state=state, get_last_user_input=lambda: parts)


# ----------------------------- original cases -----------------------------


def test_init_session_state_sets_defaults_when_missing(load_callback) -> None:
    mod = load_callback(*ROOT)
    ctx = SimpleNamespace(state={}, get_last_user_input=lambda: [])
    ret = mod.before_agent_callback(ctx)
    assert ret is None
    assert ctx.state["is_mock_mode"] is True
    assert ctx.state["user_timezone"] == ""
    assert ctx.state["user_location"] == ""
    assert ctx.state["order_id"] == ""


def test_init_session_state_preserves_existing_session_parameters_and_extracts_order_id(load_callback) -> None:
    mod = load_callback(*ROOT)
    ctx = _user_ctx(
        {"is_mock_mode": True, "user_timezone": "Asia/Tokyo", "user_location": "Tokyo", "order_id": ""},
        "Can you check order #1002?",
    )
    ret = mod.before_agent_callback(ctx)
    assert ret is None
    assert ctx.state["user_timezone"] == "Asia/Tokyo"
    assert ctx.state["user_location"] == "Tokyo"
    assert ctx.state["order_id"] == "1002"


def test_sync_race_state_persists_resolved_timezone(load_callback) -> None:
    mod = load_callback(*RACE)
    tool = SimpleNamespace(name="get_race_schedule")
    ctx = SimpleNamespace(state={"user_timezone": "", "user_location": ""})
    tool_response = {
        "status": "success",
        "needs_timezone_clarification": False,
        "timezone_resolved": "Australia/Sydney (AEDT (Sydney))",
    }
    ret = mod.after_tool_callback(tool, {"race_query": "next", "user_timezone": "Sydney"}, ctx, tool_response)
    assert ret is None
    assert ctx.state["user_timezone"] == "Australia/Sydney (AEDT (Sydney))"
    assert ctx.state["user_location"] == "Sydney"


def test_sync_race_state_ignores_utc_clarification_response(load_callback) -> None:
    mod = load_callback(*RACE)
    tool = SimpleNamespace(name="get_race_schedule")
    ctx = SimpleNamespace(state={"user_timezone": ""})
    tool_response = {"status": "success", "needs_timezone_clarification": True, "timezone_resolved": "UTC"}
    ret = mod.after_tool_callback(tool, {"race_query": "next", "user_timezone": "UTC"}, ctx, tool_response)
    assert ret is None
    assert ctx.state["user_timezone"] == ""


def test_sync_order_state_persists_normalized_order_id_and_mock_flag(load_callback) -> None:
    mod = load_callback(*ORDER)
    tool = SimpleNamespace(name="lookup_mock_merch_order")
    ctx = SimpleNamespace(state={"order_id": ""})
    tool_response = {"status": "success", "found": True, "is_mock_data": True, "order": {"order_id": "1001", "status": "Delivered"}}
    ret = mod.after_tool_callback(tool, {"order_id": "#1001"}, ctx, tool_response)
    assert ret is None
    assert ctx.state["order_id"] == "1001"
    assert ctx.state["is_mock_mode"] is True


# ------------------------- init_session_state paths ------------------------


@pytest.mark.finding("PRD-AC5", "PRD-AC6", "PRD-L137")
@pytest.mark.parametrize(
    "text,expected",
    [
        ("Bestellung 1002 ist nicht angekommen", "1002"),
        ("Où en est ma commande 1003 ?", "1003"),
        ("¿Dónde está mi pedido #1001?", "1001"),
        ("Can you check order number 1001?", "1001"),
        ("¿Dónde está mi pedido número 1002?", "1002"),
        ("Meine Bestellnummer ist 1003", "1003"),
    ],
)
def test_init_session_state_extracts_order_id_from_multilingual_phrases(load_callback, text: str, expected: str) -> None:
    mod = load_callback(*ROOT)
    ctx = _user_ctx({}, text)
    assert mod.before_agent_callback(ctx) is None
    assert ctx.state["order_id"] == expected, f"{text!r} -> order_id={ctx.state['order_id']!r}"


@pytest.mark.finding("PRD-L137", "PRD-L152")
@pytest.mark.parametrize(
    "text",
    [
        "Is George Russell the #1 driver this year?",
        "Who is P1 in the standings, #63 or #12?",
        "In what order do the sessions run at Monza?",
        "Go #SilverArrows, when is the next race?",
    ],
)
def test_init_session_state_does_not_invent_order_id_from_non_order_text(load_callback, text: str) -> None:
    mod = load_callback(*ROOT)
    ctx = _user_ctx({}, text)
    assert mod.before_agent_callback(ctx) is None
    assert ctx.state["order_id"] == "", f"{text!r} -> invented order_id={ctx.state['order_id']!r}"


def test_init_session_state_keeps_known_order_and_updates_on_new_one(load_callback) -> None:
    mod = load_callback(*ROOT)
    ctx = _user_ctx({"order_id": "1002"}, "thanks, that's all")
    mod.before_agent_callback(ctx)
    assert ctx.state["order_id"] == "1002"
    ctx2 = _user_ctx(dict(ctx.state), "now check order #1003")
    mod.before_agent_callback(ctx2)
    assert ctx2.state["order_id"] == "1003"


@pytest.mark.parametrize("transcript", [None, "", "   "])
def test_init_session_state_tolerates_missing_transcript(load_callback, transcript) -> None:
    mod = load_callback(*ROOT)
    ctx = _user_ctx({}, transcript)
    assert mod.before_agent_callback(ctx) is None
    assert ctx.state["order_id"] == "" and ctx.state["is_mock_mode"] is True


# --------------------------- after-tool callbacks --------------------------


@pytest.mark.parametrize("req_tz", ["", "utc", "UNKNOWN", None])
def test_sync_race_state_does_not_overwrite_known_timezone_with_unknown(load_callback, req_tz) -> None:
    mod = load_callback(*RACE)
    ctx = SimpleNamespace(state={"user_timezone": "Asia/Tokyo (JST (Tokyo))", "user_location": "Tokyo"})
    mod.after_tool_callback(SimpleNamespace(name="get_race_schedule"), {"race_query": "next", "user_timezone": req_tz}, ctx, {"status": "success", "timezone_resolved": "UTC"})
    assert ctx.state["user_timezone"] == "Asia/Tokyo (JST (Tokyo))"
    assert ctx.state["user_location"] == "Tokyo"


def test_sync_race_state_tolerates_error_response_and_missing_keys(load_callback) -> None:
    mod = load_callback(*RACE)
    ctx = SimpleNamespace(state={"user_timezone": ""})
    ret = mod.after_tool_callback(SimpleNamespace(name="get_race_schedule"), {}, ctx, {"status": "error", "agent_action": "CLARIFY_RACE_NAME"})
    assert ret is None
    assert ctx.state["user_timezone"] == ""


@pytest.mark.parametrize(
    "tool_input,tool_response,expected",
    [
        ({"order_id": 1002}, {"status": "success", "order_id": "1002"}, "1002"),
        ({"order_id": "#9999"}, {"status": "error", "found": False, "order_id": "9999"}, "9999"),
        ({}, {"status": "error", "found": False, "order_id": ""}, "1001"),
    ],
)
def test_sync_order_state_error_paths(load_callback, tool_input, tool_response, expected) -> None:
    mod = load_callback(*ORDER)
    ctx = SimpleNamespace(state={"order_id": "1001"})
    assert mod.after_tool_callback(SimpleNamespace(name="lookup_mock_merch_order"), tool_input, ctx, tool_response) is None
    assert ctx.state["order_id"] == expected
    assert ctx.state["is_mock_mode"] is True
