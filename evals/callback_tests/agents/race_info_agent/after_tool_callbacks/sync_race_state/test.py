from cxas_scrapi.utils.callback_libs import CallbackContext, Tool
from python_code import after_tool_callback


def test_sync_race_state_persists_timezone_and_location() -> None:
    tool = Tool(name="get_race_schedule", description="Race schedule tool")
    ctx = CallbackContext(state={})
    res = after_tool_callback(
        tool=tool,
        input={"race_query": "next", "user_timezone": "Sydney"},
        callback_context=ctx,
        tool_response={"status": "success", "timezone_resolved": "AEDT (Sydney)"},
    )
    assert res is None
    assert ctx.state["user_timezone"] == "AEDT (Sydney)"
    assert ctx.state["user_location"] == "Sydney"


def test_sync_race_state_preserves_existing_timezone_when_utc_queried() -> None:
    tool = Tool(name="get_race_schedule", description="Race schedule tool")
    ctx = CallbackContext(state={"user_timezone": "JST (Tokyo)", "user_location": "Tokyo"})
    res = after_tool_callback(
        tool=tool,
        input={"race_query": "next", "user_timezone": ""},
        callback_context=ctx,
        tool_response={"status": "success", "timezone_resolved": "UTC"},
    )
    assert res is None
    assert ctx.state["user_timezone"] == "JST (Tokyo)"
    assert ctx.state["user_location"] == "Tokyo"
