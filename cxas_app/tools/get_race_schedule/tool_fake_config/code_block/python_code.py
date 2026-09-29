"""Deterministic tool fake for get_race_schedule (no network calls)."""

from typing import Any


def fake_tool_call(
    tool: Any,
    input: dict[str, Any],
    callback_context: Any,
) -> dict[str, Any]:
    """Returns a deterministic offline race schedule response without network I/O."""
    params = input if isinstance(input, dict) else {}
    race_query = str(params.get("race_query", "next")).strip()
    user_timezone = str(params.get("user_timezone", "UTC")).strip() or "UTC"
    if not race_query:
        return {
            "status": "error",
            "agent_action": "ASK_RACE_NAME",
            "error_message": "No race query provided. Please specify a Grand Prix name or 'next'.",
        }
    needs_tz = user_timezone.upper() in ("", "UNKNOWN", "UTC")
    return {
        "status": "success",
        "season": 2026,
        "round": 17,
        "meeting_key": 1296,
        "race_name": "Singapore Grand Prix",
        "circuit_name": "Marina Bay Street Circuit",
        "circuit": "Marina Bay Street Circuit",
        "location": "Marina Bay, Singapore",
        "dates": "October 9 - October 11, 2026",
        "is_completed": False,
        "meeting_state": "upcoming",
        "timezone_requested": user_timezone,
        "user_timezone_resolved": "UTC" if needs_tz else user_timezone,
        "timezone_resolved": "UTC" if needs_tz else user_timezone,
        "needs_timezone_clarification": needs_tz,
        "sessions": [
            {
                "session": "Practice 1",
                "day": "Friday",
                "local_day": "Friday",
                "date_utc": "2026-10-09",
                "utc_time": "2026-10-09 08:30 UTC",
                "time_utc": "08:30 UTC",
                "local_time": "08:30 UTC",
                "timezone_label": "UTC",
            },
            {
                "session": "Qualifying",
                "day": "Saturday",
                "local_day": "Saturday",
                "date_utc": "2026-10-10",
                "utc_time": "2026-10-10 13:00 UTC",
                "time_utc": "13:00 UTC",
                "local_time": "13:00 UTC",
                "timezone_label": "UTC",
            },
            {
                "session": "Race",
                "day": "Sunday",
                "local_day": "Sunday",
                "date_utc": "2026-10-11",
                "utc_time": "2026-10-11 12:00 UTC",
                "time_utc": "12:00 UTC",
                "local_time": "12:00 UTC",
                "timezone_label": "UTC",
            },
        ],
        "typical_weather": {
            "condition": "Typical Marina Bay night conditions: Tropical Evening (High Humidity)",
            "air_temp_c": 29,
            "track_temp_c": 33,
            "humidity_pct": 78,
            "rain_probability": "40%",
            "source": "typical_circuit_climate_profile",
        },
        "mercedes_highlights": (
            "Mercedes-AMG Petronas F1 Team enters the Singapore Grand Prix P1 in the "
            "2026 Constructors' Championship (538 pts) with Kimi Antonelli (#12, P1 with 302 pts) "
            "and George Russell (#63, P2 with 236 pts)."
        ),
        "data_source": "OpenF1 API (2026 Season Snapshot)",
        "freshness_disclaimer": (
            "Race schedule, session times, and weather reflect the latest available structured "
            "2026 season data from OpenF1 rather than live lap-by-lap telemetry."
        ),
        "agent_action": (
            "ASK_USER_TIMEZONE_BEFORE_LOCAL_TIMES"
            if needs_tz
            else "SHARE_LOCALIZED_RACE_SCHEDULE"
        ),
    }
