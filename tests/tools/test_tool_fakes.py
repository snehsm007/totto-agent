"""Tool fakes (R2): enabled, always a dict, always marked ``_fake``, deterministic.

The platform runs ``tool_fake_config/code_block/python_code.py`` instead of the
real tool when a session uses tool fakes (eval ``toolCallBehaviour=FAKE``) and
the tool's ``toolFakeConfig.enableFakeMode`` is true. The gate tells fake
results apart from real ones by the ``_fake`` marker, so every payload path
(success, clarification, error, bad input) must carry it.
"""

from __future__ import annotations

import datetime as _dt
import json

import pytest

TOOLS = {
    "get_race_schedule": [
        {"race_query": "next", "user_timezone": "Europe/London"},
        {"race_query": "Monaco", "user_timezone": "Edinburgh"},
        {"race_query": "Atlantis Grand Prix"},
        {"race_query": ""},
        {},
    ],
    "get_driver_standings": [
        {"championship_type": "constructors"},
        {"championship_type": "drivers"},
        {"championship_type": "nonsense"},
        {},
    ],
    "get_official_links": [
        {"link_type": "tickets"},
        {"link_type": "merch"},
        {"link_type": "does-not-exist"},
        {},
    ],
    "lookup_mock_merch_order": [
        {"order_id": "MB-2026-0001"},
        {"order_id": "not-an-order"},
        {},
    ],
}
BAD_INPUTS = [None, "next", 42, ["x"]]


def _load_fake(agent_dir, name: str, now: _dt.datetime | None = None):
    path = agent_dir / "tools" / name / "tool_fake_config" / "code_block" / "python_code.py"
    ns: dict[str, object] = {"Tool": object, "CallbackContext": object}
    exec(compile(path.read_text(encoding="utf-8"), str(path), "exec"), ns)  # noqa: S102
    if now is not None and "datetime" in ns:

        class _Frozen(_dt.datetime):
            @classmethod
            def now(cls, tz=None):
                return now if tz is None else now.astimezone(tz)

        ns["datetime"] = _Frozen
    return ns["fake_tool_call"]


@pytest.mark.parametrize("name", sorted(TOOLS))
def test_tool_fake_mode_is_enabled_in_tool_json(agent_dir, name: str) -> None:
    cfg = json.loads((agent_dir / "tools" / name / f"{name}.json").read_text(encoding="utf-8"))
    assert cfg["toolFakeConfig"]["enableFakeMode"] is True


@pytest.mark.parametrize("name", sorted(TOOLS))
def test_every_fake_payload_is_a_marked_dict_even_for_bad_input(agent_dir, name: str) -> None:
    fake = _load_fake(agent_dir, name)
    for inp in TOOLS[name] + BAD_INPUTS:
        res = fake(None, inp, None)
        assert isinstance(res, dict), f"{name}({inp!r}) returned {type(res).__name__}"
        assert res.get("_fake") is True, f"{name}({inp!r}) lacks _fake: {res}"
        assert "FAKE" in str(res.get("fake_source", "")), f"{name}({inp!r}) lacks fake_source"
        assert res.get("status") in ("success", "error"), f"{name}({inp!r}): {res}"


@pytest.mark.parametrize("name", sorted(TOOLS))
def test_fake_payloads_are_deterministic(agent_dir, name: str) -> None:
    now = _dt.datetime(2026, 9, 29, 12, 0, tzinfo=_dt.timezone.utc)
    fake = _load_fake(agent_dir, name, now)
    for inp in TOOLS[name]:
        assert fake(None, inp, None) == fake(None, inp, None)


def test_race_fake_next_follows_the_clock_and_ends_with_the_season(agent_dir) -> None:
    before_monaco = _dt.datetime(2026, 6, 1, 0, 0, tzinfo=_dt.timezone.utc)
    after_season = _dt.datetime(2026, 12, 31, 0, 0, tzinfo=_dt.timezone.utc)
    early = _load_fake(agent_dir, "get_race_schedule", before_monaco)(None, {"race_query": "next"}, None)
    late = _load_fake(agent_dir, "get_race_schedule", after_season)(None, {"race_query": "next"}, None)
    assert early["status"] == "success" and "Monaco" in early["race_name"]
    assert late["status"] == "error" and late["agent_action"] == "SEASON_2026_CONCLUDED"
    assert early["_fake"] is True and late["_fake"] is True


def test_race_fake_unknown_race_asks_for_clarification(agent_dir) -> None:
    res = _load_fake(agent_dir, "get_race_schedule")(None, {"race_query": "Atlantis Grand Prix"}, None)
    assert res["agent_action"] == "CLARIFY_RACE_NAME" and res["_fake"] is True
