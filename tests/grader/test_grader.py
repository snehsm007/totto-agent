"""Unit tests for totto_suite.grader (all 17 checks, adapters, and combine())."""

from __future__ import annotations

import pytest

from totto_suite import grader
from totto_suite.grader import model


def _ctx(**overrides) -> dict:
    defaults = {
        "now": "2026-09-28T18:41:31Z",
        "voice": False,
        "expected_language": "en",
    }
    defaults.update(overrides)
    return defaults


def _statuses(result: dict, check_name: str) -> list[str]:
    return [c["status"] for c in result["checks"] if c["name"] == check_name]


def _findings_for(result: dict, check_name: str) -> set[str]:
    out: set[str] = set()
    for c in result["checks"]:
        if c["name"] == check_name:
            out.update(c.get("findings", []))
    return out


class TestCatalogueCompleteness:
    def test_all_17_checks_registered(self):
        expected = {
            "dead_air_handoff",
            "code_leak",
            "race_facts_without_tool",
            "race_fact_value_mismatch",
            "order_facts_without_tool",
            "order_fact_value_mismatch",
            "tool_error",
            "internal_agent_names",
            "tts_unfriendly",
            "reply_length",
            "latency_budget",
            "pci_echo",
            "language_match",
            "past_race_as_upcoming",
            "disclosure_mock",
            "disclosure_freshness",
            "session_end_without_answer",
            "repetitive_boilerplate",
        }
        assert set(grader.CATALOGUE.keys()) == expected
        for name, spec in grader.CATALOGUE.items():
            assert spec.get("findings"), f"{name} must map to at least one finding ID"


class TestDeadAirHandoff:
    def test_short_text_handoff_without_tool_fails(self):
        conv = model.conversation(
            "c1",
            [
                model.user_turn("When is the next race?"),
                model.agent_turn(
                    ["Let me check the race schedule for you."],
                    transfers=["race_info_agent"],
                ),
            ],
        )
        res = grader.grade(conv, _ctx())
        assert "fail" in _statuses(res, "dead_air_handoff")
        assert "TR-03" in _findings_for(res, "dead_air_handoff")

    def test_handoff_that_also_calls_tool_passes(self):
        conv = model.conversation(
            "c2",
            [
                model.user_turn("When is the next race?"),
                model.agent_turn(
                    ["Based on our latest season snapshot, the Singapore GP runs October 9-11."],
                    transfers=["race_info_agent"],
                    tool_calls=[
                        model.tool_call(
                            "get_race_schedule",
                            {"race_query": "next"},
                            {"status": "success", "dates": "October 9 - October 11, 2026"},
                            "{'status': 'success', 'dates': 'October 9 - October 11, 2026'}",
                        )
                    ],
                ),
            ],
        )
        res = grader.grade(conv, _ctx())
        assert _statuses(res, "dead_air_handoff") == ["pass"]


class TestCodeLeak:
    @pytest.mark.parametrize(
        "leaked_text",
        [
            "Let me check.\n```python\nprint(default_api.get_race_schedule(race_query='next'))\n```",
            "transfer_to_agent(agent_name='merch_order_support_agent')",
            "get_driver_standings(season=2026)",
            "end_session(session_escalated=True)",
            "lookup_merch_order(order_id='1001')",
        ],
    )
    def test_detects_code_leaks(self, leaked_text: str):
        conv = model.conversation(
            "leak",
            [
                model.user_turn("Help me"),
                model.agent_turn([leaked_text]),
            ],
        )
        res = grader.grade(conv, _ctx())
        assert "fail" in _statuses(res, "code_leak")
        assert "TR-02" in _findings_for(res, "code_leak")

    def test_clean_prose_passes(self):
        conv = model.conversation(
            "clean",
            [
                model.user_turn("Hello"),
                model.agent_turn(["Welcome to the Silver Arrows fan line!"]),
            ],
        )
        res = grader.grade(conv, _ctx())
        assert _statuses(res, "code_leak") == ["pass"]


