"""Deterministic tool fake for get_official_links.

CES runs this instead of the real tool only when the session has
useToolFakes (eval toolCallBehaviour=FAKE) AND toolFakeConfig.enableFakeMode.
Every payload carries "_fake": True plus a source label so recorded tool
results can be told apart from real results.
"""

from typing import Any

FAKE_SOURCE = "FAKE: get_official_links tool_fake_config fixture (deterministic, no network)"


def fake_tool_call(
    tool: Any,
    input: dict[str, Any],
    callback_context: Any,
) -> dict[str, Any]:
    """Platform tool-fake entry point; marks every payload as fake."""
    payload = _fake_payload(input)
    if not isinstance(payload, dict):
        payload = {
            "status": "error",
            "agent_action": "APOLOGIZE_TOOL_UNAVAILABLE",
            "error_message": "Links fake produced no payload.",
        }
    payload["_fake"] = True
    payload["fake_source"] = FAKE_SOURCE
    return payload


def _fake_payload(input: Any) -> dict[str, Any]:
    """Returns deterministic official Formula 1 and Mercedes-AMG Petronas F1 links."""
    params = input if isinstance(input, dict) else {}
    category = str(params.get("category", "all") or "all").strip().lower()
    links = {
        "ticketing": {
            "title": "Official Formula 1 Tickets",
            "url": "https://tickets.formula1.com",
            "guidance": "Visit the official Formula 1 ticketing portal for live seat availability and pricing. Totto cannot check inventory or quote prices.",
        },
        "merch": {
            "title": "Official Mercedes-AMG Petronas F1 Team Store",
            "url": "https://shop.mercedesamgf1.com",
            "guidance": "Explore official Silver Arrows teamwear on the official store.",
        },
        "team": {
            "title": "Mercedes-AMG Petronas F1 Official Hub",
            "url": "https://www.mercedesamgf1.com",
            "guidance": "Follow official Mercedes-AMG PETRONAS F1 news and fan updates.",
        },
    }
    return {
        "status": "success",
        "category": category,
        "links": links,
        "result": links.get(category, links["ticketing"]),
        "non_transactional_disclaimer": "Totto provides official referral links only and does not sell tickets or merchandise.",
        "agent_action": "PROVIDE_OFFICIAL_LINKS",
    }
