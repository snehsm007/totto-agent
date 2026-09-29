"""Adapters: every transcript source -> normalized Conversation (model.py).

Sources:
- harness / SCRAPI simulation result rows (``detailed_trace`` strings made of
  ``Agent Text:`` / ``Tool Call:`` / ``Tool Response:`` / ``Agent Transfer:`` /
  ``User Query:`` / ``User:`` blocks). ``totto_test_harness.py sims`` stores
  SCRAPI's ``SimulationEvals.run_simulations`` result dicts verbatim, so one
  adapter serves both;
- harness probes rows (``turns`` with user/agent/tools/transfer/latency_s/
  session_ended; tool *responses* only exist in ``detailed_trace``);
- CXAS conversation history (``Conversation`` proto converted with
  ``type(c).to_dict(c)``: ``turns[].messages[].chunks[]`` + ``event_time`` +
  ``root_span``).

All adapters are tolerant (Postel): unknown blocks/chunks are skipped and
missing fields never raise.
"""

from __future__ import annotations

import ast
import datetime as _dt
import json
import re
from typing import Any, Iterable

from totto_suite.grader import model

# Same prefixes and splitting rules as scripts/analyze_transcripts.py so the
# texts the checks see are byte-identical to what the reference checker sees.
TRACE_PREFIXES = (
    "Agent Text:",
    "Tool Call:",
    "Tool Response:",
    "Agent Transfer:",
    "User Query:",
    "User:",
)
_AGENT_KINDS = {"Agent Text:", "Tool Call:", "Tool Response:", "Agent Transfer:"}
_EVENT_RE = re.compile(
    r"^\s*(?:event:\s*(?P<a>[\w ]+)|<event>\s*(?P<b>[^<]*)</event>|<(?P<c>welcome)>)\s*$",
    re.I,
)
END_SESSION_TOOLS = {"end_session"}


def parse_blocks(entry: str) -> list[list[str]]:
    """Splits one trace entry into [kind, text] pairs; continuation lines join.

    Identical semantics to ``blocks()`` in scripts/analyze_transcripts.py.
    """
    out: list[list[str]] = []
    for line in str(entry or "").split("\n"):
        kind = next((p for p in TRACE_PREFIXES if line.startswith(p)), None)
        if kind:
            out.append([kind, line[len(kind) :].strip()])
        elif out:
            out[-1][1] += "\n" + line
    return out


def event_name(text: str) -> str | None:
    """'welcome' for session-start events ('event: welcome', '<welcome>', ...)."""
    m = _EVENT_RE.match(text or "")
    if not m:
        return None
    name = (m.group("a") or m.group("b") or m.group("c") or "").strip().lower()
    if "welcome" in name or "session start" in name or not name:
        return model.WELCOME_EVENT
    return name


def _literal(text: str) -> Any:
    """Parses a Python-repr or JSON value; returns None when it can't."""
    text = (text or "").strip()
    if not text:
        return None
    try:
        return ast.literal_eval(text)
    except (ValueError, SyntaxError, MemoryError, RecursionError, TypeError):
        pass
    try:
        return json.loads(text)
    except (ValueError, TypeError):
        return None


def _split_named(text: str, marker: str) -> tuple[str, str]:
    """'get_x with args {..}' -> ('get_x', '{..}'). Name = first token (parity)."""
    name = text.split(" ", 1)[0] if text else ""
    idx = text.find(marker)
    rest = text[idx + len(marker) :] if idx >= 0 else ""
    return name, rest


def _transfer_target(text: str) -> str:
    target = text.strip()
    if target.lower().startswith("transferred to "):
        target = target[len("transferred to ") :]
    if "->" in target:
        target = target.rsplit("->", 1)[1]
    return target.strip()


def _attach_response(calls: list[dict], name: str, response: Any, raw: str) -> None:
    """Matches a response to the latest unanswered call of the same tool
    (SCRAPI ``_match_tool_response`` semantics); orphan responses are kept."""
    for call in reversed(calls):
        if call["name"] == name and call["response_text"] is None:
            call["response"] = response
            call["response_text"] = raw
            return
    calls.append(model.tool_call(name, {}, response, raw))