class TestRaceFactsGrounding:
    def test_ungrounded_race_schedule_times_fail(self):
        conv = model.conversation(
            "ungrounded_race",
            [
                model.user_turn("When is qualifying for the British GP?"),
                model.agent_turn(
                    ["Qualifying for the British Grand Prix starts on Saturday, July 4 at 14:00 UTC."]
                ),
            ],
        )
        res = grader.grade(conv, _ctx())
        assert "fail" in _statuses(res, "race_facts_without_tool")
        assert "TR-01" in _findings_for(res, "race_facts_without_tool")

    def test_merch_delivery_timestamp_with_grand_prix_mention_does_not_false_positive(self):
        """Regression test for analyze.py false positive on sim_ac5 (2:15 PM delivery time)."""
        resp = {
            "status": "success",
            "order": {
                "order_id": "1002",
                "status": "Delivered",
                "estimated_delivery": "Delivered (Yesterday at 2:15 PM)",
            },
        }
        conv = model.conversation(
            "merch_time",
            [
                model.user_turn("Where is order 1002?"),
                model.agent_turn(
                    [
                        "Your simulated order #1002 was delivered yesterday at 2:15 PM to your front porch. "
                        "Enjoy wearing your cap for the Grand Prix weekend!"
                    ],
                    tool_calls=[
                        model.tool_call("lookup_merch_order", {"order_id": "1002"}, resp, repr(resp))
                    ],
                ),
            ],
        )
        res = grader.grade(conv, _ctx())
        assert _statuses(res, "race_facts_without_tool") == ["pass"]

    def test_race_fact_value_mismatch_detects_hallucinated_time_conversion(self):
        resp = {
            "status": "success",
            "dates": "October 9 - October 11, 2026",
            "sessions": [{"session": "Qualifying", "time_utc": "13:00 UTC"}],
        }
        conv = model.conversation(
            "tz_mismatch",
            [
                model.user_turn("What time is qualifying in London?"),
                model.agent_turn(
                    ["Based on our latest season snapshot, qualifying starts at 15:00 BST."],
                    tool_calls=[
                        model.tool_call("get_race_schedule", {"race_query": "next"}, resp, repr(resp))
                    ],
                ),
            ],
        )
        res = grader.grade(conv, _ctx())
        assert "fail" in _statuses(res, "race_fact_value_mismatch")
        assert "TR-10" in _findings_for(res, "race_fact_value_mismatch")


class TestOrderFactsGrounding:
    def test_ungrounded_arbitrary_order_id_fails(self):
        conv = model.conversation(
            "ungrounded_order",
            [
                model.user_turn("Check order #88412"),
                model.agent_turn(
                    ["Your simulated order #88412 is currently in transit via DHL Express."]
                ),
            ],
        )
        res = grader.grade(conv, _ctx())
        assert "fail" in _statuses(res, "order_facts_without_tool")
        assert "TR-01" in _findings_for(res, "order_facts_without_tool")

    def test_order_fact_value_mismatch_detects_wrong_tracking_number(self):
        resp = {
            "status": "success",
            "order": {"order_id": "1001", "tracking_number": "DHL-MB-984210"},
        }
        conv = model.conversation(
            "wrong_tracking",
            [
                model.user_turn("Check order 1001"),
                model.agent_turn(
                    ["Your simulated order 1001 is in transit with tracking number DHL-MB-999999."],
                    tool_calls=[
                        model.tool_call("lookup_merch_order", {"order_id": "1001"}, resp, repr(resp))
                    ],
                ),
            ],
        )
        res = grader.grade(conv, _ctx())
        assert "fail" in _statuses(res, "order_fact_value_mismatch")


class TestToolError:
    def test_unexpected_invalid_category_error_fails(self):
        resp = {
            "status": "error",
            "agent_action": "EXPLAIN_INVALID_CATEGORY",
            "error_message": "Unsupported standings category 'both'.",
        }
        conv = model.conversation(
            "bad_cat",
            [
                model.user_turn("How are George and Kimi doing in the standings?"),
                model.agent_turn(
                    ["George is second and Kimi is fourth."],
                    tool_calls=[
                        model.tool_call(
                            "get_driver_standings",
                            {"season": 2026, "category": "both"},
                            resp,
                            repr(resp),
                        )
                    ],
                ),
            ],
        )
        res = grader.grade(conv, _ctx())
        assert "fail" in _statuses(res, "tool_error")
        assert "TR-08" in _findings_for(res, "tool_error")

    def test_expected_user_supplied_invalid_order_9999_passes(self):
        resp = {
            "status": "error",
            "agent_action": "OFFER_SAMPLE_ORDER_IDS",
            "error_message": "No order found matching ID '9999'.",
        }
        conv = model.conversation(
            "order_9999",
            [
                model.user_turn("Can you check order 9999?"),
                model.agent_turn(
                    ["I couldn't find order 9999 in our demo database. Try sample order 1001, 1002, or 1003."],
                    tool_calls=[
                        model.tool_call("lookup_merch_order", {"order_id": "9999"}, resp, repr(resp))
                    ],
                ),
            ],
        )
        res = grader.grade(conv, _ctx())
        assert _statuses(res, "tool_error") == ["pass"]


