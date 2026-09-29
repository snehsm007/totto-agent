"""Formula 1 driver and constructor championship standings tool for Totto, Mercedes F1 Fan Agent."""

from typing import Any


VALID_CATEGORIES = {"all", "drivers", "constructors", "mercedes"}


def get_driver_standings(
    season: int = 2026, category: str = "all"
) -> dict[str, Any]:
    """Retrieves Formula 1 Constructor and Driver Championship standings with Mercedes context first.

    Before calling this tool, speak a brief conversational pacing phrase:
    Let me pull up the latest championship standings.

    Args:
        season: Championship year (default 2026, valid range 1950-2030).
        category: Standings filter ('all', 'drivers', 'constructors', or 'mercedes').

    Returns:
        Dictionary containing Mercedes-first constructor and driver standings and recent performance.
    """
    try:
        season_int = int(season)
    except (TypeError, ValueError):
        return {
            "status": "error",
            "agent_action": "EXPLAIN_INVALID_SEASON",
            "error_message": f"Invalid season '{season}'. Please provide a valid year between 1950 and 2030.",
        }

    if season_int < 1950 or season_int > 2030:
        return {
            "status": "error",
            "agent_action": "EXPLAIN_INVALID_SEASON",
            "error_message": f"Season {season_int} is out of valid Formula 1 range (1950-2030).",
        }

    clean_cat = str(category or "all").strip().lower()
    if clean_cat not in VALID_CATEGORIES:
        return {
            "status": "error",
            "agent_action": "EXPLAIN_INVALID_CATEGORY",
            "error_message": (
                f"Unsupported standings category '{category}'. "
                "Valid categories are: all, drivers, constructors, mercedes."
            ),
        }

    constructors = [
        {
            "position": 1,
            "team": "Mercedes-AMG Petronas F1 Team",
            "points": 285,
            "wins": 3,
            "podiums": 12,
        },
        {
            "position": 2,
            "team": "McLaren Formula 1 Team",
            "points": 272,
            "wins": 3,
            "podiums": 10,
        },
        {
            "position": 3,
            "team": "Scuderia Ferrari",
            "points": 258,
            "wins": 2,
            "podiums": 9,
        },
        {
            "position": 4,
            "team": "Oracle Red Bull Racing",
            "points": 240,
            "wins": 3,
            "podiums": 8,
        },
    ]

    mercedes_drivers = [
        {
            "position": 2,
            "name": "George Russell",
            "number": 63,
            "team": "Mercedes-AMG Petronas F1 Team",
            "points": 150,
            "wins": 2,
            "podiums": 7,
        },
        {
            "position": 4,
            "name": "Kimi Antonelli",
            "number": 12,
            "team": "Mercedes-AMG Petronas F1 Team",
            "points": 135,
            "wins": 1,
            "podiums": 5,
        },
    ]

    drivers = [
        {
            "position": 1,
            "name": "Lando Norris",
            "team": "McLaren Formula 1 Team",
            "points": 156,
        },
        mercedes_drivers[0],
        {
            "position": 3,
            "name": "Charles Leclerc",
            "team": "Scuderia Ferrari",
            "points": 142,
        },
        mercedes_drivers[1],
        {
            "position": 5,
            "name": "Max Verstappen",
            "team": "Oracle Red Bull Racing",
            "points": 131,
        },
    ]

    mercedes_summary = (
        "Mercedes-AMG Petronas F1 Team leads the 2026 Constructors' Championship in P1 with 285 points! "
        "George Russell is P2 in the Drivers' Championship with 150 points (2 wins, 7 podiums) and "
        "Kimi Antonelli sits P4 with 135 points (1 win, 5 podiums)."
    )

    return {
        "status": "success",
        "season": season_int,
        "category": clean_cat,
        "mercedes_summary": mercedes_summary,
        "summary": mercedes_summary,
        "constructors": constructors,
        "mercedes_drivers": mercedes_drivers,
        "drivers": drivers,
        "recent_performance": (
            "In the most recent race weekend at the Austrian Grand Prix, George Russell claimed P1 "
            "and Kimi Antonelli finished P3, securing a double Silver Arrows podium and extending "
            "Mercedes's lead at the top of the Constructors' Championship."
        ),
        "data_source": "OpenF1 Standings Feed (Sandbox Fixture)",
        "freshness_disclaimer": (
            "Standings and recent results reflect the latest available structured 2026 season snapshot "
            "rather than live telemetry."
        ),
        "agent_action": "PRESENT_MERCEDES_FIRST_STANDINGS",
    }
