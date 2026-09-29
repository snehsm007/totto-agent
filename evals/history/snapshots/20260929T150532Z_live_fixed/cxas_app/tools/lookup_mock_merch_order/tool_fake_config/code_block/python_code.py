"""Deterministic tool fake for lookup_mock_merch_order."""

from typing import Any


def fake_tool_call(
    tool: Any,
    input: dict[str, Any],
    callback_context: Any,
) -> dict[str, Any]:
    """Returns a deterministic mocked merchandise order lookup response."""
    params = input if isinstance(input, dict) else {}
    raw_id = str(params.get("order_id", "") or "").strip().lstrip("#")
    if raw_id in ("1001", "1002", "1003"):
        status_map = {
            "1001": "Delivered",
            "1002": "In Transit",
            "1003": "Return In Progress",
        }
        return {
            "status": "success",
            "found": True,
            "order_id": raw_id,
            "order": {
                "order_id": raw_id,
                "status": status_map[raw_id],
                "item": "Mercedes-AMG Petronas F1 Team Gear",
                "carrier": "DHL Express",
                "tracking_number": "DHL-MB-984210",
                "return_eligible": True,
                "is_mock_data": True,
                "is_mock": True,
            },
            "is_mock_data": True,
            "is_mock": True,
            "disclaimer": "Note: This order data is mocked and simulated for demonstration purposes only.",
            "agent_action": "SHARE_MOCK_ORDER_DETAILS",
        }
    return {
        "status": "error",
        "found": False,
        "order_id": raw_id,
        "agent_action": "OFFER_SAMPLE_ORDER_IDS" if raw_id else "PROMPT_FOR_ORDER_ID",
        "error_message": "Order not found in demo system. Try #1001, #1002, or #1003.",
        "sample_order_ids": ["1001", "1002", "1003"],
        "is_mock_data": True,
        "is_mock": True,
        "disclaimer": "Note: This order data is mocked and simulated for demonstration purposes only.",
    }