class TestInternalAgentNames:
    @pytest.mark.parametrize(
        "text",
        [
            "Let me transfer you to our race_info_agent right away.",
            "Ich verbinde dich mit unserem Race Info Agenten.",
            "I will hand you over to the Merch Support Agent.",
        ],
    )
    def test_detects_snake_case_and_humanized_agent_names(self, text: str):
        conv = model.conversation(
            "internal_name",
            [
                model.user_turn("Help"),
                model.agent_turn([text]),
            ],
        )
        res = grader.grade(conv, _ctx())
        assert "fail" in _statuses(res, "internal_agent_names")
        assert "TR-05" in _findings_for(res, "internal_agent_names")


class TestTtsAndReplyLength:
    def test_emoji_and_markdown_warn_in_text_and_fail_in_voice(self):
        conv = model.conversation(
            "tts",
            [
                model.user_turn("Who drives for Mercedes?"),
                model.agent_turn(
                    ["Our drivers are **George Russell** (#63) and **Kimi Antonelli** (#12)! 🏎️💨"]
                ),
            ],
        )
        res_text = grader.grade(conv, _ctx(voice=False))
        res_voice = grader.grade(conv, _ctx(voice=True))
        assert _statuses(res_text, "tts_unfriendly") == ["warn"]
        assert _statuses(res_voice, "tts_unfriendly") == ["fail"]

    def test_long_reply_warns_in_text_and_fails_in_voice(self):
        long_reply = " ".join(
            [f"Sentence number {i} talks about the Silver Arrows race weekend." for i in range(10)]
        )
        conv = model.conversation(
            "len",
            [
                model.user_turn("Tell me about the team."),
                model.agent_turn([long_reply]),
            ],
        )
        res_text = grader.grade(conv, _ctx(voice=False))
        res_voice = grader.grade(conv, _ctx(voice=True))
        assert _statuses(res_text, "reply_length") == ["warn"]
        assert _statuses(res_voice, "reply_length") == ["fail"]


class TestLatencyPciAndLanguage:
    def test_latency_budget_skips_when_unmeasured_and_fails_when_exceeded(self):
        conv_unmeasured = model.conversation("lat0", [model.agent_turn(["Hello there."])])
        assert _statuses(grader.grade(conv_unmeasured, _ctx()), "latency_budget") == ["skip"]

        conv_slow = model.conversation(
            "lat1", [model.agent_turn(["Hello there."], latency_s=9.5)]
        )
        res = grader.grade(conv_slow, _ctx())
        assert "fail" in _statuses(res, "latency_budget")
        assert "RC-08" in _findings_for(res, "latency_budget")

    def test_pci_echo_detects_card_number_echo(self):
        conv = model.conversation(
            "pci",
            [
                model.user_turn("My card is 4532 0151 1283 0366, charge me."),
                model.agent_turn(
                    ["I cannot charge card 4532 0151 1283 0366 because I am non-transactional."]
                ),
            ],
        )
        res = grader.grade(conv, _ctx())
        assert "fail" in _statuses(res, "pci_echo")
        assert "NEW-3" in _findings_for(res, "pci_echo")

    def test_language_match_detects_english_handoff_in_german_conversation(self):
        conv = model.conversation(
            "lang_de",
            [
                model.user_turn(
                    "Hallo! Wann findet das nächste Formel-1-Rennen statt und wie ist das Wetter?"
                ),
                model.agent_turn(
                    ["I will connect you with our race information specialist to check the schedule for you."]
                ),
            ],
        )
        res = grader.grade(conv, _ctx(expected_language="auto"))
        assert "fail" in _statuses(res, "language_match")
        assert "TR-04" in _findings_for(res, "language_match")

    def test_german_utc_schedule_bullets_not_misclassified_as_portuguese(self):
        conv = model.conversation(
            "lang_de_schedule",
            [
                model.user_turn("Hallo! Wann findet das nächste Formel-1-Rennen statt?"),
                model.agent_turn(
                    [
                        "Hier ist der Zeitplan für das Rennwochenende in UTC:\n\n"
                        "* 1. Freies Training: Freitag, 9. Oktober um 11:30 UTC\n"
                        "* Qualifying: Samstag, 10. Oktober um 14:00 UTC\n"
                        "* Rennen: Sonntag, 11. Oktober um 14:00 UTC"
                    ]
                ),
            ],
        )
        res = grader.grade(conv, _ctx(expected_language="de"))
        assert _statuses(res, "language_match") == ["pass"]


