"""Deterministic tool fake for get_race_schedule (no network calls).

CES runs this instead of the real tool only when the session has
useToolFakes (eval toolCallBehaviour=FAKE) AND toolFakeConfig.enableFakeMode.
It never calls OpenF1: race data comes from the compact 2026 calendar fixture
below (FP1/Qualifying/Race UTC start times copied from the real tool's bundled
2026 snapshot). The output is a pure function of (input, current UTC date):
"next" means the first 2026 weekend that has not ended yet, exactly like the
real tool. Every payload carries "_fake": True plus a source label so recorded
tool results can be told apart from real OpenF1-backed results.
"""

from datetime import datetime, timezone
import re
from typing import Any
import unicodedata
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError, available_timezones

FAKE_SOURCE = "FAKE: get_race_schedule tool_fake_config fixture (deterministic, no network)"

# (meeting_key, round, name, location, country, circuit, fp1_utc, quali_utc, race_utc)
FAKE_CALENDAR_2026 = (
    (1279, 1, "Australian Grand Prix", "Melbourne", "Australia", "Albert Park Grand Prix Circuit", "2026-03-06T01:30", "2026-03-07T05:00", "2026-03-08T04:00"),
    (1280, 2, "Chinese Grand Prix", "Shanghai", "China", "Shanghai International Circuit", "2026-03-13T03:30", "2026-03-14T07:00", "2026-03-15T07:00"),
    (1281, 3, "Japanese Grand Prix", "Suzuka", "Japan", "Suzuka International Racing Course", "2026-03-27T02:30", "2026-03-28T06:00", "2026-03-29T05:00"),
    (1284, 4, "Miami Grand Prix", "Miami Gardens", "United States", "Miami International Autodrome", "2026-05-01T16:00", "2026-05-02T20:00", "2026-05-03T17:00"),
    (1285, 5, "Canadian Grand Prix", "Montreal", "Canada", "Circuit Gilles-Villeneuve", "2026-05-22T16:30", "2026-05-23T20:00", "2026-05-24T20:00"),
    (1286, 6, "Monaco Grand Prix", "Monte Carlo", "Monaco", "Circuit de Monaco", "2026-06-05T11:30", "2026-06-06T14:00", "2026-06-07T13:00"),
    (1287, 7, "Barcelona Grand Prix", "Barcelona", "Spain", "Circuit de Barcelona-Catalunya", "2026-06-12T11:30", "2026-06-13T14:00", "2026-06-14T13:00"),
    (1288, 8, "Austrian Grand Prix", "Spielberg", "Austria", "Red Bull Ring", "2026-06-26T11:30", "2026-06-27T14:00", "2026-06-28T13:00"),
    (1289, 9, "British Grand Prix", "Silverstone", "United Kingdom", "Silverstone Circuit", "2026-07-03T11:30", "2026-07-04T15:00", "2026-07-05T14:00"),
    (1290, 10, "Belgian Grand Prix", "Spa-Francorchamps", "Belgium", "Circuit de Spa-Francorchamps", "2026-07-17T11:30", "2026-07-18T14:00", "2026-07-19T13:00"),
    (1291, 11, "Hungarian Grand Prix", "Budapest", "Hungary", "Hungaroring", "2026-07-24T11:30", "2026-07-25T14:00", "2026-07-26T13:00"),
    (1292, 12, "Dutch Grand Prix", "Zandvoort", "Netherlands", "Circuit Zandvoort", "2026-08-21T10:30", "2026-08-22T14:00", "2026-08-23T13:00"),
    (1293, 13, "Italian Grand Prix", "Monza", "Italy", "Autodromo Nazionale Monza", "2026-09-04T10:30", "2026-09-05T14:00", "2026-09-06T13:00"),
    (1294, 14, "Spanish Grand Prix", "Madrid", "Spain", "Madring Street Circuit", "2026-09-11T11:30", "2026-09-12T14:00", "2026-09-13T13:00"),
    (1295, 15, "Azerbaijan Grand Prix", "Baku", "Azerbaijan", "Baku City Circuit", "2026-09-24T08:30", "2026-09-25T12:00", "2026-09-26T11:00"),
    (1308, 16, "Bahrain Grand Prix", "Kuala Lumpur", "Bahrain", "Sepang International Circuit", "2026-10-02T04:30", "2026-10-03T08:00", "2026-10-04T07:00"),
    (1296, 17, "Singapore Grand Prix", "Marina Bay", "Singapore", "Marina Bay Street Circuit", "2026-10-09T08:30", "2026-10-10T13:00", "2026-10-11T12:00"),
    (1297, 18, "United States Grand Prix", "Austin", "United States", "Circuit of the Americas", "2026-10-23T17:30", "2026-10-24T21:00", "2026-10-25T20:00"),
    (1298, 19, "Mexico City Grand Prix", "Mexico City", "Mexico", "Autodromo Hermanos Rodriguez", "2026-10-30T18:30", "2026-10-31T21:00", "2026-11-01T20:00"),
    (1299, 20, "Sao Paulo Grand Prix", "Sao Paulo", "Brazil", "Autodromo Jose Carlos Pace (Interlagos)", "2026-11-06T15:30", "2026-11-07T18:00", "2026-11-08T17:00"),
    (1300, 21, "Las Vegas Grand Prix", "Las Vegas", "United States", "Las Vegas Strip Circuit", "2026-11-20T00:30", "2026-11-21T04:00", "2026-11-22T04:00"),
    (1301, 22, "Qatar Grand Prix", "Lusail", "Qatar", "Lusail International Circuit", "2026-11-27T13:30", "2026-11-28T18:00", "2026-11-29T16:00"),
    (1302, 23, "Abu Dhabi Grand Prix", "Yas Marina", "United Arab Emirates", "Yas Marina Circuit", "2026-12-04T09:30", "2026-12-05T14:00", "2026-12-06T13:00"),
)

