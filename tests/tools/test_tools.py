"""Unit and contract tests for the 4 Totto Python tools (agent in $TOTTO_APP_DIR).

Consolidated from the original tests/test_tools.py. Changes versus the
original: the agent is loaded from $TOTTO_APP_DIR, the network is blocked
(conftest), the clock is frozen, and data-pinned expectations (Singapore as the
next race, Mercedes on 538 points, quali times) are computed from the captured
OpenF1 fixtures instead of being hard-coded. The date-dependent "next race"
check moved to tests/dates/ (tool vs. independent oracle at several dates).
"""

import ast
import json

import pytest

from totto_suite import oracle

TOOL_NAMES = [
    "get_race_schedule",
    "get_driver_standings",
    "lookup_mock_merch_order",
    "get_official_links",
]


def _fixture_session_utc(openf1_calendar, meeting_name: str, session_name: str) -> str:
    meeting = next(m for m in openf1_calendar["meetings"] if m["meeting_name"] == meeting_name and not m.get("is_cancelled"))
    session = next(s for s in oracle.sessions_of(meeting["meeting_key"], openf1_calendar["sessions"]) if s["session_name"] == session_name)
    return oracle.parse_utc(session["date_start"]).strftime("%H:%M UTC")


@pytest.mark.finding("TR-02", "TR-03")
@pytest.mark.parametrize("name", TOOL_NAMES)
def test_tool_obeys_cxas_static_contracts_and_no_code_leak_phrases(agent_dir, name: str) -> None:
    """T001/T002/T009/T011 static rules; no 'pacing phrase' that caused dead air and code leaks."""
    tools_dir = agent_dir / "tools"
    py_path = tools_dir / name / "python_function" / "python_code.py"
    json_path = tools_dir / name / f"{name}.json"
    assert py_path.exists(), f"Missing {py_path}"
    assert json_path.exists(), f"Missing {json_path}"
    source = py_path.read_text(encoding="utf-8")
    json_cfg = json.loads(json_path.read_text(encoding="utf-8"))

    assert "agent_action" in source, f"{name} missing agent_action (T001)"
    assert '"""' in source, f"{name} missing docstring (T002)"
    assert "conversational pacing phrase" not in source.lower(), f"{name} docstring contains pacing phrase"
    description = json_cfg.get("pythonFunction", {}).get("description", "") + json_cfg.get("description", "")
    assert "conversational pacing phrase" not in description.lower(), f"{name}.json description contains pacing phrase"

    tree = ast.parse(source)
    fn_defs = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == name]
    assert len(fn_defs) == 1, f"Expected function {name} in {py_path}"
    fn_node = fn_defs[0]
    assert fn_node.args.kwarg is None, f"{name} must not use **kwargs (T009)"
    for default_node in fn_node.args.defaults:
        if isinstance(default_node, ast.Constant):
            assert default_node.value is not None, f"{name} uses = None default (T011)"


@pytest.mark.finding("TR-09", "PRD-AC7")
def test_get_race_schedule_without_timezone_asks_before_local_times(load_tool, openf1_calendar) -> None:
    """A fixed race (not 'next', so date-independent) without a timezone: UTC times + ASK_USER_TIMEZONE (AC7)."""
    get_race_schedule = load_tool("get_race_schedule")
    res = get_race_schedule(race_query="Singapore Grand Prix", user_timezone="")
    assert res["status"] == "success"
    assert res["season"] == 2026
    assert "Singapore Grand Prix" in res["race_name"]
    assert "Marina Bay" in res["circuit_name"]
    assert res["needs_timezone_clarification"] is True
    assert res["agent_action"] == "ASK_USER_TIMEZONE_BEFORE_LOCAL_TIMES"
    fixture_meeting = next(m for m in openf1_calendar["meetings"] if m["meeting_name"] == "Singapore Grand Prix")
    fixture_sessions = oracle.sessions_of(fixture_meeting["meeting_key"], openf1_calendar["sessions"])
    assert len(res["sessions"]) == len(fixture_sessions)
    assert "Mercedes-AMG Petronas" in res["mercedes_highlights"]
    assert "latest available" in res["freshness_disclaimer"].lower()
    assert "OpenF1" in res["data_source"]


