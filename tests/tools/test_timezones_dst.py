"""Timezone conversion at DST boundaries and for unseen cities (TR-10, PRD AC7).

Session instants come from the captured OpenF1 sessions; the expected local
times are hand-verified from the IANA rules for 2026:
  * Europe/London leaves BST on Sun 2026-10-25 01:00 UTC,
  * America/New_York leaves EDT on Sun 2026-11-01 06:00 UTC,
  * Australia/Sydney enters AEDT on Sun 2026-10-04 02:00 local (Sat 16:00 UTC).
"""

import datetime as dt

import pytest

from totto_suite import oracle

SEP_28 = dt.datetime(2026, 9, 28, 12, 0, tzinfo=dt.timezone.utc)


def _fixture_session(openf1_calendar, location: str, session_name: str) -> dt.datetime:
    meeting = next(m for m in openf1_calendar["meetings"] if m["location"] == location and not m.get("is_cancelled"))
    session = next(s for s in oracle.sessions_of(meeting["meeting_key"], openf1_calendar["sessions"]) if s["session_name"] == session_name)
    return oracle.parse_utc(session["date_start"])


def _session(res: dict, name: str) -> dict:
    return next(s for s in res["sessions"] if s["session"] == name)


@pytest.mark.finding("TR-10", "PRD-AC7")
@pytest.mark.parametrize(
    "race_query,location,tz_input,session,utc_iso,local_hhmm,abbr,local_day",
    [
        # US GP weekend straddles the end of British Summer Time.
        ("United States Grand Prix", "Austin", "London", "Qualifying", "2026-10-24T21:00", "22:00", "BST", "Saturday"),
        ("United States Grand Prix", "Austin", "London", "Race", "2026-10-25T20:00", "20:00", "GMT", "Sunday"),
        # Mexico City weekend straddles the end of US Eastern Daylight Time.
        ("Mexico City Grand Prix", "Mexico City", "New York", "Qualifying", "2026-10-31T21:00", "17:00", "EDT", "Saturday"),
        ("Mexico City Grand Prix", "Mexico City", "New York", "Race", "2026-11-01T20:00", "15:00", "EST", "Sunday"),
        # Sydney in July (AEST) vs October (AEDT).
        ("British Grand Prix", "Silverstone", "Sydney", "Qualifying", "2026-07-04T15:00", "01:00", "AEST", "Sunday"),
        ("Singapore Grand Prix", "Marina Bay", "Sydney", "Race", "2026-10-11T12:00", "23:00", "AEDT", "Sunday"),
    ],
)
def test_local_times_follow_dst_boundaries(
    load_tool, openf1_calendar, race_query, location, tz_input, session, utc_iso, local_hhmm, abbr, local_day
) -> None:
    assert _fixture_session(openf1_calendar, location, session).strftime("%Y-%m-%dT%H:%M") == utc_iso  # premise
    res = load_tool("get_race_schedule", now=SEP_28)(race_query=race_query, user_timezone=tz_input)
    assert res["status"] == "success" and res["needs_timezone_clarification"] is False
    s = _session(res, session)
    assert s["local_time"].startswith(local_hhmm) and abbr in s["local_time"], f"{session} {utc_iso}Z in {tz_input}: {s['local_time']}"
    assert s["local_day"] == local_day


@pytest.mark.finding("TR-10", "TB-2", "PRD-AC7")
@pytest.mark.parametrize(
    "race_query,session,local_hhmm,abbr,local_day",
    [
        ("Azerbaijan Grand Prix", "Race", "21:00", "AEST", "Saturday"),
        ("Singapore Grand Prix", "Race", "23:00", "AEDT", "Sunday"),
    ],
)
def test_sydney_times_across_october_dst_start(
    load_tool, serve_openf1, race_query, session, local_hhmm, abbr, local_day
) -> None:
    """Azerbaijan GP (Sep 26 11:00Z) is AEST in Sydney; Singapore GP (Oct 11 12:00Z) is AEDT after Oct 4 DST transition."""
    serve_openf1()
    res = load_tool("get_race_schedule", now=SEP_28)(race_query=race_query, user_timezone="Sydney")
    assert res["status"] == "success", f"{race_query} not served: {res.get('agent_action')}"
    s = _session(res, session)
    assert s["local_time"].startswith(local_hhmm) and abbr in s["local_time"], s
    assert s["local_day"] == local_day


@pytest.mark.finding("TR-10")
@pytest.mark.parametrize(
    "city,iana,local_hhmm",
    [
        # Singapore qualifying 2026-10-10 13:00 UTC in cities no other test uses.
        ("Reykjavik", "Atlantic/Reykjavik", "13:00"),
        ("Nairobi", "Africa/Nairobi", "16:00"),
        ("Honolulu", "Pacific/Honolulu", "03:00"),
        ("Kathmandu", "Asia/Kathmandu", "18:45"),
    ],
)
def test_more_unseen_cities_resolve_via_zoneinfo(load_tool, openf1_calendar, city, iana, local_hhmm) -> None:
    assert _fixture_session(openf1_calendar, "Marina Bay", "Qualifying").strftime("%H:%M") == "13:00"
    res = load_tool("get_race_schedule", now=SEP_28)(race_query="Singapore Grand Prix", user_timezone=city)
    assert res["status"] == "success" and res["needs_timezone_clarification"] is False
    assert res["user_timezone_resolved"] == iana
    assert _session(res, "Qualifying")["local_time"].startswith(local_hhmm)
