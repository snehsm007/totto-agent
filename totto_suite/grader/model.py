"""Normalized conversation model (plan.md §4.4).

Every source (harness sims/probes JSON, SCRAPI simulation results, CXAS
conversation history) is converted into the same plain, JSON-serializable
dict so that one set of deterministic checks can grade all of them::

    {"id": str, "session_id": str | None, "source": str,
     "modality": "text" | "audio",
     "turns": [
        {"role": "user", "text": str, "event": str | None,
         "trace_index": int | None},
        {"role": "agent", "text": str, "texts": [str, ...],
         "tool_calls": [{"name", "args", "response", "response_text"}],
         "transfer": str | None, "transfers": [str, ...],
         "session_ended": bool, "escalated": bool | None,
         "latency_s": float | None, "audio_s": float | None,
         "greeting": bool, "trace_index": int | None},
     ],
     "meta": {...}}

``text`` is the agent's spoken/written reply (all text segments joined with
"\\n", exactly like ``scripts/analyze_transcripts.py`` joins them); ``texts``
keeps the individual segments so checks that look at "the last thing said
before a handoff" can match the reference checker byte for byte.
``trace_index`` points back into the source ``detailed_trace`` list (when the
source has one) so every flag can be located in the original file.
"""

from __future__ import annotations

from typing import Any, Iterator

WELCOME_EVENT = "welcome"


def user_turn(
    text: str, *, event: str | None = None, trace_index: int | None = None
) -> dict[str, Any]:
    return {
        "role": "user",
        "text": text or "",
        "event": event,
        "trace_index": trace_index,
    }


def tool_call(
    name: str,
    args: Any = None,
    response: Any = None,
    response_text: str | None = None,
) -> dict[str, Any]:
    return {
        "name": name or "",
        "args": args if args is not None else {},
        "response": response,
        "response_text": response_text,
    }


def agent_turn(
    texts: list[str] | tuple[str, ...] | str | None = None,
    *,
    tool_calls: list[dict[str, Any]] | None = None,
    transfers: list[str] | None = None,
    session_ended: bool = False,
    escalated: bool | None = None,
    latency_s: float | None = None,
    audio_s: float | None = None,
    greeting: bool = False,
    trace_index: int | None = None,
) -> dict[str, Any]:
    if texts is None:
        texts = []
    elif isinstance(texts, str):
        texts = [texts]
    texts = [t for t in texts if t is not None]
    transfers = list(transfers or [])
    return {
        "role": "agent",
        "text": "\n".join(texts),
        "texts": list(texts),
        "tool_calls": list(tool_calls or []),
        "transfer": transfers[-1] if transfers else None,
        "transfers": transfers,
        "session_ended": bool(session_ended),
        "escalated": escalated,
        "latency_s": latency_s,
        "audio_s": audio_s,
        "greeting": bool(greeting),
        "trace_index": trace_index,
    }


def conversation(
    conv_id: str,
    turns: list[dict[str, Any]],
    *,
    session_id: str | None = None,
    source: str = "",
    modality: str = "text",
    meta: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "id": conv_id,
        "session_id": session_id or None,
        "source": source,
        "modality": "audio" if str(modality).lower() == "audio" else "text",
        "turns": turns,
        "meta": dict(meta or {}),
    }


def agent_turns(conv: dict[str, Any]) -> Iterator[tuple[int, dict[str, Any]]]:
    """Yields (turn_index, turn) for agent turns."""
    for i, t in enumerate(conv.get("turns") or []):
        if t.get("role") == "agent":
            yield i, t


def texts_of(turn: dict[str, Any]) -> list[str]:
    texts = turn.get("texts")
    if texts is None:
        text = turn.get("text") or ""
        return [text] if text else []
    return [t for t in texts if t is not None]


def previous_user_text(conv: dict[str, Any], turn_index: int) -> str:
    """Text of the closest user turn before ``turn_index`` ('' if none)."""
    turns = conv.get("turns") or []
    for j in range(turn_index - 1, -1, -1):
        if turns[j].get("role") == "user":
            return turns[j].get("text") or ""
    return ""
