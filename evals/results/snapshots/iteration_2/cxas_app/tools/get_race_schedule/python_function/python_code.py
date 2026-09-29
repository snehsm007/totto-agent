"""Formula 1 race schedule and session timing tool for Totto, Mercedes F1 Fan Agent."""

from typing import Any


TIMEZONE_OFFSETS: dict[str, tuple[int, str]] = {
    "UTC": (0, "UTC"),
    "GMT": (0, "GMT"),
    "BST": (1, "BST (London)"),
    "EUROPE/LONDON": (1, "BST (London)"),
    "LONDON": (1, "BST (London)"),
    "UK": (1, "BST (London)"),
    "CET": (2, "CEST (Central Europe)"),
    "CEST": (2, "CEST (Central Europe)"),
    "EUROPE/BERLIN": (2, "CEST (Berlin)"),
    "BERLIN": (2, "CEST (Berlin)"),
    "GERMANY": (2, "CEST (Berlin)"),
    "EUROPE/PARIS": (2, "CEST (Paris)"),
    "PARIS": (2, "CEST (Paris)"),
    "EUROPE/MADRID": (2, "CEST (Madrid)"),
    "MADRID": (2, "CEST (Madrid)"),
    "EST": (-4, "EDT (New York)"),
    "EDT": (-4, "EDT (New York)"),
    "AMERICA/NEW_YORK": (-4, "EDT (New York)"),
    "NEW YORK": (-4, "EDT (New York)"),
    "CST": (-5, "CDT (Chicago)"),
    "CDT": (-5, "CDT (Chicago)"),
    "AMERICA/CHICAGO": (-5, "CDT (Chicago)"),
    "PST": (-7, "PDT (Los Angeles)"),
    "PDT": (-7, "PDT (Los Angeles)"),
    "AMERICA/LOS_ANGELES": (-7, "PDT (Los Angeles)"),
    "LOS ANGELES": (-7, "PDT (Los Angeles)"),
    "JST": (9, "JST (Tokyo)"),
    "ASIA/TOKYO": (9, "JST (Tokyo)"),
    "TOKYO": (9, "JST (Tokyo)"),
}

RACE_FIXTURES: dict[str, dict[str, Any]] = {
    "british": {
        "round": 12,
        "race_name": "British Grand Prix",
        "circuit_name": "Silverstone Circuit",
        "location": "Silverstone, United Kingdom",
        "Dates": "July 3 - July 5, 2026",
        "mercedes_highlights": (
            "Silverstone is the home race for Brackley-based Mercedes-AMG Petronas F1 Team! "
            "George Russell took pole position here in 2024 and enters the weekend P2 in the "
            "Drivers' Championship (150 pts), while Kimi Antonelli sits P4 (135 pts) as "
            "Mercedes leads the Constructors' Championship with 285 points."
        ),
    },
    "monaco": {
        "round": 8,
        "race_name": "Monaco Grand Prix",
        "circuit_name": "Circuit de Monaco",
        "location": "Monte Carlo, Monaco",
        "Dates": "May 22 - May 24, 2026",
        "mercedes_highlights": (
            "Mercedes-AMG Petronas F1 Team scored a double top-five finish in Monte Carlo "
            "with high-downforce W17 upgrades."
        ),
    },
    "italian": {
        "round": 16,
        "race_name": "Italian Grand Prix",
        "circuit_name": "Autodromo Nazionale Monza",
        "location": "Monza, Italy",
        "Dates": "September 4 - September 6, 2026",
        "mercedes_highlights": (
            "Monza is Kimi Antonelli's home Grand Prix in Italy, featuring Mercedes low-drag "
            "aero configuration."
        ),
    },
}


def get_race_schedule(
    race_query: str = "next", user_timezone: str = ""
) -> dict[str, Any]:
    """Fetches Formula 1 race schedule, session times, weather forecast, and Mercedes context.

    Before calling this tool, speak a brief conversational pacing phrase:
    Let me check the race schedule for you.

    Args:
        race_query: Name of the Grand Prix (e.g., 'next', 'British Grand Prix', 'Silverstone').
        user_timezone: User's timezone or city (e.g., 'EST', 'America/New_York', 'Europe/London').

    Returns:
        Dictionary containing structured race weekend sessions, weather, and Mercedes highlights.
    """
    clean_query = str(race_query).strip()
    if not clean_query:
        return {
            "status": "error",
            "agent_action": "ASK_RACE_NAME",
            "error_message": "No race query provided. Please specify a Grand Prix name or 'next'.",
        }

    tz_raw = str(user_timezone).strip()
    tz_key = tz_raw.upper()
    needs_tz_clarification = tz_key in ("", "UNKNOWN", "UTC")
    offset_hours, tz_label = TIMEZONE_OFFSETS.get(tz_key, (0, "UTC"))

    q_lower = clean_query.lower()
    if "monaco" in q_lower:
        fixture = RACE_FIXTURES["monaco"]
    elif "monza" in q_lower or "ital" in q_lower:
        fixture = RACE_FIXTURES["italian"]
    else:
        fixture = RACE_FIXTURES["british"]

    base_sessions = [
        {"session": "Practice 1", "day": "Friday", "time_utc": "11:30 UTC"},
        {"session": "Practice 2", "day": "Friday", "time_utc": "15:00 UTC"},
        {"session": "Practice 3", "day": "Saturday", "time_utc": "10:30 UTC"},
        {"session": "Qualifying", "day": "Saturday", "time_utc": "14:00 UTC"},
        {"session": "Grand Prix (Race)", "day": "Sunday", "time_utc": "14:00 UTC"},
    ]

    sessions = []
    for s in base_sessions:
        parts = s["time_utc"].replace(" UTC", "").strip().split(":")
        converted_hour = (int(parts[0]) + offset_hours) % 24
        local_hhmm = f"{converted_hour:02d}:{int(parts[1]):02d}"
        sessions.append(
            {
                "session": s["session"],
                "day": s["day"],
                "time_utc": s["time_utc"],
                "local_time": f"{local_hhmm} {tz_label}",
                "timezone_label": tz_label,
            }
        )

    return {
        "status": "success",
        "season": 2026,
        "round": fixture["round"],
        "race_name": fixture["race_name"],
        "circuit_name": fixture["circuit_name"],
        "circuit": fixture["circuit_name"],
        "location": fixture["location"],
        "dates": fixture["Dates"],
        "timezone_requested": tz_raw or "UTC",
        "timezone_resolved": tz_label,
        "needs_timezone_clarification": needs_tz_clarification,
        "sessions": sessions,
        "weather_forecast": {
            "condition": "Partly Cloudy with cool breeze",
            "air_temp_c": 21,
            "track_temp_c": 28,
            "rain_probability": "35%",
        },
        "mercedes_highlights": fixture["mercedes_highlights"],
        "data_source": "OpenF1 API (Cached/Simulated for Sandbox)",
        "freshness_disclaimer": (
            "Race schedule and weather reflect the latest available structured 2026 season snapshot "
            "rather than live lap-by-lap telemetry."
        ),
        "agent_action": (
            "ASK_USER_TIMEZONE_BEFORE_LOCAL_TIMES"
            if needs_tz_clarification
            else "SHARE_LOCALIZED_RACE_SCHEDULE"
        ),
    }
