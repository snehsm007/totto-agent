"""Regression tests for PyPI cxas-scrapi==1.9.1 ConversationHistory(transport=...) TypeError fallback."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import cxas_scrapi.core.conversation_history as ch_mod

from totto_suite import cxasapi, verify_ids
from totto_suite.layers import live_sims
from totto_suite.live import runner


class _PyPIConversationHistory:
    """Simulates PyPI cxas-scrapi==1.9.1 where transport='rest' raises TypeError."""

    calls: list[tuple[tuple, dict]] = []

    def __init__(self, *args, **kwargs):
        self.calls.append((args, dict(kwargs)))
        if "transport" in kwargs:
            raise TypeError(
                "Common.__init__() got an unexpected keyword argument 'transport'"
            )
        self.app_name = kwargs.get("app_name") or (args[0] if args else "")

    def get_conversation(self, conv_id: str):
        cid = conv_id.rsplit("/", 1)[-1]
        return SimpleNamespace(name=f"{self.app_name}/conversations/{cid}", turns=[])

    def list_conversations(self, **_kwargs):
        return []


def test_cxasapi_history_falls_back_when_transport_rejected():
    _PyPIConversationHistory.calls = []
    with patch.object(ch_mod, "ConversationHistory", _PyPIConversationHistory):
        client = cxasapi._history("projects/p/locations/us/apps/a")
        assert isinstance(client, _PyPIConversationHistory)
        assert len(_PyPIConversationHistory.calls) == 2
        assert "transport" in _PyPIConversationHistory.calls[0][1]
        assert "transport" not in _PyPIConversationHistory.calls[1][1]


def test_runner_make_conversation_history_falls_back_when_transport_rejected():
    _PyPIConversationHistory.calls = []
    with patch.object(runner, "ConversationHistory", _PyPIConversationHistory):
        res = runner.resolve_conversation_resource(
            "projects/p/locations/us/apps/a", "sess-123"
        )
        assert res == "projects/p/locations/us/apps/a/conversations/sess-123"
        assert len(_PyPIConversationHistory.calls) == 2
        assert "transport" not in _PyPIConversationHistory.calls[1][1]


def test_verify_ids_conversation_falls_back_when_transport_rejected():
    _PyPIConversationHistory.calls = []
    record = {
        "run_id": "test-pypi-fallback",
        "tests": [
            {
                "id": "live_sims::sim_1",
                "status": "PASS",
                "platform_ids": {"conversation": "conversations/conv-abc"},
            }
        ],
    }
    with patch.object(ch_mod, "ConversationHistory", _PyPIConversationHistory):
        report = verify_ids.verify_run_record(
            record, app_name="projects/p/locations/us/apps/a"
        )
        assert report["verified_test_entries"] == 1
        assert report["failed_test_entries"] == 0
        assert len(_PyPIConversationHistory.calls) == 2
        assert "transport" not in _PyPIConversationHistory.calls[1][1]


def test_live_sims_constructs_conversation_history_without_transport_crash(tmp_path):
    _PyPIConversationHistory.calls = []

    class _DummySim:
        def __init__(self, app_name: str):
            self.app_name = app_name
            self.max_retries = 1
            self.retry_delay_base = 1

    with (
        patch.object(live_sims, "ConversationHistory", _PyPIConversationHistory),
        patch.object(live_sims, "SimulationEvals", _DummySim),
        patch.object(live_sims, "_load_simulations", return_value=[]),
        patch.object(live_sims, "_load_probes", return_value=[]),
    ):
        results = live_sims.run(
            {
                "app_name": "projects/p/locations/us/apps/a",
                "repeats": 1,
                "artifacts_dir": str(tmp_path),
                "tool_mode": "fake",
            }
        )
        assert results == []
        assert len(_PyPIConversationHistory.calls) == 2
        assert "transport" not in _PyPIConversationHistory.calls[1][1]
