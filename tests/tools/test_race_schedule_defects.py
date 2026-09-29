"""get_race_schedule: tool-bug regressions TB-1..TB-5 (offline, frozen clock).

Every expectation is computed from the captured OpenF1 fixtures via the
independent oracle (totto_suite/oracle.py), never from the tool under test.
Two data modes are exercised:
  * snapshot: network blocked (conftest) -> what the agent serves inside CXAS,
    where OpenF1 is unreachable (TB-1);
  * payload: urlopen serves the captured OpenF1 payloads (serve_openf1).
"""

import datetime as dt

import pytest

from totto_suite import oracle

SEP_28 = dt.datetime(2026, 9, 28, 12, 0, tzinfo=dt.timezone.utc)
JUL_01 = dt.datetime(2026, 7, 1, 12, 0, tzinfo=dt.timezone.utc)

RACE_DATA_KEYS = ("race_name", "sessions", "meeting_key", "dates", "circuit_name")


def past_signal(result: dict) -> bool | None:
    """Whether the tool result flags the meeting as already over.

    Accepts any explicit past/completed marker a fixed tool might use
    (boolean flags, a status-like field or the agent_action); None = no signal.
    """
    for key, value in result.items():
        k = key.lower()
        if k in ("status", "agent_action"):
            continue
        if any(token in k for token in ("past", "complet", "finished", "concluded")):
            if isinstance(value, str):
                return value.strip().lower() in ("true", "yes", "completed", "past", "finished", "over", "concluded")
            return bool(value)
        if k.endswith("_status") or k in ("timing", "timing_context", "event_state", "meeting_state"):
            if str(value).strip().lower() in ("completed", "past", "finished", "over", "concluded"):
                return True
            if str(value).strip().lower() in ("upcoming", "future", "scheduled", "in_progress", "live"):
                return False
    action = str(result.get("agent_action", "")).upper()
    if "PAST" in action or "COMPLETED" in action or "ALREADY" in action:
        return True
    return None


def _fixture_meeting(openf1_calendar, **match) -> dict:
    return next(m for m in openf1_calendar["meetings"] if all(m.get(k) == v for k, v in match.items()))


# --------------------------------------------------------------------------
# TB-2: next race skips Kuala Lumpur (OpenF1 meeting 1308).
# --------------------------------------------------------------------------


@pytest.mark.finding("TB-2", "PRD-AC1")
def test_next_race_includes_kuala_lumpur_when_openf1_payload_contains_it(load_tool, serve_openf1, openf1_calendar) -> None:
    """Fed the real OpenF1 calendar at 2026-09-28, 'next' must be the oracle's next race (KL, meeting 1308)."""
    expected = oracle.next_race(openf1_calendar["meetings"], SEP_28, openf1_calendar["sessions"])
    assert expected is not None and expected["location"] == "Kuala Lumpur"  # premise from the fixture
    serve_openf1()
    res = load_tool("get_race_schedule", now=SEP_28)(race_query="next", user_timezone="UTC")
    assert res["status"] == "success", res
    assert res.get("meeting_key") == expected["meeting_key"], (
        f"next race at {SEP_28:%Y-%m-%d}: tool={res.get('race_name')} (meeting {res.get('meeting_key')}, {res.get('dates')}) "
        f"but OpenF1 says {expected['meeting_name']} in {expected['location']} (meeting {expected['meeting_key']}, "
        f"{expected['date_start'][:10]}..{expected['date_end'][:10]})"
    )


@pytest.mark.finding("TB-2")
def test_kuala_lumpur_query_resolves_to_openf1_meeting(load_tool, serve_openf1, openf1_calendar) -> None:
    """A 'Kuala Lumpur' question must resolve to the OpenF1 KL meeting when the payload contains it."""
    kl = _fixture_meeting(openf1_calendar, location="Kuala Lumpur")
    serve_openf1()
    res = load_tool("get_race_schedule", now=SEP_28)(race_query="Kuala Lumpur", user_timezone="UTC")
    assert res["status"] == "success" and res.get("meeting_key") == kl["meeting_key"], (
        f"'Kuala Lumpur' -> {res.get('status')} {res.get('agent_action')} {res.get('race_name')}; "
        f"OpenF1 has meeting {kl['meeting_key']} {kl['meeting_name']} ({kl['date_start'][:10]})"
    )


