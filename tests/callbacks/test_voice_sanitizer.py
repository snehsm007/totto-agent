"""Tests for the voice_sanitizer after_model_callback of every agent in $TOTTO_APP_DIR.

The callback is executed with SCRAPI's local copies of the platform datamodels
(`cxas_scrapi.utils.callback_libs.Part` / `LlmResponse`), and its output is
checked with the same regexes that totto_suite's `tts_unfriendly` grader uses on
real transcripts, so "clean" means "the grader would not flag it in voice".
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from cxas_scrapi.utils.callback_libs import Content, LlmResponse, Part
import pytest

from totto_suite.grader import text as tx

AGENTS = ("totto_root_agent", "race_info_agent", "merch_support_agent", "ticketing_agent")
REL = "after_model_callbacks/voice_sanitizer/python_code.py"

# Shape of the real voice reply recorded in
# evals/history/artifacts/20260929T001319Z_live_fd9be8b/live_voice/voice_probe_merch_order_1002_r1.json
MESSY_REPLY = (
    "## Order update 🏎️\n"
    "Your simulated order #1002 is **In Transit** with DHL!\n"
    "- Item: `George Russell #63 cap`\n"
    "1. Track it at https://www.dhl.com/\n"
    "Visit the [Official Mercedes-AMG Petronas F1 Team Store](https://shop.mercedesamgf1.com) -> returns ✅"
)


def _load(agent_dir: Path, agent: str) -> dict:
    path = agent_dir / "agents" / agent / REL
    namespace = {
        "__name__": f"voice_sanitizer_{agent}",
        "CallbackContext": object,
        "LlmResponse": LlmResponse,
        "Part": Part,
    }
    exec(compile(path.read_text(encoding="utf-8"), str(path), "exec"), namespace)
    return namespace


def _response(*parts, **flags) -> LlmResponse:
    return LlmResponse(content=Content(parts=list(parts), role="model"), **flags)


def _tts_issues(text: str) -> list[str]:
    issues = [f"markdown:{k}" for k, rx in tx.MARKDOWN.items() if rx.search(text)]
    issues += [f"symbol:{k}" for k, rx in tx.SPOKEN_SYMBOLS.items() if k != "position_token" and rx.search(text)]
    if [e for e in tx.EMOJI.findall(text) if e not in ("\ufe0f", "\u200d")]:
        issues.append("emoji")
    return issues


def test_every_agent_registers_the_voice_sanitizer(agent_dir: Path) -> None:
    for agent in AGENTS:
        cfg = json.loads((agent_dir / "agents" / agent / f"{agent}.json").read_text(encoding="utf-8"))
        paths = [cb.get("pythonCode") for cb in cfg.get("afterModelCallbacks", [])]
        assert f"agents/{agent}/{REL}" in paths, f"{agent} does not register the voice sanitizer"
        assert (agent_dir / "agents" / agent / REL).is_file()


def test_messy_reply_fixture_really_is_flagged_by_the_grader() -> None:
    assert {"markdown:bold", "markdown:link", "symbol:raw_url", "symbol:hash_number", "emoji"} <= set(
        _tts_issues(MESSY_REPLY)
    )


@pytest.mark.finding("RC-06", "RC-07", "NEW-2")
@pytest.mark.parametrize("agent", AGENTS)
def test_markdown_emoji_and_url_prefixes_are_removed_but_content_is_kept(agent_dir: Path, agent: str) -> None:
    ns = _load(agent_dir, agent)
    result = ns["after_model_callback"](None, _response(Part.from_text(text=MESSY_REPLY)))

    assert result is not None, "a reply with markdown must be rewritten"
    (part,) = result.content.parts
    cleaned = part.text
    assert _tts_issues(cleaned) == [], cleaned
    for kept in (
        "Order update",
        "In Transit",
        "order 1002",
        "George Russell 63 cap",
        "dhl.com",
        "Official Mercedes-AMG Petronas F1 Team Store (shop.mercedesamgf1.com)",
    ):
        assert kept in cleaned, f"{kept!r} lost from {cleaned!r}"


@pytest.mark.parametrize("agent", AGENTS)
def test_tool_calls_are_kept_in_order_and_untouched(agent_dir: Path, agent: str) -> None:
    ns = _load(agent_dir, agent)
    call = Part.from_function_call(name="get_official_links", args={"category": "all"})
    end = Part.from_end_session(reason="user said goodbye")
    result = ns["after_model_callback"](None, _response(Part.from_text(text="**Bye!** 👋"), call, end))

    assert [p.text for p in result.content.parts[:1]] == ["Bye!"]
    assert result.content.parts[1] is call and result.content.parts[2] is end


@pytest.mark.parametrize(
    "text",
    [
        "Qualifying is on Saturday at 14:00 UTC and the race is Sunday at 13:00 UTC, with about 21°C expected.",
        "Das Rennen findet am Sonntag um 15 Uhr statt. Viel Spaß, Silberpfeil-Fan!",
        "Vous trouverez les billets sur tickets.formula1.com, le site officiel de la Formule 1.",
    ],
    ids=["english_times", "german_umlauts", "french_short_domain"],
)
def test_clean_replies_are_left_alone(agent_dir: Path, text: str) -> None:
    ns = _load(agent_dir, "totto_root_agent")
    assert ns["after_model_callback"](None, _response(Part.from_text(text=text))) is None


def test_emoji_only_part_is_dropped_and_streaming_flags_survive(agent_dir: Path) -> None:
    ns = _load(agent_dir, "race_info_agent")
    result = ns["after_model_callback"](
        None,
        _response(Part.from_text(text="🏁🏆"), Part.from_text(text="George Russell is **fourth**."), partial=True),
    )
    assert [p.text for p in result.content.parts] == ["George Russell is fourth."]
    assert result.partial is True


def test_thought_parts_and_missing_content_are_not_touched(agent_dir: Path) -> None:
    ns = _load(agent_dir, "merch_support_agent")
    thought = SimpleNamespace(text="**internal plan**", thought=True)
    assert ns["after_model_callback"](None, SimpleNamespace(content=SimpleNamespace(parts=[thought]))) is None
    assert ns["after_model_callback"](None, SimpleNamespace(content=None)) is None


def test_unexpected_errors_fail_open(agent_dir: Path, capsys: pytest.CaptureFixture[str]) -> None:
    ns = _load(agent_dir, "ticketing_agent")

    class Exploding:
        @property
        def content(self):
            raise RuntimeError("platform object changed")

    assert ns["after_model_callback"](None, Exploding()) is None
    assert "left response unchanged after RuntimeError" in capsys.readouterr().out


@pytest.mark.parametrize(
    ("raw", "spoken"),
    [
        ("### Standings\n1. George Russell\n2) Kimi Antonelli", "Standings\nGeorge Russell\nKimi Antonelli"),
        ("See [tickets.formula1.com](https://tickets.formula1.com/) now", "See tickets.formula1.com now"),
        ("Go to www.mercedesamgf1.com/ today", "Go to mercedesamgf1.com today"),
        ("Use `get_race_schedule` ```python", "Use get_race_schedule"),
        ("London -> Tokyo => Sydney", "London - Tokyo - Sydney"),
        ("Order #1003 is __delivered__ * thanks", "Order 1003 is delivered thanks"),
        ("calling tool end_session...", ""),
    ],
    ids=[
        "heading_numbered_list",
        "link_with_domain_label",
        "www_trailing_slash",
        "code",
        "arrows",
        "hash_bold_stray",
        "calling_tool_narration",
    ],
)
def test_clean_spoken_text_examples(agent_dir: Path, raw: str, spoken: str) -> None:
    ns = _load(agent_dir, "totto_root_agent")
    assert ns["clean_spoken_text"](raw) == spoken
