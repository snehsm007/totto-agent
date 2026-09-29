"""Tool-fake evidence: tell fake tool results apart from real ones (R2).

The platform runs a tool's ``toolFakeConfig`` code instead of the real tool
only when the session has ``useToolFakes`` (eval ``toolCallBehaviour=FAKE``)
and the tool has ``toolFakeConfig.enableFakeMode``. Evidence it did so:

* the conversation / evaluation trace has a span named ``Fake Tool`` with
  ``attributes.type == "ToolFake"`` (a real call is a span named ``Tool``
  with e.g. ``attributes.type == "PythonFunctionTool"``);
* our fake payloads carry ``"_fake": True`` (real payloads never do).

``fake_verified`` for one test is True only if at least one fake tool call
is seen and no real app-tool call is seen; False if a real app-tool call is
seen (or fakes were not requested); None if the test made no tool calls at
all (nothing to verify).
"""

from __future__ import annotations

import json
from typing import Any

FAKE_SPAN_NAME = "Fake Tool"
FAKE_SPAN_TYPE = "ToolFake"
REAL_TOOL_SPAN_NAME = "Tool"
# Platform-internal tool spans that are not app tools (agent transfer etc.).
SYSTEM_TOOL_TYPES = {"TransferToAgentTool", "EndSessionTool", "SystemTool"}


def _as_dict(obj: Any) -> Any:
    if obj is None or isinstance(obj, (dict, list, str, int, float, bool)):
        return obj
    to_dict = getattr(type(obj), "to_dict", None)
    if callable(to_dict):
        try:
            return to_dict(obj)
        except Exception:  # noqa: BLE001
            pass
    return obj


def _attr(attrs: Any, key: str) -> Any:
    if isinstance(attrs, dict):
        return attrs.get(key)
    return None


def span_evidence(obj: Any, app_tool_names: set[str] | None = None) -> dict[str, Any]:
    """Counts fake/real tool spans and ``_fake`` payload markers in ``obj``.

    ``obj`` may be a conversation, an evaluation result, a session row or any
    nested dict/list (proto-plus messages are converted with ``to_dict``).
    """
    counts = {
        "fake_tool_spans": 0,
        "real_tool_spans": 0,
        "fake_markers": 0,
        "fake_tools": [],
        "real_tools": [],
    }
    names = set(app_tool_names or ())

    def visit(node: Any) -> None:
        node = _as_dict(node)
        if isinstance(node, dict):
            attrs = node.get("attributes")
            span_name = node.get("name")
            if isinstance(attrs, dict) and isinstance(span_name, str):
                a_type = _attr(attrs, "type")
                a_name = _attr(attrs, "name")
                if span_name == FAKE_SPAN_NAME or a_type == FAKE_SPAN_TYPE:
                    counts["fake_tool_spans"] += 1
                    counts["fake_tools"].append(str(a_name or ""))
                elif span_name == REAL_TOOL_SPAN_NAME and a_type not in SYSTEM_TOOL_TYPES and (
                    not names or str(a_name) in names or a_type == "PythonFunctionTool"
                ):
                    counts["real_tool_spans"] += 1
                    counts["real_tools"].append(str(a_name or ""))
            if node.get("_fake") is True:
                counts["fake_markers"] += 1
            for value in node.values():
                visit(value)
        elif isinstance(node, list):
            for value in node:
                visit(value)
        elif isinstance(node, str) and "_fake" in node and node[:1] in "{[":
            # Payloads are sometimes stored as JSON strings.
            try:
                visit(json.loads(node))
            except ValueError:
                if "'_fake': True" in node or '"_fake": true' in node:
                    counts["fake_markers"] += 1

    visit(obj)
    counts["fake_tools"] = sorted(set(counts["fake_tools"]) - {""})
    counts["real_tools"] = sorted(set(counts["real_tools"]) - {""})
    return counts


def fake_verified(tool_mode: str, evidence: dict[str, Any] | None) -> bool | None:
    """Per-test verdict (see module docstring)."""
    if str(tool_mode).lower() != "fake":
        return False
    if not evidence:
        return None
    fake_seen = evidence.get("fake_tool_spans", 0) > 0 or evidence.get("fake_markers", 0) > 0
    real_seen = evidence.get("real_tool_spans", 0) > 0
    if real_seen:
        return False
    if fake_seen:
        return True
    return None


def run_fake_verified(tests: list[dict[str, Any]], tool_mode: str) -> bool:
    """Run-level verdict: fakes requested, >=1 test verified, no test contradicted."""
    if str(tool_mode).lower() != "fake":
        return False
    verdicts = [t.get("fake_verified") for t in tests if t.get("tool_mode") == "fake"]
    return any(v is True for v in verdicts) and not any(v is False for v in verdicts)