class TestPastRaceAndDisclosuresAndEscalation:
    def test_past_race_presented_as_upcoming_fails(self):
        resp = {
            "status": "success",
            "race_name": "British Grand Prix",
            "dates": "July 3 - July 5, 2026",
            "data_source": "OpenF1 API (Cached/Simulated for Sandbox)",
        }
        conv = model.conversation(
            "past_race",
            [
                model.user_turn("When is the next race?"),
                model.agent_turn(
                    [
                        "The next race is the British Grand Prix at Silverstone from July 3 to July 5, 2026 "
                        "based on our latest available season snapshot."
                    ],
                    tool_calls=[
                        model.tool_call("get_race_schedule", {"race_query": "next"}, resp, repr(resp))
                    ],
                ),
            ],
        )
        res = grader.grade(conv, _ctx(now="2026-09-28T18:41:31Z"))
        assert "fail" in _statuses(res, "past_race_as_upcoming")
        assert "TB-5" in _findings_for(res, "past_race_as_upcoming")

    def test_french_a_deja_eu_lieu_with_courses_a_venir_passes(self):
        resp = {
            "status": "success",
            "race_name": "British Grand Prix",
            "dates": "July 3 - July 5, 2026",
            "data_source": "OpenF1 API (Cached/Simulated for Sandbox)",
        }
        conv = model.conversation(
            "past_race_fr",
            [
                model.user_turn("Quand a lieu le Grand Prix de Silverstone ?"),
                model.agent_turn(
                    [
                        "Selon les dernières données disponibles, le Grand Prix de Grande-Bretagne à Silverstone "
                        "a déjà eu lieu du 3 au 5 juillet 2026. Pour les courses à venir, vous pouvez acheter "
                        "vos billets sur le site officiel."
                    ],
                    tool_calls=[
                        model.tool_call("get_race_schedule", {"race_query": "Silverstone"}, resp, repr(resp))
                    ],
                ),
            ],
        )
        res = grader.grade(conv, _ctx(now="2026-09-30T15:00:00Z", expected_language="fr"))
        assert _statuses(res, "past_race_as_upcoming") == ["pass"]

    def test_missing_mock_and_freshness_disclosures_fail(self):
        resp_order = {"status": "success", "order": {"order_id": "1001"}}
        resp_standings = {
            "status": "success",
            "data_source": "OpenF1 Standings Feed (Sandbox Fixture)",
        }
        conv = model.conversation(
            "no_disclosure",
            [
                model.user_turn("Check order 1001 and standings"),
                model.agent_turn(
                    [
                        "Order #1001 is in transit via DHL Express, and George Russell is P2 with 150 points."
                    ],
                    tool_calls=[
                        model.tool_call(
                            "lookup_merch_order", {"order_id": "1001"}, resp_order, repr(resp_order)
                        ),
                        model.tool_call(
                            "get_driver_standings",
                            {"season": 2026, "category": "all"},
                            resp_standings,
                            repr(resp_standings),
                        ),
                    ],
                ),
            ],
        )
        res = grader.grade(conv, _ctx())
        assert "fail" in _statuses(res, "disclosure_mock")
        assert "fail" in _statuses(res, "disclosure_freshness")

    def test_session_end_without_answer_detects_missing_human_escalation_path(self):
        conv = model.conversation(
            "human_esc",
            [
                model.user_turn("I want to speak to a human supervisor right now!"),
                model.agent_turn(["I am transferring you to a human agent now."]),
            ],
        )
        res = grader.grade(conv, _ctx())
        assert "fail" in _statuses(res, "session_end_without_answer")
        assert "RC-02" in _findings_for(res, "session_end_without_answer")

    def test_live_provenance_schedule_needs_no_snapshot_disclaimer(self):
        resp_live = {
            "status": "success",
            "source": "live",
            "data_source": "OpenF1 API (https://api.openf1.org/v1 - Live 2026 Season)",
            "race_name": "Singapore Grand Prix",
            "dates": "October 9 - October 11, 2026",
            "sessions": [{"session": "Race", "utc_time": "2026-10-11 12:00 UTC"}],
            "typical_weather": {"source": "typical_circuit_climate_profile"},
            "freshness_disclaimer": "Race schedule reflects the latest available structured 2026 season data.",
        }
        conv = model.conversation(
            "live_sched",
            [
                model.user_turn("When is the next race?"),
                model.agent_turn(
                    ["The Singapore Grand Prix runs from October 9 to October 11, with the race at 12:00 UTC."],
                    tool_calls=[
                        model.tool_call("get_race_schedule", {"race_query": "next"}, resp_live, repr(resp_live))
                    ],
                ),
            ],
        )
        res = grader.grade(conv, _ctx())
        assert "fail" not in _statuses(res, "disclosure_freshness")


