from cxas_scrapi.utils.callback_libs import CallbackContext, Content, Event, Part
from python_code import before_agent_callback


def test_init_session_state_defaults() -> None:
    ctx = CallbackContext(state={})
    res = before_agent_callback(ctx)
    assert res is None
    assert ctx.state["is_mock_mode"] is True
    assert ctx.state["user_timezone"] == ""
    assert ctx.state["user_location"] == ""
    assert ctx.state["order_id"] == ""


def test_init_session_state_extracts_order_id_from_user_event() -> None:
    event = Event(
        id="e1",
        author="user",
        timestamp=1,
        invocationId="inv1",
        content=Content(role="user", parts=[Part.from_text("Check my order #1002 please")]),
    )
    ctx = CallbackContext(state={}, events=[event])
    res = before_agent_callback(ctx)
    assert res is None
    assert ctx.state["order_id"] == "1002"
    assert ctx.state["is_mock_mode"] is True