def _agent_turn_from_blocks(
    parts: list[list[str]], *, greeting: bool, trace_index: int | None
) -> dict[str, Any]:
    texts: list[str] = []
    calls: list[dict] = []
    transfers: list[str] = []
    ended = False
    escalated = None
    for kind, text in parts:
        if kind == "Agent Text:":
            texts.append(text)
        elif kind == "Tool Call:":
            name, rest = _split_named(text, " with args ")
            args = _literal(rest)
            call = model.tool_call(name, args if args is not None else rest)
            calls.append(call)
            if name in END_SESSION_TOOLS:
                ended = True
                if isinstance(args, dict) and "session_escalated" in args:
                    escalated = bool(args.get("session_escalated"))
        elif kind == "Tool Response:":
            name, rest = _split_named(text, " with result ")
            _attach_response(calls, name, _literal(rest), rest)
        elif kind == "Agent Transfer:":
            transfers.append(_transfer_target(text))
    return model.agent_turn(
        texts,
        tool_calls=calls,
        transfers=transfers,
        session_ended=ended,
        escalated=escalated,
        greeting=greeting,
        trace_index=trace_index,
    )


def turns_from_trace(trace: Iterable[Any]) -> list[dict[str, Any]]:
    """Converts a ``detailed_trace`` list into normalized turns."""
    turns: list[dict[str, Any]] = []
    for idx, entry in enumerate(trace or []):
        if not isinstance(entry, str):
            continue
        parts = parse_blocks(entry)
        user_parts = [t for k, t in parts if k == "User:"]
        queries = [t for k, t in parts if k == "User Query:"]
        agent_parts = [p for p in parts if p[0] in _AGENT_KINDS]
        for text in user_parts:
            turns.append(model.user_turn(text, event=event_name(text), trace_index=idx))
        if not agent_parts and not (queries and not user_parts):
            continue
        if queries and (not turns or turns[-1]["role"] != "user"):
            # Traces that only carry the user's words as 'User Query:'.
            text = "\n".join(queries)
            turns.append(model.user_turn(text, event=event_name(text), trace_index=idx))
        greeting = bool(
            (turns and turns[-1]["role"] == "user" and turns[-1].get("event"))
            or any(event_name(q) for q in queries)
        )
        if agent_parts:
            turns.append(
                _agent_turn_from_blocks(agent_parts, greeting=greeting, trace_index=idx)
            )
    return turns


def _naturalness_latencies(row: dict[str, Any]) -> dict[int, float]:
    details = row.get("naturalness_details")
    if not isinstance(details, dict):
        return {}
    raw = details.get("latency_ms_by_turn") or {}
    out: dict[int, float] = {}
    if isinstance(raw, dict):
        for k, v in raw.items():
            try:
                out[int(k)] = float(v) / 1000.0
            except (TypeError, ValueError):
                continue
    return out


def from_sim_row(
    row: dict[str, Any], *, modality: str = "text", source: str = "sims"
) -> dict[str, Any]:
    """One SCRAPI/harness simulation result row -> Conversation."""
    row = row if isinstance(row, dict) else {}
    name = str(row.get("name", "unnamed"))
    run = row.get("run")
    turns = turns_from_trace(row.get("detailed_trace") or [])
    # Perceived latency (naturalness metric) is keyed by speech index: the
    # n-th agent turn that produced text.
    latencies = _naturalness_latencies(row)
    if latencies:
        speech = 0
        for t in turns:
            if t["role"] == "agent" and t["text"].strip():
                if speech in latencies:
                    t["latency_s"] = latencies[speech]
                speech += 1
    meta = {
        "name": name,
        "run": run,
        "judge_passed": row.get("passed"),
        "goals": row.get("goals"),
        "expectations": row.get("expectations"),
        "expectation_details": row.get("expectation_details") or [],
        "step_details": row.get("step_details") or [],
        "duration_s": row.get("duration_s"),
        "error": row.get("error"),
        "session_parameters": row.get("session_parameters") or {},
    }
    return model.conversation(
        f"{name}#run{run}" if run is not None else name,
        turns,
        session_id=row.get("session_id"),
        source=source,
        modality=row.get("modality") or modality,
        meta=meta,
    )


def _rows(data: Any) -> list[dict[str, Any]]:
    if isinstance(data, dict):
        rows = data.get("results") or []
    elif isinstance(data, list):
        rows = data
    else:
        rows = []
    return [r for r in rows if isinstance(r, dict)]


def from_harness_sims(data: Any, *, source: str = "harness_sims") -> list[dict[str, Any]]:
    modality = data.get("modality", "text") if isinstance(data, dict) else "text"
    return [from_sim_row(r, modality=modality, source=source) for r in _rows(data)]


# SCRAPI's run_simulations() returns exactly these row dicts.
from_scrapi_sim_result = from_sim_row


def from_scrapi_sim_results(results: Iterable[dict[str, Any]], *, modality: str = "text"):
    return [from_sim_row(r, modality=modality, source="scrapi_sims") for r in results or []]