@pytest.mark.finding("TR-10", "PRD-AC7")
@pytest.mark.parametrize(
    ("tz_input", "expected_qualifying_local", "expected_needs_clarification"),
    [
        ("EST", "09:00 EDT (New York)", False),
        ("America/New_York", "09:00 EDT (New York)", False),
        ("I'm watching from New York, Eastern Time", "09:00 EDT (New York)", False),
        ("Europe/London", "14:00 BST (London)", False),
        ("JST", "22:00 JST (Tokyo)", False),
        ("Tokyo, Japan", "22:00 JST (Tokyo)", False),
        ("Berlin, Germany", "15:00 CEST (Berlin)", False),
        ("Sydney", "00:00 AEDT (Sydney)", False),
        ("Sydney, Australia", "00:00 AEDT (Sydney)", False),
        ("Australia/Sydney", "00:00 AEDT (Sydney)", False),
        ("UTC", "13:00 UTC", True),
    ],
)
def test_get_race_schedule_singapore_zoneinfo_dst_and_sydney_conversion(
    load_tool, openf1_calendar, tz_input: str, expected_qualifying_local: str, expected_needs_clarification: bool
) -> None:
    """Real IANA conversion on the October Singapore GP (quali 13:00 UTC per OpenF1 -> 00:00 AEDT Sunday in Sydney).

    The local strings are hand-verified for the fixture's quali instant
    (2026-10-10T13:00Z); the UTC time itself is read from the fixture.
    """
    get_race_schedule = load_tool("get_race_schedule")
    res = get_race_schedule(race_query="Singapore Grand Prix", user_timezone=tz_input)
    assert res["status"] == "success"
    assert res["needs_timezone_clarification"] is expected_needs_clarification
    quali = next(s for s in res["sessions"] if s["session"] == "Qualifying")
    assert quali["time_utc"] == _fixture_session_utc(openf1_calendar, "Singapore Grand Prix", "Qualifying")
    assert quali["local_time"] == expected_qualifying_local
    if "Sydney" in tz_input:
        assert quali["local_day"] == "Sunday"


@pytest.mark.finding("TR-10")
@pytest.mark.parametrize(
    ("unseen_city", "expected_iana", "expected_abbr_or_city"),
    [
        ("Toronto", "America/Toronto", "EDT (Toronto)"),
        ("São Paulo", "America/Sao_Paulo", "BRT (Sao Paulo)"),
        ("Auckland", "Pacific/Auckland", "NZDT (Auckland)"),
        ("Vienna", "Europe/Vienna", "CEST (Vienna)"),
        ("Mumbai", "Asia/Kolkata", "IST (Mumbai)"),
    ],
)
def test_get_race_schedule_unseen_world_cities_dynamic_zoneinfo(
    load_tool, unseen_city: str, expected_iana: str, expected_abbr_or_city: str
) -> None:
    """Unseen cities resolve via zoneinfo. Uses the fixed Singapore weekend (Oct 9-11) instead of 'next'.

    The original used race_query='next', so the expected DST label depended on
    the day the test ran (Auckland/Vienna/Toronto flipped at other dates).
    """
    get_race_schedule = load_tool("get_race_schedule")
    res = get_race_schedule(race_query="Singapore Grand Prix", user_timezone=unseen_city)
    assert res["status"] == "success"
    assert res["needs_timezone_clarification"] is False
    assert res["user_timezone_resolved"] == expected_iana
    assert expected_abbr_or_city in res["timezone_resolved"]


@pytest.mark.finding("TR-10")
@pytest.mark.parametrize(
    ("race_query", "tz_input", "expected_race_name"),
    [
        ("British Grand Prix", "Sydney, Australia", "British Grand Prix"),
        ("United States Grand Prix", "CDT", "United States Grand Prix"),
        ("Las Vegas Grand Prix", "PST", "Las Vegas Grand Prix"),
        ("Suzuka", "Tokyo", "Japanese Grand Prix"),
        ("Interlagos", "São Paulo", "São Paulo Grand Prix"),
    ],
)
def test_get_race_schedule_specific_2026_races_and_seasonal_dst(
    load_tool, openf1_calendar, race_query: str, tz_input: str, expected_race_name: str
) -> None:
    """Specific 2026 races resolve; quali UTC matches OpenF1; Sydney is AEST in July (vs AEDT in October)."""
    get_race_schedule = load_tool("get_race_schedule")
    res = get_race_schedule(race_query=race_query, user_timezone=tz_input)
    assert res["status"] == "success"
    assert expected_race_name in res["race_name"]
    assert res["needs_timezone_clarification"] is False
    quali = next(s for s in res["sessions"] if s["session"] == "Qualifying")
    assert quali["time_utc"] == _fixture_session_utc(openf1_calendar, expected_race_name, "Qualifying")
    if race_query == "British Grand Prix":
        assert "AEST (Sydney)" in quali["local_time"]


@pytest.mark.finding("TB-3")
def test_get_race_schedule_empty_and_unknown_query_error(load_tool) -> None:
    get_race_schedule = load_tool("get_race_schedule")
    res = get_race_schedule(race_query="   ", user_timezone="EST")
    assert res["status"] == "error"
    assert res["agent_action"] == "ASK_RACE_NAME"

    unknown_res = get_race_schedule(race_query="Moon Grand Prix", user_timezone="UTC")
    assert unknown_res["status"] == "error"
    assert unknown_res["agent_action"] == "CLARIFY_RACE_NAME"


