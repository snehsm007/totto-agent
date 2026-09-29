from cxas_scrapi.utils.callback_libs import CallbackContext, Tool
from python_code import after_tool_callback


def test_sync_order_state_persists_order_id_and_mock_flag() -> None:
    tool = Tool(name="lookup_mock_merch_order", description="Order lookup tool")
    ctx = CallbackContext(state={})
    res = after_tool_callback(
        tool=tool,
        input={"order_id": "#1001"},
        callback_context=ctx,
        tool_response={"status": "success", "order_id": "1001", "found": True},
    )
    assert res is None
    assert ctx.state["order_id"] == "1001"
    assert ctx.state["is_mock_mode"] is True