# --------------------------------------------------------------------------
# TB-3: unknown race must be an error, never another race's details.
# --------------------------------------------------------------------------


@pytest.mark.finding("TB-3")
@pytest.mark.parametrize("mode", ["snapshot", "payload"])
@pytest.mark.parametrize("query", ["Moon Grand Prix", "Atlantis Grand Prix", "Portuguese Grand Prix"])
def test_unknown_race_returns_error_without_race_data(load_tool, serve_openf1, mode: str, query: str) -> None:
    if mode == "payload":
        serve_openf1()
    res = load_tool("get_race_schedule", now=SEP_28)(race_query=query, user_timezone="UTC")
    assert res["status"] == "error", f"{query!r} -> {res.get('status')} {res.get('race_name')}"
    assert res.get("agent_action") == "CLARIFY_RACE_NAME"
    leaked = [k for k in RACE_DATA_KEYS if k in res]
    assert not leaked, f"error result for {query!r} still carries race data keys {leaked}"


@pytest.mark.finding("TB-3", "PRD-L152")
@pytest.mark.parametrize("query", ["Spain", "Spain Grand Prix", "Grand Prix in Spain"])
def test_spain_query_never_returns_a_race_in_another_country(load_tool, query: str) -> None:
    """'Spain' must resolve to a Spanish meeting (or ask to clarify), never to another country's race.

    Substring keyword matching ('spa' for Spa-Francorchamps) turns 'Spain' into
    the Belgian Grand Prix: the TB-3 failure mode (wrong race returned as success).
    """
    res = load_tool("get_race_schedule", now=SEP_28)(race_query=query, user_timezone="Madrid")
    if res["status"] == "success":
        assert "Spain" in res.get("location", ""), f"{query!r} -> {res.get('race_name')} in {res.get('location')}"
    else:
        assert res.get("agent_action") == "CLARIFY_RACE_NAME"


# --------------------------------------------------------------------------
# TB-5: past race must be flagged as past relative to "now".
# --------------------------------------------------------------------------


@pytest.mark.finding("TB-5", "TR-09", "PRD-AC1")
@pytest.mark.parametrize("query", ["British Grand Prix", "Silverstone"])
def test_past_race_is_flagged_as_completed(load_tool, openf1_calendar, query: str) -> None:
    british = _fixture_meeting(openf1_calendar, meeting_name="British Grand Prix")
    assert oracle.meeting_status(british, SEP_28) == "completed"  # premise from the fixture
    res = load_tool("get_race_schedule", now=SEP_28)(race_query=query, user_timezone="Europe/London")
    assert res["status"] == "success"
    assert past_signal(res) is True, (
        f"{res.get('race_name')} ({res.get('dates')}) ended {british['date_end'][:10]}, before now={SEP_28:%Y-%m-%d}, "
        f"but the result has no past/completed flag (keys: {sorted(res)}); the agent can present it as upcoming"
    )


@pytest.mark.finding("TB-5")
def test_upcoming_race_is_not_flagged_as_completed(load_tool, openf1_calendar) -> None:
    """Guard against an always-'past' flag: before the British GP it must not be flagged completed."""
    british = _fixture_meeting(openf1_calendar, meeting_name="British Grand Prix")
    assert oracle.meeting_status(british, JUL_01) == "upcoming"
    res = load_tool("get_race_schedule", now=JUL_01)(race_query="British Grand Prix", user_timezone="Europe/London")
    assert res["status"] == "success"
    assert past_signal(res) is not True


# --------------------------------------------------------------------------
# TB-4: weather for future meetings is climatology, never a forecast.
# --------------------------------------------------------------------------


def _weather(res: dict) -> tuple[str, dict]:
    keys = [k for k in res if "weather" in k.lower()]
    assert keys, f"no weather in result (keys {sorted(res)})"
    return keys[0], res[keys[0]]