def _probe_turns(row: dict[str, Any]) -> list[dict[str, Any]]:
    turns: list[dict[str, Any]] = []
    for t in row.get("turns") or []:
        if not isinstance(t, dict):
            continue
        user = str(t.get("user") or "")
        event = event_name(user)
        turns.append(model.user_turn("" if event else user, event=event))
        agent = t.get("agent") or []
        if isinstance(agent, str):
            agent = [agent]
        calls = []
        for tool in t.get("tools") or []:
            if isinstance(tool, dict):
                calls.append(model.tool_call(str(tool.get("name", "")), tool.get("args") or {}))
        transfer = t.get("transfer")
        turns.append(
            model.agent_turn(
                [str(a) for a in agent],
                tool_calls=calls,
                transfers=[str(transfer)] if transfer else [],
                session_ended=bool(t.get("session_ended")),
                latency_s=_float(t.get("latency_s")),
                greeting=bool(event),
            )
        )
    return turns


def _float(v: Any) -> float | None:
    try:
        return float(v) if v is not None else None
    except (TypeError, ValueError):
        return None


def from_probe_row(row: dict[str, Any], *, source: str = "probes") -> dict[str, Any]:
    """One harness probe row -> Conversation.

    Text, tool calls and tool responses come from ``detailed_trace``; latency,
    session end and transfer come from ``turns``. When the two can't be
    aligned one-to-one, ``turns`` alone is used (no tool responses).
    """
    row = row if isinstance(row, dict) else {}
    trace_turns = turns_from_trace(row.get("detailed_trace") or [])
    probe_turns = _probe_turns(row)
    trace_agents = [t for t in trace_turns if t["role"] == "agent"]
    probe_agents = [t for t in probe_turns if t["role"] == "agent"]
    if trace_agents and len(trace_agents) == len(probe_agents):
        turns = trace_turns
        for tt, pt in zip(trace_agents, probe_agents):
            tt["latency_s"] = pt["latency_s"]
            tt["session_ended"] = tt["session_ended"] or pt["session_ended"]
            if not tt["transfers"] and pt["transfers"]:
                tt["transfers"] = pt["transfers"]
                tt["transfer"] = pt["transfer"]
            if not tt["tool_calls"] and pt["tool_calls"]:
                tt["tool_calls"] = pt["tool_calls"]
    else:
        turns = probe_turns
    name = str(row.get("name", "unnamed"))
    run = row.get("run")
    meta = {
        "name": name,
        "run": run,
        "judge_passed": row.get("passed"),
        "expectation_details": row.get("expectation_details") or [],
        "duration_s": row.get("duration_s"),
        "quota_wait_s": row.get("quota_wait_s"),
        "error": row.get("error"),
    }
    return model.conversation(
        f"{name}#run{run}" if run is not None else name,
        turns,
        session_id=row.get("session_id"),
        source=source,
        modality="text",
        meta=meta,
    )


def from_harness_probes(data: Any, *, source: str = "harness_probes") -> list[dict[str, Any]]:
    return [from_probe_row(r, source=source) for r in _rows(data)]


# --- CXAS conversation history ------------------------------------------------


def _ts(value: Any) -> _dt.datetime | None:
    """RFC3339 string / {'seconds','nanos'} / datetime -> aware datetime."""
    if value is None or value == "":
        return None
    if isinstance(value, _dt.datetime):
        return value if value.tzinfo else value.replace(tzinfo=_dt.timezone.utc)
    if isinstance(value, dict):
        try:
            secs = float(value.get("seconds", 0)) + float(value.get("nanos", 0)) / 1e9
            return _dt.datetime.fromtimestamp(secs, tz=_dt.timezone.utc)
        except (TypeError, ValueError):
            return None
    text = str(value).strip().replace("Z", "+00:00")
    # Python < 3.11 can't parse >6 fractional digits; trim them.
    text = re.sub(r"(\.\d{6})\d+", r"\1", text)
    try:
        parsed = _dt.datetime.fromisoformat(text)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=_dt.timezone.utc)


def _duration_s(value: Any) -> float | None:
    """'1.131740s' / {'seconds','nanos'} / timedelta / number -> seconds."""
    if value is None or value == "":
        return None
    if isinstance(value, _dt.timedelta):
        return value.total_seconds()
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, dict):
        try:
            return float(value.get("seconds", 0)) + float(value.get("nanos", 0)) / 1e9
        except (TypeError, ValueError):
            return None
    m = re.match(r"^\s*([\d.]+)\s*s?\s*$", str(value))
    return float(m.group(1)) if m else None


def _short_name(value: Any) -> str:
    return str(value or "").rstrip("/").rsplit("/", 1)[-1]


def _chunk_text(chunk: dict[str, Any]) -> str | None:
    for key in ("text", "transcript"):
        if isinstance(chunk.get(key), str) and chunk.get(key).strip():
            return chunk[key]
    return None


