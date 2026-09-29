"""OpenF1 fault injection for the two network-backed tools (RC-03, RC-09, TB-1).

The fake OpenF1 server (conftest.FakeOpenF1) injects timeouts, HTTP 500/429,
malformed JSON, empty and non-list payloads, partial failures and hanging or
slow endpoints. Hangs are simulated: the fake adds each request's timeout to a
virtual clock instead of sleeping, so the worst-case latency bound
(attempts x timeout) is measured exactly and the test stays fast.

Latency budget: 7 s per tool call. The Agent Report Card flagged 7.2 s of dead
air as a defect (RC-08) and 30 s timeouts during a standings lookup (RC-03,
RC-09); the PRD asks for fast, voice-friendly answers (L21, L89-90). A tool
that can block longer than the budget before returning cannot meet that.
"""

import datetime as dt

import pytest

SEP_28 = dt.datetime(2026, 9, 28, 12, 0, tzinfo=dt.timezone.utc)
TOOL_LATENCY_BUDGET_S = 7.0

CASES = {
    "standings": ("get_driver_standings", {"season": 2026, "category": "all"}),
    "schedule_next": ("get_race_schedule", {"race_query": "next", "user_timezone": "UTC"}),
    "schedule_past_race": ("get_race_schedule", {"race_query": "Azerbaijan Grand Prix", "user_timezone": "UTC"}),
}


def _assert_structured_snapshot_success(res: dict) -> None:
    assert isinstance(res, dict) and res.get("status") == "success", res
    assert "snapshot" in res["data_source"].lower() and "live" not in res["data_source"].lower(), res["data_source"]
    assert res.get("freshness_disclaimer", "").strip()
    assert res.get("agent_action")


@pytest.mark.finding("RC-03", "RC-09", "TB-1")
@pytest.mark.parametrize("fault", ["timeout", "http500", "http429", "malformed", "empty", "non_list"])
@pytest.mark.parametrize("case", ["standings", "schedule_next"])
def test_openf1_fault_falls_back_to_labelled_snapshot(load_tool, serve_openf1, case: str, fault: str) -> None:
    tool, kwargs = CASES[case]
    fake = serve_openf1({"*": fault})
    res = load_tool(tool, now=SEP_28)(**kwargs)
    assert fake.calls, "fault was never exercised: the tool made no OpenF1 request"
    _assert_structured_snapshot_success(res)


@pytest.mark.finding("RC-03", "RC-09", "TB-1")
@pytest.mark.parametrize(
    "case,faults",
    [
        ("schedule_next", {"sessions": "http500"}),
        ("schedule_next", {"meetings": "empty"}),
        ("standings", {"championship_drivers": "http429"}),
        ("standings", {"drivers": "malformed"}),
    ],
)
def test_partial_openf1_failure_never_mixes_live_label_with_fallback(load_tool, serve_openf1, case: str, faults: dict) -> None:
    tool, kwargs = CASES[case]
    serve_openf1(faults)
    res = load_tool(tool, now=SEP_28)(**kwargs)
    assert res.get("status") == "success", res
    label = res["data_source"].lower()
    if "live" in label:
        # A live label is only honest if everything came from OpenF1; the
        # standings tool tolerates a failing optional drivers-metadata call.
        assert case == "standings" and list(faults) == ["drivers"], f"live label despite failing {faults}: {res['data_source']}"
    assert res.get("freshness_disclaimer", "").strip()


@pytest.mark.finding("RC-03", "RC-09", "RC-08", "PRD-L21")
@pytest.mark.parametrize("behaviour", ["hang", "slow"])
@pytest.mark.parametrize("case", ["standings", "schedule_next", "schedule_past_race"])
def test_worst_case_latency_with_hanging_openf1_stays_within_voice_budget(load_tool, serve_openf1, case: str, behaviour: str) -> None:
    """Worst case = sum of per-request timeouts when every OpenF1 request hangs
    until its timeout ('hang') or answers just before it ('slow')."""
    tool, kwargs = CASES[case]
    fake = serve_openf1({"*": behaviour})
    res = load_tool(tool, now=SEP_28)(**kwargs)
    assert isinstance(res, dict) and res.get("status") in ("success", "error"), res
    assert all(c["timeout"] is not None for c in fake.calls), f"request without timeout: {fake.calls}"
    attempts = [(c["endpoint"], c["timeout"]) for c in fake.calls]
    assert fake.virtual_elapsed_s <= TOOL_LATENCY_BUDGET_S, (
        f"{tool}({kwargs}) can block {fake.virtual_elapsed_s:.1f}s before answering "
        f"(budget {TOOL_LATENCY_BUDGET_S}s): sequential OpenF1 requests {attempts}"
    )


@pytest.mark.finding("NEW-4", "PRD-L152", "PRD-L153")
@pytest.mark.parametrize("season", [2019, 2025])
def test_standings_for_other_season_never_returns_2026_data_as_that_season(load_tool, season: int) -> None:
    """The tool only has 2026 data; answering a 2019 request with 2026 numbers labelled 2019 invents data."""
    res = load_tool("get_driver_standings", now=SEP_28)(season=season, category="all")
    assert res["status"] != "success" or res.get("season") == 2026, (
        f"season={season} -> status=success, season={res.get('season')}, but constructors are the 2026 table "
        f"(P1 {res['constructors'][0]['team']} {res['constructors'][0]['points']} pts)"
    )


@pytest.mark.finding("TB-1", "PRD-AC2")
def test_standings_from_openf1_payload_match_captured_tables(load_tool, serve_openf1, openf1_json) -> None:
    teams = sorted(openf1_json("championship_teams_latest"), key=lambda t: t["position_current"])
    drivers = sorted(openf1_json("championship_drivers_latest"), key=lambda d: d["position_current"])
    serve_openf1()
    res = load_tool("get_driver_standings", now=SEP_28)(season=2026, category="all")
    assert res["status"] == "success"
    got_teams = [(c["position"], c["team_short_name"], c["points"]) for c in res["constructors"]]
    assert got_teams == [(t["position_current"], t["team_name"], t["points_current"]) for t in teams]
    got_drivers = [(d["position"], d["number"], d["points"]) for d in res["drivers"]]
    assert got_drivers == [(d["position_current"], d["driver_number"], d["points_current"]) for d in drivers][: len(got_drivers)]
    merc = {d["number"]: d for d in res["mercedes_drivers"]}
    for d in drivers:
        if d["driver_number"] in (12, 63):
            assert merc[d["driver_number"]]["points"] == d["points_current"]
            assert merc[d["driver_number"]]["position"] == d["position_current"]