# Extra query keywords (normalized ASCII) per meeting key.
FAKE_RACE_KEYWORDS = {
    1279: ("australia", "australian", "melbourne", "albert park"),
    1280: ("china", "chinese", "shanghai"),
    1281: ("japan", "japanese", "suzuka"),
    1284: ("miami",),
    1285: ("canada", "canadian", "montreal"),
    1286: ("monaco", "monte carlo"),
    1287: ("barcelona", "catalunya"),
    1288: ("austria", "austrian", "spielberg", "red bull ring"),
    1289: ("britain", "british", "silverstone", "united kingdom", "uk"),
    1290: ("belgium", "belgian", "spa", "spa-francorchamps"),
    1291: ("hungary", "hungarian", "budapest", "hungaroring"),
    1292: ("netherlands", "dutch", "zandvoort"),
    1293: ("italy", "italian", "monza"),
    1294: ("spain", "spanish", "madrid", "madring"),
    1295: ("azerbaijan", "baku"),
    1308: ("bahrain", "kuala lumpur", "malaysia", "sepang"),
    1296: ("singapore", "marina bay"),
    1297: ("united states grand prix", "usgp", "austin", "cota", "americas"),
    1298: ("mexico", "mexican", "mexico city"),
    1299: ("brazil", "brazilian", "sao paulo", "interlagos"),
    1300: ("las vegas", "vegas"),
    1301: ("qatar", "lusail"),
    1302: ("abu dhabi", "yas marina", "uae"),
}

FAKE_NEXT_SYNONYMS = (
    "next",
    "upcoming",
    "next race",
    "upcoming race",
    "current",
    "next grand prix",
    "upcoming grand prix",
    "schedule",
    "calendar",
)

FAKE_TZ_ALIASES = {
    "edinburgh": "Europe/London",
    "scotland": "Europe/London",
    "uk": "Europe/London",
    "mumbai": "Asia/Kolkata",
    "delhi": "Asia/Kolkata",
    "india": "Asia/Kolkata",
    "est": "America/New_York",
    "edt": "America/New_York",
    "pst": "America/Los_Angeles",
    "pdt": "America/Los_Angeles",
    "cet": "Europe/Paris",
    "cest": "Europe/Paris",
    "bst": "Europe/London",
    "jst": "Asia/Tokyo",
    "aest": "Australia/Sydney",
}


def fake_tool_call(
    tool: Any,
    input: dict[str, Any],
    callback_context: Any,
) -> dict[str, Any]:
    """Platform tool-fake entry point; marks every payload as fake."""
    try:
        payload = _fake_payload(input, datetime.now(timezone.utc))
    except Exception as exc:  # noqa: BLE001 - a fake must always answer with a dict
        payload = {
            "status": "error",
            "agent_action": "APOLOGIZE_TOOL_UNAVAILABLE",
            "error_message": f"Race schedule fake failed: {type(exc).__name__}",
        }
    if not isinstance(payload, dict):
        payload = {
            "status": "error",
            "agent_action": "APOLOGIZE_TOOL_UNAVAILABLE",
            "error_message": "Race schedule fake produced no payload.",
        }
    payload["_fake"] = True
    payload["fake_source"] = FAKE_SOURCE
    return payload


def _norm(value: str) -> str:
    text = unicodedata.normalize("NFKD", str(value)).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9\s-]", " ", text.lower())).strip()


def _utc(stamp: str) -> datetime:
    return datetime.fromisoformat(stamp).replace(tzinfo=timezone.utc)


def _select(query: str, now_utc: datetime) -> tuple[Any, bool]:
    """Returns (calendar row or None, query_was_next)."""
    q = _norm(query)
    if q in FAKE_NEXT_SYNONYMS or not q:
        for row in FAKE_CALENDAR_2026:
            if _utc(row[8]) >= now_utc:
                return row, True
        return None, True
    for row in FAKE_CALENDAR_2026:
        for kw in FAKE_RACE_KEYWORDS.get(row[0], ()):
            if re.search(rf"\b{re.escape(kw)}\b", q):
                return row, False
    return None, False