def from_conversation_history(conv: Any, *, source: str = "conversation_history") -> dict[str, Any]:
    """CXAS ``Conversation`` (dict from ``type(c).to_dict(c)``) -> Conversation."""
    if not isinstance(conv, dict):
        to_dict = getattr(type(conv), "to_dict", None)
        conv = to_dict(conv) if callable(to_dict) else {}
    platform_turns = conv.get("turns") or []
    if not platform_turns and conv.get("messages"):
        platform_turns = [{"messages": conv.get("messages")}]
    turns: list[dict[str, Any]] = []
    for p_turn in platform_turns:
        if not isinstance(p_turn, dict):
            continue
        user_texts: list[str] = []
        user_time = None
        agent_texts: list[str] = []
        agent_first_time = None
        calls: list[dict] = []
        by_id: dict[str, dict] = {}
        transfers: list[str] = []
        ended = False
        escalated = None
        saw_user_msg = False
        for msg in p_turn.get("messages") or []:
            if not isinstance(msg, dict):
                continue
            role = str(msg.get("role") or "").lower()
            when = _ts(msg.get("event_time"))
            chunks = [c for c in msg.get("chunks") or [] if isinstance(c, dict)]
            if role == "user":
                saw_user_msg = True
                user_texts.extend(t for t in (_chunk_text(c) for c in chunks) if t)
                user_time = when or user_time
                continue
            if when and agent_first_time is None:
                agent_first_time = when
            for c in chunks:
                text = _chunk_text(c)
                if text:
                    agent_texts.append(text)
                elif isinstance(c.get("tool_call"), dict):
                    tc = c["tool_call"]
                    name = tc.get("display_name") or _short_name(tc.get("tool"))
                    args = tc.get("args") or {}
                    call = model.tool_call(name, args)
                    calls.append(call)
                    if tc.get("id"):
                        by_id[str(tc["id"])] = call
                    if name in END_SESSION_TOOLS:
                        ended = True
                        if isinstance(args, dict) and "session_escalated" in args:
                            escalated = bool(args.get("session_escalated"))
                elif isinstance(c.get("tool_response"), dict):
                    tr = c["tool_response"]
                    name = tr.get("display_name") or _short_name(tr.get("tool"))
                    resp = tr.get("response")
                    raw = json.dumps(resp, sort_keys=True, default=str)
                    target = by_id.get(str(tr.get("id"))) if tr.get("id") else None
                    if target is not None and target["response_text"] is None:
                        target["response"] = resp
                        target["response_text"] = raw
                    else:
                        _attach_response(calls, name, resp, raw)
                elif isinstance(c.get("agent_transfer"), dict):
                    at = c["agent_transfer"]
                    transfers.append(at.get("display_name") or _short_name(at.get("target_agent")))
        user_text = " ".join(user_texts).strip()
        event = None
        if saw_user_msg and not user_text:
            event = model.WELCOME_EVENT if not turns else "event"
        elif user_text:
            event = event_name(user_text)
        if saw_user_msg:
            turns.append(model.user_turn(user_text if not event else "", event=event))
        latency = None
        if user_time and agent_first_time:
            latency = max(0.0, (agent_first_time - user_time).total_seconds())
        if latency is None:
            span = p_turn.get("root_span") or {}
            latency = _duration_s(span.get("duration")) if isinstance(span, dict) else None
        if agent_texts or calls or transfers:
            turns.append(
                model.agent_turn(
                    agent_texts,
                    tool_calls=calls,
                    transfers=transfers,
                    session_ended=ended,
                    escalated=escalated,
                    latency_s=latency,
                    greeting=bool(event == model.WELCOME_EVENT),
                )
            )
    channel = conv.get("channel_type")
    modality = "audio" if channel in (2, "AUDIO", "CHANNEL_TYPE_AUDIO") else "text"
    name = str(conv.get("name") or "")
    session_id = _short_name(name) or None
    meta = {
        "name": name,
        "source_enum": conv.get("source"),
        "app_version": conv.get("app_version"),
        "language_code": conv.get("language_code"),
        "start_time": str(conv.get("start_time") or ""),
        "end_time": str(conv.get("end_time") or ""),
        "entry_agent": conv.get("entry_agent"),
    }
    return model.conversation(
        session_id or "conversation",
        turns,
        session_id=session_id,
        source=source,
        modality=modality,
        meta=meta,
    )


def load_conversations(data: Any, *, kind: str | None = None, source: str | None = None):
    """Dispatches on the file shape: probes rows have ``turns`` lists."""
    rows = _rows(data)
    if kind is None:
        kind = "probes" if any(isinstance(r.get("turns"), list) for r in rows) else "sims"
    if kind == "probes":
        return from_harness_probes(data, source=source or "harness_probes")
    return from_harness_sims(data, source=source or "harness_sims")