@pytest.mark.finding("TB-4", "PRD-L152")
def test_future_meeting_weather_is_labelled_typical_climatology(load_tool, openf1_calendar) -> None:
    singapore = _fixture_meeting(openf1_calendar, meeting_name="Singapore Grand Prix")
    assert oracle.meeting_status(singapore, SEP_28) == "upcoming"
    res = load_tool("get_race_schedule", now=SEP_28)(race_query="Singapore Grand Prix", user_timezone="UTC")
    _, weather = _weather(res)
    source = str(weather.get("source", ""))
    text = " ".join(str(v) for v in weather.values()).lower()
    assert not source.startswith("openf1"), f"future meeting weather claims OpenF1 telemetry: {weather}"
    assert any(word in text for word in ("typical", "climat", "historical", "average")), f"weather not labelled typical: {weather}"


@pytest.mark.finding("TB-4", "PRD-L152", "PRD-L153")
def test_future_meeting_weather_is_never_presented_as_a_forecast(load_tool, openf1_calendar) -> None:
    """A fixed per-circuit profile must not be handed to the model under a 'forecast' label."""
    res = load_tool("get_race_schedule", now=SEP_28)(race_query="Singapore Grand Prix", user_timezone="UTC")
    key, weather = _weather(res)
    assert "forecast" not in key.lower(), (
        f"fixed climatology profile is returned under key {key!r}: {weather}; the model reads it as a forecast"
    )
    assert "forecast" not in " ".join(str(v) for v in weather.values()).lower()


@pytest.mark.finding("TB-4")
def test_past_meeting_weather_comes_from_openf1_payload(load_tool, serve_openf1, openf1_json) -> None:
    readings = openf1_json("weather_meeting_1295_race_session_11377")
    last = readings[-1]
    serve_openf1()
    res = load_tool("get_race_schedule", now=SEP_28)(race_query="Azerbaijan Grand Prix", user_timezone="UTC")
    _, weather = _weather(res)
    assert str(weather.get("source", "")).startswith("openf1"), weather
    assert weather["air_temp_c"] == round(float(last["air_temperature"]), 1)
    assert weather["track_temp_c"] == round(float(last["track_temperature"]), 1)


# --------------------------------------------------------------------------
# TB-1 / TR-09: honest data_source label and freshness disclaimer.
# --------------------------------------------------------------------------


@pytest.mark.finding("TB-1", "TR-09", "PRD-L114")
@pytest.mark.parametrize("tool,kwargs", [("get_race_schedule", {"race_query": "Singapore Grand Prix", "user_timezone": "UTC"}), ("get_driver_standings", {"season": 2026, "category": "all"})])
def test_snapshot_data_is_labelled_snapshot_with_freshness_disclaimer(load_tool, tool: str, kwargs: dict) -> None:
    res = load_tool(tool, now=SEP_28)(**kwargs)
    assert res["status"] == "success"
    assert "snapshot" in res["data_source"].lower(), res["data_source"]
    assert "live" not in res["data_source"].lower(), f"network blocked but labelled live: {res['data_source']}"
    assert res.get("freshness_disclaimer", "").strip(), "missing freshness disclaimer"


@pytest.mark.finding("TB-1", "TR-09")
@pytest.mark.parametrize("tool,kwargs", [("get_race_schedule", {"race_query": "Singapore Grand Prix", "user_timezone": "UTC"}), ("get_driver_standings", {"season": 2026, "category": "all"})])
def test_live_label_only_when_openf1_payload_was_served(load_tool, serve_openf1, tool: str, kwargs: dict) -> None:
    fake = serve_openf1()
    res = load_tool(tool, now=SEP_28)(**kwargs)
    assert fake.calls, "tool never requested OpenF1"
    assert res["status"] == "success"
    assert "live" in res["data_source"].lower() and "snapshot" not in res["data_source"].lower(), res["data_source"]
    assert res.get("freshness_disclaimer", "").strip()
