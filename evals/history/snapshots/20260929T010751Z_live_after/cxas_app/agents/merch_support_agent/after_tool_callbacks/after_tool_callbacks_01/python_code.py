from typing import Any, Optional


def after_tool_callback(
    tool: Tool,
    input: dict[str, Any],
    callback_context: CallbackContext,
    tool_response: dict[str, Any],
) -> Optional[dict[str, Any]]:
    """Persists looked-up order_id and mock mode flag into session state after lookup_mock_merch_order."""
    state = callback_context.state
    state["is_mock_mode"] = True
    resolved_order = (
        str(tool_response.get("order_id") or input.get("order_id") or "")
        .strip()
        .lstrip("#")
    )
    if resolved_order:
        state["order_id"] = resolved_order
    return None