def _resolve_tz(raw: str) -> str:
    cleaned = str(raw or "").strip()
    if not cleaned or cleaned.upper() in ("UTC", "UNKNOWN", "Z", "GMT"):
        return "UTC"
    candidate = cleaned.split("(")[0].strip()
    if "/" in candidate:
        try:
            ZoneInfo(candidate)
            return candidate
        except (ZoneInfoNotFoundError, ValueError):
            pass
    norm = _norm(cleaned)
    for alias in sorted(FAKE_TZ_ALIASES, key=len, reverse=True):
        if re.search(rf"\b{re.escape(alias)}\b", norm):
            return FAKE_TZ_ALIASES[alias]
    cities = {}
    for zone in available_timezones():
        if "/" in zone and not zone.startswith(("Etc/", "SystemV/", "US/")):
            cities.setdefault(_norm(zone.rsplit("/", 1)[-1].replace("_", " ")), zone)
    for city in sorted(cities, key=len, reverse=True):
        if len(city) >= 4 and re.search(rf"\b{re.escape(city)}\b", norm):
            return cities[city]
    return "UTC"


def _fake_payload(input: Any, now_utc: datetime) -> dict[str, Any]:
    """Returns a deterministic offline race schedule response without network I/O."""
    params = input if isinstance(input, dict) else {}
    race_query = str(params.get("race_query", "next") or "").strip()
    user_timezone = str(params.get("user_timezone", "UTC") or "").strip() or "UTC"
    if not race_query:
        return {
            "status": "error",
            "agent_action": "ASK_RACE_NAME",
            "error_message": "No race query provided. Please specify a Grand Prix name or 'next'.",
        }
    row, was_next = _select(race_query, now_utc)
    if row is None and was_next:
        return {
            "status": "error",
            "season": 2026,
            "season_completed": True,
            "is_completed": True,
            "meeting_state": "completed",
            "agent_action": "SEASON_2026_CONCLUDED",
            "error_message": "The 2026 Formula 1 season has concluded (final race: Abu Dhabi Grand Prix on December 6, 2026).",
        }
    if row is None:
        return {
            "status": "error",
            "agent_action": "CLARIFY_RACE_NAME",
            "error_message": (
                f"No 2026 Formula 1 Grand Prix found matching '{race_query}'. "
                "Please specify a valid 2026 Grand Prix, circuit, country, or 'next'."
            ),
        }
    m_key, round_no, name, location, country, circuit, fp1, quali, race = row
    iana = _resolve_tz(user_timezone)
    needs_tz = iana == "UTC"
    tz_obj = ZoneInfo(iana)
    sessions = []
    for label, stamp in (("Practice 1", fp1), ("Qualifying", quali), ("Race", race)):
        dt_utc = _utc(stamp)
        dt_local = dt_utc.astimezone(tz_obj)
        tz_label = "UTC" if needs_tz else f"{dt_local.strftime('%Z')} ({iana.rsplit('/', 1)[-1].replace('_', ' ')})"
        sessions.append(
            {
                "session": label,
                "day": dt_utc.strftime("%A"),
                "local_day": dt_local.strftime("%A"),
                "date_utc": dt_utc.strftime("%Y-%m-%d"),
                "local_date": dt_local.strftime("%Y-%m-%d"),
                "utc_time": dt_utc.strftime("%Y-%m-%d %H:%M UTC"),
                "time_utc": dt_utc.strftime("%H:%M UTC"),
                "local_time": f"{dt_local.strftime('%H:%M')} {tz_label}",
                "timezone_label": tz_label,
            }
        )
    first, last = _utc(fp1), _utc(race)
    is_completed = last < now_utc
    return {
        "status": "success",
        "season": 2026,
        "round": round_no,
        "meeting_key": m_key,
        "race_name": name,
        "circuit_name": circuit,
        "circuit": circuit,
        "location": f"{location}, {country}",
        "dates": f"{first.strftime('%B')} {first.day} - {last.strftime('%B')} {last.day}, 2026",
        "is_completed": is_completed,
        "meeting_state": "completed" if is_completed else "upcoming",
        "timezone_requested": user_timezone,
        "user_timezone_resolved": iana,
        "timezone_resolved": iana,
        "needs_timezone_clarification": needs_tz,
        "sessions": sessions,
        "typical_weather": {
            "condition": "Typical seasonal conditions for this circuit (fixture, not a forecast)",
            "source": "typical_circuit_climate_profile",
        },
        "mercedes_highlights": (
            "Mercedes-AMG Petronas F1 Team leads the 2026 Constructors' Championship (538 pts) "
            "with Kimi Antonelli (#12, P1 with 302 pts) and George Russell (#63, P2 with 236 pts)."
        ),
        "source": "fallback",
        "relocation_note": (
            "The 2026 Bahrain Grand Prix was relocated from Sakhir to the Sepang International "
            "Circuit in Malaysia and keeps the Bahrain Grand Prix name."
            if m_key == 1308
            else ""
        ),
        "data_source": "OpenF1 API (2026 Season Snapshot)",
        "freshness_disclaimer": (
            "Race schedule, session times, and weather reflect the latest available structured "
            "2026 season data from OpenF1 rather than live lap-by-lap telemetry."
        ),
        "agent_action": (
            "ASK_USER_TIMEZONE_BEFORE_LOCAL_TIMES" if needs_tz else "SHARE_LOCALIZED_RACE_SCHEDULE"
        ),
    }