class TestRepetitiveBoilerplate:
    def test_repeated_self_intro_across_turns_fails(self):
        conv = model.conversation(
            "rep_intro",
            [
                model.user_turn("<welcome>"),
                model.agent_turn(["Hello! I am Totto, Mercedes F1 Fan Agent. How can I help you?"], greeting=True),
                model.user_turn("Hello Totto"),
                model.agent_turn(["Hello! I am Totto, Mercedes F1 Fan Agent, the AI assistant for Mercedes fans."]),
            ],
        )
        res = grader.grade(conv, _ctx())
        assert "fail" in _statuses(res, "repetitive_boilerplate")

    def test_self_intro_on_explicit_identity_question_passes(self):
        conv = model.conversation(
            "explicit_id",
            [
                model.user_turn("<welcome>"),
                model.agent_turn(["Hello! I am Totto, Mercedes F1 Fan Agent."], greeting=True),
                model.user_turn("Wait, who are you? Are you Toto Wolff?"),
                model.agent_turn(["I am Totto, the fictional AI Mercedes F1 Fan Agent, not the real Toto Wolff."]),
            ],
        )
        res = grader.grade(conv, _ctx())
        assert _statuses(res, "repetitive_boilerplate") == ["pass"]

    def test_repeated_according_to_latest_available_mantra_fails(self):
        conv = model.conversation(
            "rep_mantra",
            [
                model.user_turn("When is the next race?"),
                model.agent_turn(["According to the latest-available 2026 data, the Singapore Grand Prix is next."]),
                model.user_turn("I am in New York."),
                model.agent_turn(["According to the latest-available 2026 data, the race starts at 8 AM EDT."]),
            ],
        )
        res = grader.grade(conv, _ctx())
        assert "fail" in _statuses(res, "repetitive_boilerplate")

    def test_natural_six_turn_conversation_passes_repetitive_boilerplate(self):
        conv = model.conversation(
            "natural_call",
            [
                model.user_turn("<welcome>"),
                model.agent_turn(["Hello and welcome to the Silver Arrows paddock! I am Totto, your Mercedes F1 Fan Agent."], greeting=True),
                model.user_turn("Hello Totto"),
                model.agent_turn(["Great to have you with us! What is on your mind for the Silver Arrows?"]),
                model.user_turn("When is the next race?"),
                model.agent_turn(["Next up on the 2026 calendar is the Singapore Grand Prix from October 9 to October 11. Which city or timezone are you watching from?"]),
                model.user_turn("I'm in New York"),
                model.agent_turn(["For New York, qualifying is on Saturday at 9 AM EDT and Sunday's race starts at 8 AM EDT."]),
                model.user_turn("How has your day been so far?"),
                model.agent_turn(["Busy as ever in Brackley reviewing W17 simulator data with George and Kimi, and my headset is still in one piece!"]),
                model.user_turn("What is your favorite breakfast?"),
                model.agent_turn(["Nothing beats a crisp slice of pumpernickel toast—toasted until it snaps like a carbon-fiber front wing—with a strong espresso!"]),
            ],
        )
        res = grader.grade(conv, _ctx())
        assert _statuses(res, "repetitive_boilerplate") == ["pass"]