@pytest.mark.finding("TR-08", "PRD-AC2")
@pytest.mark.parametrize("cat_input", ["all", "both", "standings", "drivers", "constructors", "wdc", "wcc"])
def test_get_driver_standings_mercedes_first_and_category_aliases(load_tool, openf1_json, cat_input: str) -> None:
    """Category aliases incl. 'both' (TR-08); Mercedes numbers equal the captured OpenF1 standings."""
    teams = openf1_json("championship_teams_latest")
    mercedes = next(t for t in teams if t["team_name"] == "Mercedes")
    get_driver_standings = load_tool("get_driver_standings")
    res = get_driver_standings(season=2026, category=cat_input)
    assert res["status"] == "success"
    names = {d["name"] for d in res["mercedes_drivers"]}
    assert names == {"Kimi Antonelli", "George Russell"}
    assert "Kimi Antonelli" in res["mercedes_summary"]
    assert "George Russell" in res["mercedes_summary"]
    assert "OpenF1" in res["data_source"]
    merc_rows = [c for c in res["constructors"] if c["team"] == "Mercedes-AMG Petronas F1 Team"]
    assert len(merc_rows) == 1
    assert merc_rows[0]["position"] == mercedes["position_current"]
    assert merc_rows[0]["points"] == mercedes["points_current"]


def test_get_driver_standings_error_cases(load_tool) -> None:
    get_driver_standings = load_tool("get_driver_standings")
    bad_season = get_driver_standings(season=1940, category="all")
    assert bad_season["status"] == "error"
    assert bad_season["agent_action"] == "EXPLAIN_INVALID_SEASON"

    bad_cat = get_driver_standings(season=2026, category="invalid_cat")
    assert bad_cat["status"] == "error"
    assert bad_cat["agent_action"] == "EXPLAIN_INVALID_CATEGORY"


@pytest.mark.finding("PRD-AC5")
@pytest.mark.parametrize(
    ("order_input", "expected_status"),
    [
        ("1001", "Delivered"),
        ("#1001", "Delivered"),
        ("1002", "In Transit"),
        ("ORD-1002", "In Transit"),
        ("1003", "Return In Progress"),
    ],
)
def test_lookup_mock_merch_order_valid_ids(load_tool, order_input: str, expected_status: str) -> None:
    lookup_mock_merch_order = load_tool("lookup_mock_merch_order")
    res = lookup_mock_merch_order(order_id=order_input)
    assert res["status"] == "success"
    assert res["found"] is True
    assert res["is_mock_data"] is True
    assert res["is_mock"] is True
    assert res["order"]["status"] == expected_status
    assert res["order"]["return_eligible"] is True
    assert "damaged_item_policy" in res["order"]
    assert "exchange_policy" in res["order"]
    assert "product_availability" in res["order"]


@pytest.mark.finding("PRD-AC5")
def test_lookup_mock_merch_order_invalid_and_empty(load_tool) -> None:
    lookup_mock_merch_order = load_tool("lookup_mock_merch_order")
    not_found = lookup_mock_merch_order(order_id="9999")
    assert not_found["status"] == "error"
    assert not_found["found"] is False
    assert not_found["agent_action"] == "OFFER_SAMPLE_ORDER_IDS"
    assert not_found["is_mock_data"] is True
    assert "1001" in not_found["error_message"]

    empty_res = lookup_mock_merch_order(order_id="")
    assert empty_res["status"] == "error"
    assert empty_res["found"] is False
    assert empty_res["agent_action"] == "PROMPT_FOR_ORDER_ID"
    assert empty_res["is_mock_data"] is True


@pytest.mark.finding("PRD-AC4", "RC-01")
@pytest.mark.parametrize(
    ("category", "expected_url"),
    [
        ("ticketing", "https://tickets.formula1.com"),
        ("tickets", "https://tickets.formula1.com"),
        ("merch", "https://shop.mercedesamgf1.com"),
        ("store", "https://shop.mercedesamgf1.com"),
        ("team", "https://www.mercedesamgf1.com"),
        ("all", "https://tickets.formula1.com"),
    ],
)
def test_get_official_links_valid_categories(load_tool, category: str, expected_url: str) -> None:
    get_official_links = load_tool("get_official_links")
    res = get_official_links(category=category)
    assert res["status"] == "success"
    assert res["result"]["url"] == expected_url
    assert res["agent_action"] == "PROVIDE_OFFICIAL_LINKS"


def test_get_official_links_invalid_category(load_tool) -> None:
    get_official_links = load_tool("get_official_links")
    res = get_official_links(category="unknown_portal")
    assert res["status"] == "error"
    assert res["agent_action"] == "EXPLAIN_INVALID_CATEGORY"
