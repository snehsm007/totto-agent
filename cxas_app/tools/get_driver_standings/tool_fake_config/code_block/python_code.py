"""Deterministic tool fake for get_driver_standings (no network calls).

CES runs this instead of the real tool only when the session has
useToolFakes (eval toolCallBehaviour=FAKE) AND toolFakeConfig.enableFakeMode.
Every payload carries "_fake": True plus a source label so recorded tool
results can be told apart from real OpenF1-backed results.
"""

from typing import Any

FAKE_SOURCE = "FAKE: get_driver_standings tool_fake_config fixture (deterministic, no network)"


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
            "error_message": "Standings fake produced no payload.",
        }
    payload["_fake"] = True
    payload["fake_source"] = FAKE_SOURCE
    return payload


def _fake_payload(input: Any) -> dict[str, Any]:
    """Returns a deterministic offline championship standings response without network I/O."""
    params = input if isinstance(input, dict) else {}
    try:
        season_int = int(params.get("season", 2026))
    except (TypeError, ValueError):
        return {
            "status": "error",
            "agent_action": "EXPLAIN_INVALID_SEASON",
            "error_message": "Invalid season provided. Please provide 2026.",
        }
    if season_int != 2026:
        return {
            "status": "error",
            "agent_action": "EXPLAIN_ONLY_2026_SEASON_SUPPORTED",
            "error_message": f"Standings tool only carries the 2026 season snapshot (requested {season_int}).",
        }
    category = str(params.get("category", "all") or "all").strip().lower()
    summary = (
        "Mercedes-AMG Petronas F1 Team leads the 2026 Constructors' Championship in P1 "
        "with 538 points! In the Drivers' Championship, Kimi Antonelli (#12) sits P1 "
        "with 302 points (8 wins, 12 podiums) and George Russell (#63) sits P2 "
        "with 236 points (3 wins, 8 podiums)."
    )
    return {
        "status": "success",
        "season": 2026,
        "category": category,
        "mercedes_summary": summary,
        "summary": summary,
        "constructors": [
            {
                "position": 1,
                "team": "Mercedes-AMG Petronas F1 Team",
                "team_short_name": "Mercedes",
                "points": 538,
                "wins": 11,
                "podiums": 20,
            },
            {
                "position": 2,
                "team": "Scuderia Ferrari",
                "team_short_name": "Ferrari",
                "points": 378,
            },
        ],
        "mercedes_drivers": [
            {
                "position": 1,
                "name": "Kimi Antonelli",
                "number": 12,
                "team": "Mercedes-AMG Petronas F1 Team",
                "points": 302,
                "wins": 8,
                "podiums": 12,
            },
            {
                "position": 2,
                "name": "George Russell",
                "number": 63,
                "team": "Mercedes-AMG Petronas F1 Team",
                "points": 236,
                "wins": 3,
                "podiums": 8,
            },
        ],
        "drivers": [
            {
                "position": 1,
                "name": "Kimi Antonelli",
                "number": 12,
                "team": "Mercedes-AMG Petronas F1 Team",
                "points": 302,
            },
            {
                "position": 2,
                "name": "George Russell",
                "number": 63,
                "team": "Mercedes-AMG Petronas F1 Team",
                "points": 236,
            },
        ],
        "source": "fallback",
        "data_source": "OpenF1 API (2026 Standings Snapshot)",
        "freshness_disclaimer": (
            "Standings and recent results reflect the latest available structured 2026 season data "
            "from OpenF1 rather than live lap-by-lap telemetry."
        ),
        "agent_action": "PRESENT_MERCEDES_FIRST_STANDINGS",
    }