class TestAdaptersAndCombine:
    def test_all_four_adapters_produce_valid_conversations(self):
        trace = [
            "User Query: When is the next race?\n"
            "Agent Transfer: Transferred to race_info_agent\n"
            "Tool Call: get_race_schedule with args {'race_query': 'next'}\n"
            "Tool Response: get_race_schedule with result {'result': {'status': 'success', 'dates': 'October 9 - October 11, 2026'}}\n"
            "Agent Text: Based on our latest available season snapshot, the Singapore Grand Prix runs October 9 to October 11, 2026."
        ]
        # 1. Sim row adapter & SCRAPI sim result adapter
        sim_row = {
            "name": "sim_1",
            "run": 1,
            "session_id": "sess-1",
            "passed": True,
            "detailed_trace": trace,
        }
        c_sim = grader.from_sim_row(sim_row)
        assert c_sim["id"] == "sim_1#run1"
        assert len(c_sim["turns"]) == 2
        assert c_sim["turns"][1]["tool_calls"][0]["name"] == "get_race_schedule"

        c_scrapi = grader.from_scrapi_sim_result(sim_row)
        assert c_scrapi["id"] == "sim_1#run1"

        # 2. Probe row adapter
        probe_row = {
            "name": "probe_1",
            "run": 1,
            "session_id": "sess-2",
            "passed": True,
            "turns": [
                {
                    "user": "When is the next race?",
                    "agent": [
                        "Based on our latest available season snapshot, the Singapore Grand Prix runs October 9 to October 11, 2026."
                    ],
                    "tools": [{"name": "get_race_schedule", "args": {"race_query": "next"}}],
                    "transfer": "race_info_agent",
                    "latency_s": 1.2,
                }
            ],
            "detailed_trace": trace,
        }
        c_probe = grader.from_probe_row(probe_row)
        assert c_probe["id"] == "probe_1#run1"
        assert c_probe["turns"][1]["latency_s"] == 1.2

        # 3. Conversation history adapter
        hist_dict = {
            "name": "projects/p/locations/l/apps/a/conversations/conv-123",
            "channel_type": "TEXT",
            "turns": [
                {
                    "messages": [
                        {
                            "role": "USER",
                            "event_time": "2026-09-28T18:00:00Z",
                            "chunks": [{"text": "Hello"}],
                        },
                        {
                            "role": "AGENT",
                            "event_time": "2026-09-28T18:00:01Z",
                            "chunks": [{"text": "Welcome to the Silver Arrows fan line!"}],
                        },
                    ]
                }
            ],
        }
        c_hist = grader.from_conversation_history(hist_dict)
        assert c_hist["session_id"] == "conv-123"
        assert c_hist["turns"][1]["latency_s"] == 1.0

    def test_combine_d3_rules(self):
        det_pass = {"passed": True, "checks": []}
        det_fail = {"passed": False, "checks": [{"name": "code_leak", "status": "fail"}]}
        judge_pass = {"passed": True, "error": None}
        judge_fail = {"passed": False, "error": None}

        # Judge PASS + deterministic FAIL -> FAIL (judge override)
        assert grader.combine(det_fail, judge_pass) == grader.FAIL
        # Judge FAIL + deterministic PASS -> FAIL
        assert grader.combine(det_pass, judge_fail) == grader.FAIL
        # Judge PASS + deterministic PASS -> PASS
        assert grader.combine(det_pass, judge_pass) == grader.PASS
        # Infra error -> INFRA_ERROR
        assert (
            grader.combine(det_pass, judge_pass, row_error="429 RESOURCE_EXHAUSTED")
            == grader.INFRA_ERROR
        )
        # Missing judge verdict when expectations exist -> INFRA_ERROR
        assert (
            grader.combine(det_pass, {"passed": None, "error": "empty judge output"})
            == grader.INFRA_ERROR
        )
