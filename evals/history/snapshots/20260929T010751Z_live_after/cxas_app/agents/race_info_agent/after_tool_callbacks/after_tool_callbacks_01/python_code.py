from typing import Any, Optional


def after_tool_callback(
    tool: Tool,
    input: dict[str, Any],
    callback_context: CallbackContext,
    tool_response: dict[str, Any],
) -> Optional[dict[str, Any]]:
    """Persists resolved timezone and user location into session state after get_race_schedule."""
    state = callback_context.state
    req_tz = str(input.get("user_timezone") or "").strip()
    resolved_tz = str(tool_response.get("timezone_resolved") or "").strip()
    if req_tz and req_tz.upper() not in ("", "UTC", "UNKNOWN"):
        state["user_timezone"] = resolved_tz or req_tz
        state["user_location"] = req_tz
    elif "user_timezone" not in state:
        state["user_timezone"] = resolved_tz or "UTC"
    return None
