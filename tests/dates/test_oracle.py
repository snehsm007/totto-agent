"""Unit tests of the independent date oracle (totto_suite/oracle.py).

The expected meetings below were verified by hand against the captured OpenF1
calendar (tests/fixtures/openf1/meetings_2026.json, captured 2026-09-28):
  1304/1305 Pre-Season Testing (Feb) | 1279 Australian GP Mar 6-8 (ends 06:00Z)
  1280 Chinese GP Mar 13-15 | 1281 Japanese GP Mar 27-29
  1282 Bahrain GP (Sakhir, Apr 10-12) and 1283 Saudi Arabian GP: is_cancelled
  1284 Miami GP May 1-3 | ... | 1289 British GP Jul 3-5 | 1295 Azerbaijan GP Sep 24-26
  1308 "Bahrain Grand Prix" in Kuala Lumpur Oct 2-4 (ends 2026-10-04T09:00Z)
  1296 Singapore GP Oct 9-11 | ... | 1302 Abu Dhabi GP Dec 4-6 (ends 2026-12-06T15:00Z)
"""

import datetime as dt

import pytest

from totto_suite import oracle


def _utc(*args) -> dt.datetime:
    return dt.datetime(*args, tzinfo=dt.timezone.utc)


@pytest.mark.finding("TB-2", "NEW-1", "TR-09", "PRD-AC1")
@pytest.mark.parametrize(
    "now,expected_key",
    [
        (_utc(2026, 2, 15), 1279),  # between the two testing events: testing is not a race
        (_utc(2026, 3, 8, 5, 59, 59), 1279),  # Australian GP still running
        (_utc(2026, 3, 8, 6, 0, 1), 1280),  # just after it ended
        (_utc(2026, 4, 1), 1284),  # Bahrain (Sakhir) and Saudi Arabia are cancelled -> Miami
        (_utc(2026, 7, 1, 12), 1289),  # British GP
        (_utc(2026, 9, 28, 12), 1308),  # Kuala Lumpur, not Singapore
        (_utc(2026, 10, 4, 8, 59, 59), 1308),  # KL race under way
        (_utc(2026, 10, 4, 9, 0, 1), 1296),  # KL over -> Singapore
        (_utc(2026, 10, 5, 12), 1296),
        (_utc(2026, 12, 6, 14, 59, 59), 1302),  # Abu Dhabi still running
        (_utc(2026, 12, 6, 15, 0, 1), None),  # season over
        (_utc(2026, 12, 31, 12), None),
    ],
    ids=lambda v: v.strftime("%Y-%m-%dT%H:%M:%S") if isinstance(v, dt.datetime) else f"meeting-{v}",
)
def test_next_race_at_hand_verified_instants(openf1_calendar, now, expected_key) -> None:
    got = oracle.next_race(openf1_calendar["meetings"], now, openf1_calendar["sessions"])
    assert (got["meeting_key"] if got else None) == expected_key
    # The session-free rule (name-based testing filter) gives the same answer.
    got_no_sessions = oracle.next_race(openf1_calendar["meetings"], now)
    assert (got_no_sessions["meeting_key"] if got_no_sessions else None) == expected_key


def test_next_race_boundary_is_inclusive_at_date_end() -> None:
    meetings = [{"meeting_key": 1, "meeting_name": "A Grand Prix", "date_start": "2026-01-01T10:00:00+00:00", "date_end": "2026-01-03T10:00:00+00:00"}]
    assert oracle.next_race(meetings, _utc(2026, 1, 3, 10))["meeting_key"] == 1
    assert oracle.next_race(meetings, _utc(2026, 1, 3, 10, 0, 1)) is None


def test_rules_exclude_testing_and_cancelled_and_order_by_start() -> None:
    meetings = [
        {"meeting_key": 3, "meeting_name": "C Grand Prix", "date_start": "2026-03-01T00:00:00Z", "date_end": "2026-03-03T00:00:00Z"},
        {"meeting_key": 1, "meeting_name": "Pre-Season Testing", "date_start": "2026-01-01T00:00:00Z", "date_end": "2026-01-03T00:00:00Z"},
        {"meeting_key": 2, "meeting_name": "B Grand Prix", "date_start": "2026-02-01T00:00:00Z", "date_end": "2026-02-03T00:00:00Z", "is_cancelled": True},
    ]
    assert [m["meeting_key"] for m in oracle.race_meetings(meetings)] == [3]
    assert oracle.next_race(meetings, _utc(2025, 12, 1))["meeting_key"] == 3


def test_sessions_define_race_meetings_when_given() -> None:
    meetings = [
        {"meeting_key": 1, "meeting_name": "Filming Day", "date_start": "2026-01-01T00:00:00Z", "date_end": "2026-01-01T08:00:00Z"},
        {"meeting_key": 2, "meeting_name": "B Grand Prix", "date_start": "2026-02-01T00:00:00Z", "date_end": "2026-02-03T00:00:00Z"},
    ]
    sessions = [{"meeting_key": 1, "session_type": "Practice"}, {"meeting_key": 2, "session_type": "Race"}]
    assert oracle.next_race(meetings, _utc(2025, 12, 1), sessions)["meeting_key"] == 2


def test_meeting_status_and_naive_datetime_rejected(openf1_calendar) -> None:
    british = next(m for m in openf1_calendar["meetings"] if m["meeting_key"] == 1289)
    assert oracle.meeting_status(british, _utc(2026, 7, 1)) == "upcoming"
    assert oracle.meeting_status(british, _utc(2026, 7, 4)) == "in_progress"
    assert oracle.meeting_status(british, _utc(2026, 9, 28)) == "completed"
    with pytest.raises(ValueError):
        oracle.next_race(openf1_calendar["meetings"], dt.datetime(2026, 9, 28))
