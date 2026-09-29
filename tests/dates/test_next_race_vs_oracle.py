"""get_race_schedule('next') versus the independent oracle at frozen dates.

For each frozen instant the expected next race is computed by
totto_suite/oracle.py from the captured OpenF1 calendar; the tool's own code
is never used to build an expectation. Both data modes are checked:
  * snapshot: network blocked, i.e. what the agent serves inside CXAS (TB-1);
  * payload: the tool is fed the captured OpenF1 payloads.

Known disagreements on the unmodified agent (reported, not fixed):
  * 2026-09-28: the tool skips the Kuala Lumpur meeting 1308 (TB-2);
  * 2026-12-31: after the season the tool still answers Singapore (NEW-1);
  * 2026-04-01: the tool offers the cancelled Bahrain GP in Sakhir (NEW-5).
"""

import datetime as dt

import pytest

from totto_suite import oracle

DATES = {
    "2026-04-01": (dt.datetime(2026, 4, 1, 12, 0, tzinfo=dt.timezone.utc), ("NEW-5",)),
    "2026-07-01": (dt.datetime(2026, 7, 1, 12, 0, tzinfo=dt.timezone.utc), ()),
    "2026-09-28": (dt.datetime(2026, 9, 28, 12, 0, tzinfo=dt.timezone.utc), ("TB-2",)),
    "2026-10-05": (dt.datetime(2026, 10, 5, 12, 0, tzinfo=dt.timezone.utc), ()),
    "2026-12-31": (dt.datetime(2026, 12, 31, 12, 0, tzinfo=dt.timezone.utc), ("NEW-1",)),
}


def _params():
    for label, (_, findings) in DATES.items():
        for mode in ("snapshot", "payload"):
            yield pytest.param(label, mode, marks=pytest.mark.finding("PRD-AC1", "TR-09", *findings), id=f"{label}-{mode}")


def _describe(res: dict) -> str:
    return f"{res.get('status')} {res.get('race_name')} (meeting {res.get('meeting_key')}, {res.get('dates')}, {res.get('location')})"


@pytest.mark.parametrize("date_label,mode", list(_params()))
def test_next_race_matches_oracle(load_tool, serve_openf1, openf1_calendar, date_label: str, mode: str) -> None:
    now, _ = DATES[date_label]
    expected = oracle.next_race(openf1_calendar["meetings"], now, openf1_calendar["sessions"])
    if mode == "payload":
        serve_openf1()
    tool = load_tool("get_race_schedule", now=now)
    assert tool.__globals__.get("__totto_clock_seam_found__"), "tool has no datetime seam to freeze; test would depend on the real date"
    res = tool(race_query="next", user_timezone="UTC")

    if expected is None:
        # Season over: the tool must not present a race of this (finished) season as next.
        if res.get("status") == "success":
            session_dates = sorted(str(s.get("date_utc", "")) for s in res.get("sessions", []))
            last_session = session_dates[-1] if session_dates else ""
            today = now.strftime("%Y-%m-%d")
            season_end = oracle.race_meetings(openf1_calendar["meetings"], openf1_calendar["sessions"])[-1]["date_end"][:10]
            assert last_session >= today, (
                f"{date_label} ({mode}): the 2026 season is over per OpenF1 (last race ended {season_end}), "
                f"but the tool presents {_describe(res)} as the next race"
            )
        return

    assert res.get("status") == "success", f"{date_label} ({mode}): {_describe(res)}"
    assert res.get("meeting_key") == expected["meeting_key"], (
        f"{date_label} ({mode}): tool says {_describe(res)}; oracle (OpenF1) says {expected['meeting_name']} in "
        f"{expected['location']} (meeting {expected['meeting_key']}, {expected['date_start'][:10]}..{expected['date_end'][:10]})"
    )
    expected_sessions = [(s["session_name"], oracle.parse_utc(s["date_start"]).strftime("%Y-%m-%d %H:%M UTC")) for s in oracle.sessions_of(expected["meeting_key"], openf1_calendar["sessions"])]
    got_sessions = [(s["session"], s["utc_time"]) for s in res["sessions"]]
    assert got_sessions == expected_sessions, f"{date_label} ({mode}): session times differ from OpenF1"
