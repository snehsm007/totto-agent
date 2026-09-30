"""Independent date oracle for Totto's "next race" logic.

Given the OpenF1 2026 calendar (``meetings?year=2026`` and optionally
``sessions?year=2026`` payloads) and an instant ``now``, this module decides
which race meeting is "next". It shares NO code with the agent's tools; tests
compare the tool's answer with this oracle at frozen dates.

Rules (from the PRD's AC1 "next race ... with appropriate timing context" and
the OpenF1 calendar semantics):
  * Testing events are not races: a meeting is a race meeting only if its name
    does not mention "testing" and, when sessions are known, it has a session
    of type "Race".
  * Cancelled meetings (``is_cancelled: true``) are not races.
  * next = the first race meeting (by start) whose ``date_end >= now``; a
    meeting that is under way is still "next" until it ends.
  * After the last race of the season there is no next race (None).
"""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
from typing import Any, Iterable

Meeting = dict[str, Any]
Session = dict[str, Any]


def parse_utc(value: str) -> dt.datetime:
    """Parses an OpenF1 ISO-8601 timestamp into an aware UTC datetime."""
    parsed = dt.datetime.fromisoformat(str(value).strip().replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError(f"timestamp without timezone: {value!r}")
    return parsed.astimezone(dt.timezone.utc)


def _require_aware(now: dt.datetime) -> dt.datetime:
    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    return now.astimezone(dt.timezone.utc)


def load_calendar(fixture_dir: str | Path) -> tuple[list[Meeting], list[Session]]:
    """Loads the captured OpenF1 meetings and sessions payloads."""
    base = Path(fixture_dir)
    meetings = json.loads((base / "meetings_2026.json").read_text(encoding="utf-8"))
    sessions = json.loads((base / "sessions_2026.json").read_text(encoding="utf-8"))
    return meetings, sessions


def _race_session_meeting_keys(sessions: Iterable[Session]) -> set[int]:
    return {int(s["meeting_key"]) for s in sessions if str(s.get("session_type", "")).lower() == "race"}


def is_testing(meeting: Meeting, sessions: Iterable[Session] | None = None) -> bool:
    if "testing" in str(meeting.get("meeting_name", "")).lower():
        return True
    if sessions is not None:
        return int(meeting["meeting_key"]) not in _race_session_meeting_keys(sessions)
    return False


def is_cancelled(meeting: Meeting) -> bool:
    return bool(meeting.get("is_cancelled"))


def race_meetings(meetings: Iterable[Meeting], sessions: Iterable[Session] | None = None) -> list[Meeting]:
    """Race meetings (no testing, not cancelled), ordered by start time."""
    sessions = list(sessions) if sessions is not None else None
    races = [m for m in meetings if not is_cancelled(m) and not is_testing(m, sessions)]
    return sorted(races, key=lambda m: parse_utc(m["date_start"]))


def next_race(meetings: Iterable[Meeting], now: dt.datetime, sessions: Iterable[Session] | None = None) -> Meeting | None:
    """The next race meeting at ``now``, or None when the season is over."""
    now_utc = _require_aware(now)
    for meeting in race_meetings(meetings, sessions):
        if parse_utc(meeting["date_end"]) >= now_utc:
            return meeting
    return None


def meeting_status(meeting: Meeting, now: dt.datetime) -> str:
    """'completed' | 'in_progress' | 'upcoming' relative to ``now``."""
    now_utc = _require_aware(now)
    if parse_utc(meeting["date_end"]) < now_utc:
        return "completed"
    if parse_utc(meeting["date_start"]) <= now_utc:
        return "in_progress"
    return "upcoming"


def sessions_of(meeting_key: int, sessions: Iterable[Session]) -> list[Session]:
    """Sessions of one meeting ordered by start time."""
    return sorted((s for s in sessions if int(s["meeting_key"]) == int(meeting_key)), key=lambda s: parse_utc(s["date_start"]))
