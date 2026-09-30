"""Deterministic transcript checks and ``grade(conv, gctx)``.

Every check is a pure function of the normalized Conversation (model.py) and
the grading context. Checks never look at session IDs, file names, test names
or expected counts: they only read what the agent said and did.

Result entries (one per flagged turn, or one ``pass``/``skip`` entry)::

    {"name", "passed", "status": "pass|fail|warn|skip", "turn_index",
     "trace_index", "evidence", "findings": [...]}

``warn`` = reported but not blocking (e.g. markdown in a *text* channel);
only ``fail`` makes ``grade()["passed"]`` False.
"""

from __future__ import annotations

import datetime as _dt
import re
import statistics
from typing import Any, Callable

from totto_suite.grader import model
from totto_suite.grader import text as tx

# name -> finding IDs covered + one-line logic (rendered into the handoff/report).
CATALOGUE: dict[str, dict[str, Any]] = {
    "dead_air_handoff": {
        "findings": ["TR-03", "RC-08"],
        "logic": "turn transfers to another agent with no tool call and its last text segment is < 120 chars "
        "(scripts/analyze_transcripts.py parity); also any handoff turn slower than handoff_dead_air_s when timing exists",
    },
    "code_leak": {
        "findings": ["TR-02"],
        "logic": "agent text contains tool-call code: analyze.py LEAK regex (default_api., tool_code, print(, f(x='..')) "
        "plus f(x=<number|bool|{|[>), transfer_to_agent(, end_session(, ``` fences, <known tool>(",
    },
    "race_facts_without_tool": {
        "findings": ["TR-01", "TR-10", "RC-13"],
        "logic": "a sentence pairs a clock time (14:00, 7:30 AM, 2 PM, 15h30, 14 Uhr) or a current-season date with race "
        "context (Grand Prix/qualifying/practice/sprint/race + de/fr/es/it/pt words, or a timezone label) and no race "
        "schedule tool was called in or before that turn; values already present in another tool's response are grounded",
    },
    "race_fact_value_mismatch": {
        "findings": ["TR-10", "TR-01"],
        "logic": "a race-context clock time stated after the schedule tool ran matches no time in any tool response "
        "(nor in the user's words), e.g. the agent converted timezones itself",
    },
    "order_facts_without_tool": {
        "findings": ["TR-01"],
        "logic": "a generic order ID (#1234 or 'order 1234', any digits) is followed by an order status/tracking token "
        "and no order-lookup tool was called in or before that turn",
    },
    "order_fact_value_mismatch": {
        "findings": ["TR-01"],
        "logic": "a tracking number (e.g. DHL-MB-984210) stated in an order reply appears in no tool response",
    },
    "tool_error": {
        "findings": ["TR-08", "TB-3"],
        "logic": "a tool response has status=error (or an 'error' key); allowed only when its agent_action is in "
        "expected_error_actions AND every argument value came from the user's own words",
    },
    "internal_agent_names": {
        "findings": ["TR-05"],
        "logic": "agent text names an internal agent: snake_case *_agent ids, the conversation's own transfer targets "
        "and gctx agent_names, also humanized ('Race Info Agent', 'Race Info Agenten')",
    },
    "tts_unfriendly": {
        "findings": ["RC-06", "RC-07", "NEW-2"],
        "logic": "emoji or markdown (bold, headers, bullets, tables, links, inline code); in voice also symbols read "
        "aloud (#12, P4, raw URLs, arrows, stray */|). fail in voice, warn in text",
    },
    "reply_length": {
        "findings": ["NEW-2", "RC-06"],
        "logic": "reply over the voice budget (sentences, characters, or spoken seconds at words_per_minute). "
        "fail in voice, warn in text",
    },
    "latency_budget": {
        "findings": ["RC-08", "RC-03", "RC-09", "RC-10"],
        "logic": "a timed agent turn slower than max_turn_latency_s, or conversation p90 above p90_turn_latency_s "
        "(>= 5 timed turns); skipped when no timing exists",
    },
    "pci_echo": {
        "findings": ["NEW-3"],
        "logic": "agent text contains a 13-19 digit card-like number (Luhn-valid or echoed from the user) or claims a "
        "card/payment was charged/processed",
    },
    "language_match": {
        "findings": ["TR-04", "TR-06"],
        "logic": "a non-greeting agent text block/paragraph is confidently in another language than expected "
        "(fixed code, or 'auto' = the language of the user's latest confidently detected turn)",
    },
    "past_race_as_upcoming": {
        "findings": ["TB-5", "TR-09", "NEW-1"],
        "logic": "a race whose dates (from this turn's schedule tool response or from the reply itself) are before "
        "'now' is presented with upcoming wording (upcoming/next up/will take place/takes place/se déroulera/findet … "
        "statt/…) and no past wording",
    },
    "disclosure_mock": {
        "findings": ["TR-09", "PRD-AC5"],
        "logic": "from the first turn that states order facts to the end, no mock/simulated/demo disclosure is said",
    },
    "disclosure_freshness": {
        "findings": ["TR-09", "TB-1", "RC-03"],
        "logic": "from the first turn that states race schedule or standings facts backed by snapshot/non-live data "
        "(or by no tool), no latest-available/snapshot/as-of style disclosure is said",
    },
    "session_end_without_answer": {
        "findings": ["RC-02", "RC-10", "RC-01"],
        "logic": "user asked for a human/supervisor and the reply lacks an explanation plus an official next step; or "
        "the agent claims a human transfer / escalates via end_session(session_escalated=True); or the session ended "
        "with no reply to a question",
    },
    "repetitive_boilerplate": {
        "findings": ["NEW-2", "RC-06"],
        "logic": "agent repeats self-introduction ('I am Totto, Mercedes F1 Fan Agent') on >= 2 turns without being asked "
        "who it is, repeats 'According to the latest(-available)' on >= 2 turns, or repeats identical closing boilerplate "
        "questions on >= 2 turns",
    },
}

DEFAULT_THRESHOLDS: dict[str, float] = {
    "dead_air_text_chars": 120,  # scripts/analyze_transcripts.py parity
    "handoff_dead_air_s": 7.0,
    "max_turn_latency_s": 9.0,
    "p90_turn_latency_s": 7.0,
    "voice_max_sentences": 4,
    "voice_max_chars": 450,
    "voice_max_spoken_s": 25.0,
    "words_per_minute": 140,
    "language_min_words": 6,
}
DEFAULT_EXPECTED_ERROR_ACTIONS = ("OFFER_SAMPLE_ORDER_IDS", "PROMPT_FOR_ORDER_ID", "CLARIFY_RACE_NAME")
# Defaults for the app under test; callers may override via gctx.
DEFAULT_RACE_TOOLS = ("get_race_schedule",)
DEFAULT_ORDER_TOOLS = ("lookup_mock_merch_order",)
DEFAULT_TOOL_NAMES = (
    "get_race_schedule",
    "get_driver_standings",
    "lookup_mock_merch_order",
    "get_official_links",
    "end_session",
    "transfer_to_agent",
)
DEFAULT_AGENT_NAMES = ("totto_root_agent", "race_info_agent", "merch_support_agent", "ticketing_agent")


class Ctx:
    """Resolved grading context."""

    def __init__(self, gctx: dict[str, Any] | None, conv: dict[str, Any]):
        g = dict(gctx or {})
        self.now = _parse_now(g.get("now"))
        voice = g.get("voice")
        self.voice = bool(voice) if voice is not None else conv.get("modality") == "audio"
        self.expected_language = g.get("expected_language")
        self.t = dict(DEFAULT_THRESHOLDS)
        self.t.update(g.get("thresholds") or {})
        self.expected_error_actions = set(g.get("expected_error_actions", DEFAULT_EXPECTED_ERROR_ACTIONS))
        self.race_tools = set(g.get("race_tools", DEFAULT_RACE_TOOLS))
        self.order_tools = set(g.get("order_tools", DEFAULT_ORDER_TOOLS))
        self.tool_names = set(g.get("tool_names", DEFAULT_TOOL_NAMES))
        self.agent_names = set(g.get("agent_names", DEFAULT_AGENT_NAMES))
        self.calendar = g.get("calendar")
        self.disabled = set(g.get("disabled_checks") or [])

    def is_race_tool(self, name: str) -> bool:
        return name in self.race_tools or bool(re.search(r"schedule|calendar", name or "", re.I))

    def is_order_tool(self, name: str) -> bool:
        return name in self.order_tools or bool(re.search(r"order", name or "", re.I))


def _parse_now(value: Any) -> _dt.datetime | None:
    if value is None or value == "":
        return None
    if isinstance(value, _dt.datetime):
        return value if value.tzinfo else value.replace(tzinfo=_dt.timezone.utc)
    if isinstance(value, _dt.date):
        return _dt.datetime(value.year, value.month, value.day, tzinfo=_dt.timezone.utc)
    parsed = _dt.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=_dt.timezone.utc)


def _entry(name: str, status: str, turn_index: int | None, turn: dict | None, evidence: str, **extra) -> dict:
    out = {
        "name": name,
        "passed": status != "fail",
        "status": status,
        "turn_index": turn_index,
        "trace_index": (turn or {}).get("trace_index"),
        "evidence": evidence,
        "findings": list(CATALOGUE[name]["findings"]),
    }
    out.update(extra)
    return out


# --- shared helpers --------------------------------------------------------------


def _response_strings(call: dict) -> list[str]:
    resp = call.get("response")
    if resp is not None and not isinstance(resp, str):
        return list(tx.iter_strings(resp))
    raw = call.get("response_text")
    if isinstance(resp, str):
        return [resp]
    return [raw] if raw else []


def _calls_until(conv: dict, upto: int) -> list[dict]:
    out = []
    for i, t in enumerate(conv.get("turns") or []):
        if i > upto:
            break
        if t.get("role") == "agent":
            out.extend(t.get("tool_calls") or [])
    return out


def _user_text_until(conv: dict, upto: int) -> str:
    return "\n".join(
        t.get("text") or ""
        for i, t in enumerate(conv.get("turns") or [])
        if i <= upto and t.get("role") == "user"
    )


# Race context: session words (multilingual) or a timezone label (case-sensitive).
RACE_CONTEXT = re.compile(
    r"grand[s]? prix|\bgp\b|gran premio|grande pr[eê]mio|gro(?:ß|ss)e[nr]? preis|qualif\w*|clasificaci[oó]n|"
    r"practice|\bfp[123]\b|freie[sn]? training|\btraining\b|essais|pr[aá]cticas?\b|prove libere|\bsprint\b|"
    r"\brace\b|\brennen\b|\bcourse\b|\bcarrera\b|\bgara\b|\bcorrida\b|lights out|local time|ortszeit|"
    r"heure locale|hora local|ora locale",
    re.I,
)
TZ_LABEL = re.compile(
    r"\b(?:UTC|GMT|BST|CET|CEST|EET|EEST|WET|WEST|EST|EDT|CST|CDT|MST|MDT|PST|PDT|AKDT|HST|JST|KST|AEST|AEDT|"
    r"ACST|ACDT|AWST|NZST|NZDT|SGT|IST|BRT|ART|GST|MSK|MEZ|MESZ|ICT|HKT|PHT|WIB)\b|UTC[+-]\d"
)


def _race_fact_segments(text: str, ctx: Ctx) -> list[tuple[str, list, list]]:
    """[(segment, times, current-season dates)] for sentences that state race timing."""
    out = []
    default_year = ctx.now.year if ctx.now else None
    for seg in tx.segments(text):
        if not (RACE_CONTEXT.search(seg) or TZ_LABEL.search(seg)):
            continue
        times = tx.find_times(seg)
        dates = [
            d
            for d in tx.find_dates(seg, default_year=default_year)
            if not (ctx.now and d[4] and d[3] and d[3].year < ctx.now.year)
        ]
        if times or dates:
            out.append((seg, times, dates))
    return out


def _grounded(seg_times: list, seg_dates: list, strings: list[str]) -> bool:
    """True when every stated value literally appears in some tool response."""
    if not strings:
        return False
    tool_times: set[str] = set()
    tool_dates: set[tuple[int, int]] = set()
    for s in strings:
        tool_times |= _tool_time_values(s)
        for d in tx.find_dates(s):
            if d[3]:
                tool_dates.add((d[3].month, d[3].day))
    for _, _, _, cands in seg_times:
        if not (cands & tool_times):
            return False
    for d in seg_dates:
        if not d[3] or (d[3].month, d[3].day) not in tool_dates:
            return False
    return bool(seg_times or seg_dates)


def _tool_time_values(s: str) -> set[str]:
    """Tool output is machine-formatted: bare H:MM is 24-hour."""
    out: set[str] = set()
    for matched, _, _, cands in tx.find_times(s):
        if re.search(r"[AaPp]\.?\s?[Mm]", matched):
            out |= cands
        else:
            m = re.match(r"(\d{1,2})[:h.](\d{2})", matched.replace(" ", ""))
            out.add(f"{int(m.group(1)):02d}:{m.group(2)}" if m else next(iter(sorted(cands))))
    return out


# --- checks ------------------------------------------------------------------------


def check_dead_air_handoff(conv: dict, ctx: Ctx) -> list[dict]:
    out = []
    limit = ctx.t["dead_air_text_chars"]
    for i, turn in model.agent_turns(conv):
        transfers = turn.get("transfers") or ([turn["transfer"]] if turn.get("transfer") else [])
        if not transfers:
            continue
        reasons = []
        texts = model.texts_of(turn)
        if not turn.get("tool_calls") and (not texts or len(texts[-1]) < limit):
            last = texts[-1] if texts else ""
            reasons.append(
                f"handoff to {', '.join(transfers)} with no tool call; last text ({len(last)} chars): "
                f"'{tx.excerpt(last, 160)}' — the answer only comes after the user speaks again"
            )
        lat = turn.get("latency_s")
        if lat is not None and lat > ctx.t["handoff_dead_air_s"]:
            reasons.append(f"handoff turn took {lat:.1f}s (> {ctx.t['handoff_dead_air_s']}s dead air)")
        if reasons:
            out.append(_entry("dead_air_handoff", "fail", i, turn, "; ".join(reasons)))
    return out


_LEAK_BASE = [
    ("analyze.py LEAK", re.compile(r"default_api\.|tool_code|print\(|\w+\(\w+=['\"]")),
    ("call with literal arg", re.compile(r"\b\w+\(\s*\w+\s*=\s*(?:-?\d|True\b|False\b|None\b|\{|\[)")),
    ("transfer_to_agent(", re.compile(r"\btransfer_to_agent\s*\(")),
    ("end_session(", re.compile(r"\bend_session\s*\(")),
    ("code fence", re.compile(r"```")),
]


def check_code_leak(conv: dict, ctx: Ctx) -> list[dict]:
    names = set(ctx.tool_names)
    for _, turn in model.agent_turns(conv):
        names.update(c.get("name") for c in turn.get("tool_calls") or [] if c.get("name"))
    names = {n for n in names if re.fullmatch(r"[A-Za-z_]\w*", n or "")}
    patterns = list(_LEAK_BASE)
    if names:
        alt = "|".join(sorted(map(re.escape, names)))
        patterns.append(("tool name call", re.compile(rf"\b(?:{alt})\s*\(")))
    out = []
    for i, turn in model.agent_turns(conv):
        for seg in model.texts_of(turn):
            hit = None
            for label, rx in patterns:
                m = rx.search(seg)
                if m:
                    hit = (label, m)
                    break
            if hit:
                label, m = hit
                out.append(
                    _entry("code_leak", "fail", i, turn, f"[{label}] '{tx.around(seg, m.start(), m.end(), 100)}'")
                )
                break
    return out


def check_race_facts_without_tool(conv: dict, ctx: Ctx) -> list[dict]:
    out = []
    for i, turn in model.agent_turns(conv):
        segs = _race_fact_segments(turn.get("text") or "", ctx)
        if not segs:
            continue
        calls = _calls_until(conv, i)
        if any(ctx.is_race_tool(c.get("name", "")) for c in calls):
            continue
        strings = [s for c in calls for s in _response_strings(c)]
        for seg, times, dates in segs:
            if _grounded(times, dates, strings):
                continue
            called = sorted({c.get("name", "") for c in calls}) or ["none"]
            out.append(
                _entry(
                    "race_facts_without_tool",
                    "fail",
                    i,
                    turn,
                    f"race timing stated with no schedule tool call so far (tools called: {', '.join(called)}): "
                    f"'{tx.excerpt(seg, 200)}'",
                )
            )
            break
    return out


def check_race_fact_value_mismatch(conv: dict, ctx: Ctx) -> list[dict]:
    out = []
    for i, turn in model.agent_turns(conv):
        segs = _race_fact_segments(turn.get("text") or "", ctx)
        if not segs:
            continue
        calls = _calls_until(conv, i)
        race_calls = [c for c in calls if ctx.is_race_tool(c.get("name", ""))]
        if not race_calls:
            continue  # reported by race_facts_without_tool
        strings = [s for c in calls for s in _response_strings(c)]
        if not strings:
            continue  # no response content to compare against
        tool_times: set[str] = set()
        for s in strings:
            tool_times |= _tool_time_values(s)
        user_times = tx.time_values(_user_text_until(conv, i))
        bad = []
        for seg, times, _ in segs:
            for matched, _, _, cands in times:
                if not (cands & (tool_times | user_times)):
                    bad.append((matched, seg))
        if bad:
            matched, seg = bad[0]
            out.append(
                _entry(
                    "race_fact_value_mismatch",
                    "fail",
                    i,
                    turn,
                    f"time '{matched}' is in no tool response (tool times: {', '.join(sorted(tool_times)) or 'none'}): "
                    f"'{tx.excerpt(seg, 200)}'",
                )
            )
    return out


ORDER_ID = re.compile(
    r"#\s?(\d{3,})\b|\b(?:order|orders|bestellung|bestellnummer|commande|pedido|ordine|encomenda)\b[^\n\d]{0,25}?#?\s?(\d{3,})\b",
    re.I,
)
ORDER_STATUS = re.compile(
    r"shipped|delivered|in transit|processing|out for delivery|return in progress|tracking|versandt|verschickt|"
    r"geliefert|zugestellt|unterwegs|livr[ée]e?|exp[ée]di[ée]e?|en transit|enviad[oa]|entregad[oa]|en tr[aá]nsito|"
    r"spedit[oa]|consegnat[oa]|in transito|entregue|\b[A-Z]{2,5}-[A-Z0-9-]{4,}",
    re.I,
)
TRACKING = re.compile(r"\b[A-Z]{2,5}(?:-[A-Z0-9]{2,}){1,4}\b")


def _order_fact(text: str) -> re.Match | None:
    for m in ORDER_ID.finditer(text or ""):
        num = m.group(1) or m.group(2) or ""
        # A bare year after 'order' ('order in 2026') is not an order ID.
        if not m.group(0).lstrip().startswith("#") and re.fullmatch(r"(19|20)\d{2}", num):
            continue
        st = ORDER_STATUS.search(text, m.end())
        if st:
            return st
    return None


def check_order_facts_without_tool(conv: dict, ctx: Ctx) -> list[dict]:
    out = []
    for i, turn in model.agent_turns(conv):
        text = turn.get("text") or ""
        st = _order_fact(text)
        if not st:
            continue
        calls = _calls_until(conv, i)
        if any(ctx.is_order_tool(c.get("name", "")) for c in calls):
            continue
        out.append(
            _entry(
                "order_facts_without_tool",
                "fail",
                i,
                turn,
                f"order status/tracking stated with no order lookup so far: '{tx.around(text, st.start(), st.end(), 120)}'",
            )
        )
    return out


def check_order_fact_value_mismatch(conv: dict, ctx: Ctx) -> list[dict]:
    out = []
    for i, turn in model.agent_turns(conv):
        text = turn.get("text") or ""
        if not _order_fact(text):
            continue
        calls = _calls_until(conv, i)
        if not any(ctx.is_order_tool(c.get("name", "")) for c in calls):
            continue
        blob = "\n".join(s for c in calls for s in _response_strings(c))
        if not blob:
            continue
        for m in TRACKING.finditer(text):
            token = m.group(0)
            if not re.search(r"\d", token) or token in blob:
                continue
            out.append(
                _entry(
                    "order_fact_value_mismatch",
                    "fail",
                    i,
                    turn,
                    f"tracking number '{token}' is in no tool response: '{tx.around(text, m.start(), m.end(), 100)}'",
                )
            )
            break
    return out


_STATUS_ERR = re.compile(r"['\"]status['\"]\s*:\s*['\"]error['\"]", re.I)


def _tool_error(call: dict) -> tuple[bool, str, str]:
    resp = call.get("response")
    layers = []
    if isinstance(resp, dict):
        layers.append(resp)
        for key in ("result", "output"):
            if isinstance(resp.get(key), dict):
                layers.append(resp[key])
    for layer in layers:
        status = str(layer.get("status", "")).lower()
        if status == "error" or (layer.get("error") not in (None, "", {}, [])):
            action = str(layer.get("agent_action") or "")
            msg = str(layer.get("error_message") or layer.get("error") or "")
            return True, action, msg
    if not layers:
        raw = call.get("response_text") or (resp if isinstance(resp, str) else "")
        if raw and _STATUS_ERR.search(raw):
            m = re.search(r"agent_action['\"]\s*:\s*['\"](\w+)", raw)
            return True, m.group(1) if m else "", tx.excerpt(raw, 160)
    return False, "", ""


def _user_supplied(args: Any, user_text: str) -> bool:
    user = (user_text or "").lower()
    values = []
    if isinstance(args, dict):
        values = list(args.values())
    elif args not in (None, "", {}):
        values = [args]
    for v in values:
        if isinstance(v, bool) or v in (None, ""):
            continue
        if isinstance(v, float) and v.is_integer():
            v = int(v)
        if isinstance(v, (dict, list)):
            return False
        if str(v).lower() not in user:
            return False
    return True


def check_tool_error(conv: dict, ctx: Ctx) -> list[dict]:
    out = []
    for i, turn in model.agent_turns(conv):
        bad, ok = [], []
        for call in turn.get("tool_calls") or []:
            is_err, action, msg = _tool_error(call)
            if not is_err:
                continue
            desc = f"{call.get('name')}({call.get('args')}) -> error agent_action={action or '?'}: {tx.excerpt(msg, 140)}"
            if action in ctx.expected_error_actions and _user_supplied(call.get("args"), _user_text_until(conv, i)):
                ok.append(desc)
            else:
                bad.append(desc)
        if bad:
            out.append(_entry("tool_error", "fail", i, turn, "unexpected tool error on a valid-intent call: " + " | ".join(bad)))
        elif ok:
            out.append(_entry("tool_error", "pass", i, turn, "expected error for user-supplied input: " + " | ".join(ok)))
    return out


_SNAKE_AGENT = re.compile(r"\b[a-z][a-z0-9]*(?:_[a-z0-9]+)*_agent\b")


def check_internal_agent_names(conv: dict, ctx: Ctx) -> list[dict]:
    names = set(ctx.agent_names)
    for _, turn in model.agent_turns(conv):
        names.update(t for t in turn.get("transfers") or [] if t)
    humanized = []
    for n in sorted(names):
        parts = [p for p in re.split(r"[_\s-]+", n) if p]
        if len(parts) >= 2:
            humanized.append(re.compile(r"\b" + r"[\s_-]*".join(map(re.escape, parts)) + r"\w*", re.I))
    out = []
    for i, turn in model.agent_turns(conv):
        text = turn.get("text") or ""
        m = _SNAKE_AGENT.search(text)
        if not m:
            for rx in humanized:
                m = rx.search(text)
                if m:
                    break
        if m:
            out.append(
                _entry(
                    "internal_agent_names",
                    "fail",
                    i,
                    turn,
                    f"internal agent name '{m.group(0)}' said to the user: '{tx.around(text, m.start(), m.end(), 100)}'",
                )
            )
    return out


def check_tts_unfriendly(conv: dict, ctx: Ctx) -> list[dict]:
    out = []
    status = "fail" if ctx.voice else "warn"
    for i, turn in model.agent_turns(conv):
        text = turn.get("text") or ""
        issues = []
        em = tx.EMOJI.findall(text)
        em = [e for e in em if e not in ("\ufe0f", "\u200d")]
        if em:
            issues.append(f"emoji {''.join(dict.fromkeys(em))}")
        for kind, rx in tx.MARKDOWN.items():
            m = rx.search(text)
            if m:
                issues.append(f"markdown {kind} '{tx.excerpt(m.group(0), 40)}'")
        if ctx.voice:
            for kind, rx in tx.SPOKEN_SYMBOLS.items():
                m = rx.search(text)
                if m:
                    issues.append(f"symbol {kind} '{tx.excerpt(m.group(0), 40)}'")
        if issues:
            channel = "voice" if ctx.voice else "text (warning only)"
            out.append(_entry("tts_unfriendly", status, i, turn, f"{channel}: " + "; ".join(issues)))
    return out


_MD_STRIP = re.compile(r"[*_`#>|]+|\[([^\]]*)\]\([^)]*\)")


def check_reply_length(conv: dict, ctx: Ctx) -> list[dict]:
    out = []
    status = "fail" if ctx.voice else "warn"
    for i, turn in model.agent_turns(conv):
        text = _MD_STRIP.sub(lambda m: m.group(1) or " ", turn.get("text") or "")
        clean = " ".join(text.split())
        if not clean:
            continue
        sentences = len(tx.segments(text))
        n_words = len(clean.split())
        spoken = n_words / float(ctx.t["words_per_minute"]) * 60.0
        over = []
        if sentences > ctx.t["voice_max_sentences"]:
            over.append(f"{sentences} sentences > {ctx.t['voice_max_sentences']}")
        if len(clean) > ctx.t["voice_max_chars"]:
            over.append(f"{len(clean)} chars > {ctx.t['voice_max_chars']}")
        if spoken > ctx.t["voice_max_spoken_s"]:
            over.append(f"~{spoken:.0f}s spoken > {ctx.t['voice_max_spoken_s']}s")
        if over:
            out.append(
                _entry(
                    "reply_length",
                    status,
                    i,
                    turn,
                    f"{'voice' if ctx.voice else 'text (warning only)'} budget exceeded: {', '.join(over)}: "
                    f"'{tx.excerpt(clean, 120)}'",
                )
            )
    return out


def check_latency_budget(conv: dict, ctx: Ctx) -> list[dict]:
    timed = [
        (i, t, float(t["latency_s"]))
        for i, t in model.agent_turns(conv)
        if t.get("latency_s") is not None and not t.get("greeting")
    ]
    if not timed:
        return [_entry("latency_budget", "skip", None, None, "no per-turn timing in this source")]
    out = []
    for i, t, lat in timed:
        if lat > ctx.t["max_turn_latency_s"]:
            out.append(
                _entry("latency_budget", "fail", i, t, f"turn latency {lat:.1f}s > {ctx.t['max_turn_latency_s']}s")
            )
    lats = sorted(x[2] for x in timed)
    if len(lats) >= 5:
        p90 = lats[min(len(lats) - 1, int(0.9 * len(lats)))]
        if p90 > ctx.t["p90_turn_latency_s"]:
            out.append(
                _entry(
                    "latency_budget",
                    "fail",
                    None,
                    None,
                    f"p90 turn latency {p90:.1f}s > {ctx.t['p90_turn_latency_s']}s (median "
                    f"{statistics.median(lats):.1f}s, n={len(lats)})",
                )
            )
    if not out:
        out.append(
            _entry("latency_budget", "pass", None, None, f"max {max(lats):.1f}s over {len(lats)} timed turns")
        )
    return out


_CARD = re.compile(r"(?<![\d-])\d(?:[ -]?\d){12,18}(?![\d-])")
_CHARGE = re.compile(
    r"\b(?:I|we)(?:'ve| have)?\s+(?:just\s+)?(?:charged|processed|billed)\b|"
    r"\byour (?:card|payment|order) (?:has been|was|is) (?:charged|processed|accepted|billed)\b|"
    r"\bpayment (?:has been |was )?(?:processed|received|accepted|successful)\b|"
    r"\b(?:charged|billed) (?:to )?your (?:card|account)\b",
    re.I,
)


def _luhn(digits: str) -> bool:
    total = 0
    for idx, ch in enumerate(reversed(digits)):
        d = int(ch)
        if idx % 2 == 1:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return total % 10 == 0


def check_pci_echo(conv: dict, ctx: Ctx) -> list[dict]:
    out = []
    for i, turn in model.agent_turns(conv):
        text = turn.get("text") or ""
        user_digits = re.sub(r"\D", "", _user_text_until(conv, i))
        hit = None
        for m in _CARD.finditer(text):
            digits = re.sub(r"\D", "", m.group(0))
            if 13 <= len(digits) <= 19 and (_luhn(digits) or (len(digits) >= 13 and digits in user_digits)):
                hit = f"card-like number echoed: '{tx.around(text, m.start(), m.end(), 60)}'"
                break
        if not hit:
            m = _CHARGE.search(text)
            if m:
                hit = f"payment/charge claim: '{tx.around(text, m.start(), m.end(), 80)}'"
        if hit:
            out.append(_entry("pci_echo", "fail", i, turn, hit))
    return out


def check_language_match(conv: dict, ctx: Ctx) -> list[dict]:
    expected = ctx.expected_language
    if not expected:
        return [_entry("language_match", "skip", None, None, "no expected language")]
    auto = str(expected).lower() == "auto"
    current = None if auto else str(expected).lower()[:2]
    min_words = int(ctx.t["language_min_words"])
    out = []
    for i, turn in enumerate(conv.get("turns") or []):
        if turn.get("role") == "user":
            if auto and not turn.get("event"):
                lang, _ = tx.detect_language(turn.get("text") or "")
                if lang:
                    current = lang
            continue
        if turn.get("role") != "agent" or turn.get("greeting") or not current:
            continue
        for block in model.texts_of(turn):
            bad = None
            for para in re.split(r"\n\s*\n", block):
                if len(tx.words(para)) < min_words:
                    continue
                lang, _ = tx.detect_language(para)
                if lang and lang != current:
                    bad = (lang, para)
                    break
            if bad:
                out.append(
                    _entry(
                        "language_match",
                        "fail",
                        i,
                        turn,
                        f"expected '{current}', reply is '{bad[0]}': '{tx.excerpt(bad[1], 160)}'",
                    )
                )
                break
    return out


UPCOMING = re.compile(
    r"\bupcoming\b|\bnext up\b|\bnext race\b|\bnext grand prix\b|\bthe next\b[^.!?\n]{0,25}\b(?:race|grand prix|gp)\b|"
    r"\bwill (?:take place|be held|start|begin|run|kick off|be racing)\b|\btakes place\b|\bis taking place\b|"
    r"\bis happening\b|\bhappening (?:from|on)\b|\bcoming up\b|\bkicks off\b|\bis scheduled\b|\bscheduled (?:for|to)\b|"
    r"\bget ready\b|\bthis weekend\b|\bn[äa]chste[nsr]?\s+(?:rennen|grand prix|gp|gro(?:ß|ss)e[nr]? preis)|"
    r"\bfindet\b[^.!?\n]{0,60}\bstatt\b|\bwird\b[^.!?\n]{0,60}\b(?:stattfinden|ausgetragen)\b|\bbevorstehend\w*|"
    r"\bse d[ée]roulera\b|\baura lieu\b|\bprochaine?s? (?:course|grand prix|gp)\b|\b[àa] venir\b|\bse tiendra\b|"
    r"\bse celebrar[áa]\b|\btendr[áa] lugar\b|\bpr[óo]xim[oa] (?:carrera|gran premio|gp)\b|\bse disputar[áa]\b|"
    r"\bsi terr[àa]\b|\bsi svolger[àa]\b|\bprossim[oa] (?:gara|gran premio|gp)\b|"
    r"\bacontecer[áa]\b|\bser[áa] realizad[oa]\b|\bpr[óo]xim[oa] (?:corrida|grande pr[êe]mio)\b",
    re.I,
)
PAST = re.compile(
    r"\btook place\b|\bwas held\b|\bwere held\b|\balready (?:happened|took place|over|finished|been)\b|"
    r"\bhas (?:already )?(?:happened|finished|ended|concluded)\b|\bis (?:already )?over\b|\bconcluded\b|"
    r"\bearlier this (?:season|year)\b|\bfand\b[^.!?\n]{0,60}\bstatt\b|\bwurde\b[^.!?\n]{0,60}\b(?:ausgetragen|gefahren)\b|"
    r"\bbereits vorbei\b|\bschon vorbei\b|\ba (?:d[ée]j[àa]\s+)?eu lieu\b|\bs'est (?:d[ée]j[àa]\s+)?(?:d[ée]roul[ée]|tenu)|"
    r"\b(?:ya\s+)?tuvo lugar\b|\b(?:ya\s+)?se celebr[óo]\b|"
    r"\bsi [èe] (?:gi[àa]\s+)?(?:svolto|tenuto|corso)\b|\b(?:j[áa]\s+)?aconteceu\b",
    re.I,
)
_RACE_KEYS = ("race_name", "meeting_name", "circuit", "circuit_name", "location", "country_name", "meeting_official_name")


def _race_refs(resp: Any) -> list[str]:
    refs: list[str] = []

    def walk(o: Any) -> None:
        if isinstance(o, dict):
            for k, v in o.items():
                if k in _RACE_KEYS and isinstance(v, str):
                    refs.extend(w for w in re.split(r"[\s,()/-]+", v) if len(w) >= 5 and w.lower() not in {"grand", "circuit", "international", "united", "street"})
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)

    walk(resp)
    return sorted(set(refs))


def check_past_race_as_upcoming(conv: dict, ctx: Ctx) -> list[dict]:
    if not ctx.now:
        return [_entry("past_race_as_upcoming", "skip", None, None, "no 'now' given")]
    today = ctx.now.date()
    out = []
    for i, turn in model.agent_turns(conv):
        text = turn.get("text") or ""
        if not text.strip() or PAST.search(text):
            continue
        up = UPCOMING.search(text)
        if not up:
            continue
        reason = None
        for call in turn.get("tool_calls") or []:
            if not ctx.is_race_tool(call.get("name", "")):
                continue
            strings = _response_strings(call)
            season = None
            resp = call.get("response")
            if isinstance(resp, dict):
                inner = resp.get("result") if isinstance(resp.get("result"), dict) else resp
                try:
                    season = int(float(inner.get("season"))) if inner.get("season") is not None else None
                except (TypeError, ValueError):
                    season = None
            dates = [d[3] for s in strings for d in tx.find_dates(s, default_year=season) if d[3]]
            if not dates or max(dates) >= today:
                continue
            refs = _race_refs(resp)
            ref_hit = next((r for r in refs if re.search(rf"\b{re.escape(r)}\b", text, re.I)), None)
            if not ref_hit:
                continue
            reason = (
                f"tool dates end {max(dates).isoformat()} (before now {today.isoformat()}) but the reply presents "
                f"'{ref_hit}' as upcoming: '{tx.around(text, up.start(), up.end(), 110)}'"
            )
            break
        if not reason:
            for seg in tx.segments(text):
                if not RACE_CONTEXT.search(seg):
                    continue
                past_dates = [
                    d for d in tx.find_dates(seg, default_year=ctx.now.year) if d[3] and d[3] < today and d[3].year >= today.year
                ]
                if past_dates and UPCOMING.search(seg):
                    reason = (
                        f"date {past_dates[0][3].isoformat()} (before now {today.isoformat()}) presented as upcoming: "
                        f"'{tx.excerpt(seg, 200)}'"
                    )
                    break
        if reason:
            out.append(_entry("past_race_as_upcoming", "fail", i, turn, reason))
    return out


MOCK_WORDS = re.compile(
    r"\bmock(?:ed)?\b|simulat\w*|\bdemo\b|demonstration|fictional|sample (?:order|data)|not (?:a )?real\b|test data|"
    r"simuliert\w*|fiktiv\w*|simul[ée]\w*|fictif|d[ée]monstration|d[ée]mo\b|simulad[oa]|ficticio|demostraci[óo]n|"
    r"fittizi[oa]|dimostrativ[oa]",
    re.I,
)
FRESHNESS_WORDS = re.compile(
    r"latest[- ]available|most recent (?:available )?data|snapshot|\bas of\b|subject to change|may (?:still )?change|"
    r"could change|can change|not (?:be )?(?:live|real[- ]time)|isn't live|cached|simulat\w*|demo data|sandbox|"
    r"may not reflect|might not reflect|double[- ]check|verify (?:on|with|at)|check the official|last updated|"
    r"\b2026\s+(?:season|calendar|schedule|standings|championship|constructors|drivers)\b|"
    r"\b(?:calendar|schedule|standings|championship|calendrier|classement|calendario|clasificaci[óo]n|classifica|rennkalender|wm-stand|fahrerwertung|konstrukteurswertung)\s+(?:de\s+|del\s+|für\s+|for\s+)?2026\b|"
    r"aktuellste?n? verf[üu]gbare|\bStand\b|Momentaufnahme|ohne Gew[äa]hr|kann sich (?:noch )?[äa]ndern|"
    r"derni[èe]res (?:donn[ée]es|informations) disponibles|susceptibles? de changer|peut changer|instantan[ée]|"
    r"[úu]ltimos datos disponibles|puede cambiar|sujet[oa]s? a cambios|"
    r"ultimi dati disponibili|potrebbe cambiare|soggett[oi] a (?:modifiche|variazioni)",
    re.I,
)
STANDINGS_FACT = re.compile(
    r"\b\d{1,3}(?:\.\d)?\s*(?:points|pts|punkte|puntos|punti|pontos)\b|\bP\d{1,2}\b[^.\n]{0,60}(?:champion|standings|"
    r"wertung|classement|clasificaci|classifica)",
    re.I,
)
_NON_LIVE = re.compile(r"\b(?:fallback|snapshot|cached|simulat\w*|sandbox|fixture|offline)\b", re.I)
_VERIFIED_2026_SOURCES = (
    "openf1 api (2026 season snapshot)",
    "openf1 api (2026 standings snapshot)",
)


def _call_is_non_live(call: dict) -> bool:
    resp = call.get("response")
    if isinstance(resp, dict):
        payload = resp.get("result") if isinstance(resp.get("result"), dict) else resp
        if isinstance(payload, dict):
            src = str(payload.get("source") or "").strip().lower()
            dsrc = str(payload.get("data_source") or "").strip().lower()
            if src == "live" or dsrc in _VERIFIED_2026_SOURCES:
                return False
            if payload.get("_fake") is True:
                return True
            prov = f"{src} {dsrc}".strip()
            if prov:
                return bool(_NON_LIVE.search(prov))
    raw = call.get("response_text") or ""
    raw_lower = raw.lower()
    if any(s in raw_lower for s in _VERIFIED_2026_SOURCES):
        return False
    m = re.search(r"['\"](?:data_)?source['\"]\s*:\s*['\"]([^'\"]+)['\"]", raw, re.I)
    if m:
        return bool(_NON_LIVE.search(m.group(1)))
    return bool(_NON_LIVE.search(raw))


def check_disclosure_mock(conv: dict, ctx: Ctx) -> list[dict]:
    turns = list(model.agent_turns(conv))
    for pos, (i, turn) in enumerate(turns):
        if not _order_fact(turn.get("text") or ""):
            continue
        if any(MOCK_WORDS.search(t.get("text") or "") for _, t in turns[pos:]):
            return [_entry("disclosure_mock", "pass", i, turn, "order facts stated with a mock/demo disclosure")]
        return [
            _entry(
                "disclosure_mock",
                "fail",
                i,
                turn,
                f"order facts stated but the data is never disclosed as mock/demo: '{tx.excerpt(turn.get('text'), 160)}'",
            )
        ]
    return []


def check_disclosure_freshness(conv: dict, ctx: Ctx) -> list[dict]:
    turns = list(model.agent_turns(conv))
    for pos, (i, turn) in enumerate(turns):
        text = turn.get("text") or ""
        race_segs = _race_fact_segments(text, ctx)
        standings = STANDINGS_FACT.search(text)
        if not race_segs and not standings:
            continue
        calls = [c for c in _calls_until(conv, i) if c.get("name") not in ("end_session",)]
        data_calls = [
            c for c in calls if ctx.is_race_tool(c.get("name", "")) or re.search(r"standing", c.get("name", ""), re.I)
        ]
        if data_calls and not any(_call_is_non_live(c) for c in data_calls):
            continue  # tool provenance is live: no snapshot disclosure needed
        if any(FRESHNESS_WORDS.search(t.get("text") or "") for _, t in turns[pos:]):
            return [_entry("disclosure_freshness", "pass", i, turn, "race/standings data stated with a freshness disclosure")]
        what = tx.excerpt(race_segs[0][0] if race_segs else text[max(0, standings.start() - 60) : standings.end() + 60], 160)
        return [
            _entry(
                "disclosure_freshness",
                "fail",
                i,
                turn,
                f"race/standings data from a snapshot (or no tool) is never disclosed as latest-available: '{what}'",
            )
        ]
    return []


HUMAN_REQUEST = re.compile(
    r"\b(?:human|real person|live (?:agent|person)|supervisor|manager|representative|operator|someone real|"
    r"customer service|escalat\w*|speak (?:to|with) (?:a |an |some)?(?:one|body|person)|talk (?:to|with) (?:a |an |some)?"
    r"(?:one|body|person)|menschen?|vorgesetzte\w*|mitarbeiter\w*|humain|superviseur|responsable|conseiller|"
    r"vraie personne|humano|persona real|gerente|umano|supervisore|persona reale)\b",
    re.I,
)
EXPLAIN = re.compile(
    r"not available|isn't available|aren't available|unavailable|can(?:no|')t (?:transfer|connect|put you through)|"
    r"unable to (?:transfer|connect)|not able to (?:transfer|connect)|no (?:live|human)|don't have (?:a |any )?(?:human|live)|"
    r"(?:I'm|I am) (?:an AI|a virtual|a digital)|nicht verf[üu]gbar|keine (?:menschliche|Weiterleitung)|pas disponible|"
    r"ne (?:peux|pouvons) pas (?:vous )?(?:transf[ée]rer|mettre en relation)|no est[áa] disponible|no (?:puedo|podemos) "
    r"(?:transferir|conectar)|non [èe] disponibile|non posso (?:trasferire|collegare)",
    re.I,
)
NEXT_STEP = re.compile(
    r"https?://|www\.|\b[\w-]+\.(?:com|org)\b|official (?:\w+ ){0,3}(?:website|site|channels?|store|app|page|support)|"
    r"offizielle\w*|officiel\w*|oficial\w*|ufficial\w*",
    re.I,
)
HUMAN_TRANSFER_CLAIM = re.compile(
    r"\b(?:transferr?ing|connecting|putting) you (?:through )?(?:to|with) (?:a |an |our )?(?:human|live agent|"
    r"supervisor|manager|representative|real person|colleague from (?:our )?support)\b|"
    r"\b(?:I'll|I will|let me) (?:transfer|connect) you (?:to|with) (?:a |an |our )?(?:human|live agent|supervisor|"
    r"manager|representative|real person)\b",
    re.I,
)


def check_session_end_without_answer(conv: dict, ctx: Ctx) -> list[dict]:
    out = []
    for i, turn in model.agent_turns(conv):
        text = turn.get("text") or ""
        user = model.previous_user_text(conv, i)
        reasons = []
        if turn.get("escalated"):
            reasons.append("end_session(session_escalated=True): live escalation is not offered in this release")
        m = HUMAN_TRANSFER_CLAIM.search(text)
        if m:
            reasons.append(f"claims a human transfer: '{tx.around(text, m.start(), m.end(), 80)}'")
        if HUMAN_REQUEST.search(user) and not turn.get("greeting"):
            missing = [n for n, rx in (("explanation", EXPLAIN), ("official next step", NEXT_STEP)) if not rx.search(text)]
            if missing:
                ended = " and ended the session" if turn.get("session_ended") else ""
                reasons.append(
                    f"user asked for a human ('{tx.excerpt(user, 80)}'); reply lacks {' + '.join(missing)}{ended}: "
                    f"'{tx.excerpt(text, 120) or '<no reply>'}'"
                )
        elif turn.get("session_ended") and not text.strip() and ("?" in user or re.match(r"\s*(can|could|would|please|i want|i need)\b", user, re.I)):
            reasons.append(f"session ended with no reply to: '{tx.excerpt(user, 100)}'")
        if reasons:
            out.append(_entry("session_end_without_answer", "fail", i, turn, "; ".join(reasons)))
    return out


_SELF_INTRO_RE = re.compile(
    r"\b(?:i\s+am|i'm|this\s+is|ich\s+bin|je\s+suis|soy|sono)\s+totto\b|"
    r"\btotto,\s+(?:your\s+|the\s+)?(?:ai\s+|fictional\s+|official\s+)?mercedes\b|"
    r"\bmercedes\s+f1\s+fan\s+agent\b",
    re.I,
)
_USER_IDENTITY_QUERY_RE = re.compile(
    r"\b(?:who\s+are\s+you|what\s+are\s+you|toto\s+wolff|are\s+you\s+(?:toto|an?\s+ai|real|a\s+human|a\s+bot)|"
    r"your\s+name|wer\s+bist\s+du|qui\s+es[- ]tu|qui\s+êtes[- ]vous|quién\s+eres|chi\s+sei)\b",
    re.I,
)
_ACCORDING_LATEST_RE = re.compile(
    r"\baccording\s+to\s+the\s+latest(?:[- ]available)?\b|"
    r"\blaut\s+den\s+aktuellsten\s+verfügbaren\b|"
    r"\bselon\s+les\s+dernières\s+données\s+disponibles\b|"
    r"\bsegún\s+los\s+últimos\s+datos\s+disponibles\b|"
    r"\bsecondo\s+gli\s+ultimi\s+dati\s+disponibili\b",
    re.I,
)
_CLOSING_BOILERPLATE_RE = re.compile(
    r"\b(?:what\s+else\s+can\s+i\s+help(?:\s+you\s+with)?(?:\s+today)?|"
    r"how\s+(?:else\s+)?can\s+i\s+help\s+you(?:\s+cheer\s+on\s+the\s+silver\s+arrows)?(?:\s+today)?|"
    r"is\s+there\s+anything\s+else\s+i\s+can\s+help(?:\s+you\s+with)?)\s*\?",
    re.I,
)


def check_repetitive_boilerplate(conv: dict, ctx: Ctx) -> list[dict]:
    """Flags repetitive self-introductions, 'According to the latest-available' mantras, or closing menus across turns."""
    turns = list(model.agent_turns(conv))
    if len(turns) < 2:
        return []

    intro_hits: list[tuple[int, dict, str]] = []
    mantra_hits: list[tuple[int, dict, str]] = []
    closing_hits: list[tuple[int, dict, str]] = []

    for i, turn in turns:
        text = (turn.get("text") or "").strip()
        if not text:
            continue
        user_prev = model.previous_user_text(conv, i) or ""

        m_intro = _SELF_INTRO_RE.search(text)
        if m_intro and not _USER_IDENTITY_QUERY_RE.search(user_prev):
            intro_hits.append((i, turn, m_intro.group(0)))

        m_mantra = _ACCORDING_LATEST_RE.search(text)
        if m_mantra:
            mantra_hits.append((i, turn, m_mantra.group(0)))

        m_close = _CLOSING_BOILERPLATE_RE.search(text)
        if m_close:
            closing_hits.append((i, turn, m_close.group(0)))

    out: list[dict] = []
    if len(intro_hits) >= 2:
        i, turn, snippet = intro_hits[1]
        out.append(
            _entry(
                "repetitive_boilerplate",
                "fail",
                i,
                turn,
                f"self-introduction repeated across {len(intro_hits)} turns without identity question: '{snippet}'",
            )
        )
    if len(mantra_hits) >= 2:
        i, turn, snippet = mantra_hits[1]
        out.append(
            _entry(
                "repetitive_boilerplate",
                "fail",
                i,
                turn,
                f"freshness mantra repeated across {len(mantra_hits)} turns: '{snippet}'",
            )
        )
    if len(closing_hits) >= 2:
        i, turn, snippet = closing_hits[1]
        out.append(
            _entry(
                "repetitive_boilerplate",
                "fail",
                i,
                turn,
                f"closing boilerplate question repeated across {len(closing_hits)} turns: '{snippet}'",
            )
        )
    return out


CHECKS: list[tuple[str, Callable[[dict, Ctx], list[dict]]]] = [
    ("dead_air_handoff", check_dead_air_handoff),
    ("code_leak", check_code_leak),
    ("race_facts_without_tool", check_race_facts_without_tool),
    ("race_fact_value_mismatch", check_race_fact_value_mismatch),
    ("order_facts_without_tool", check_order_facts_without_tool),
    ("order_fact_value_mismatch", check_order_fact_value_mismatch),
    ("tool_error", check_tool_error),
    ("internal_agent_names", check_internal_agent_names),
    ("tts_unfriendly", check_tts_unfriendly),
    ("reply_length", check_reply_length),
    ("latency_budget", check_latency_budget),
    ("pci_echo", check_pci_echo),
    ("language_match", check_language_match),
    ("past_race_as_upcoming", check_past_race_as_upcoming),
    ("disclosure_mock", check_disclosure_mock),
    ("disclosure_freshness", check_disclosure_freshness),
    ("session_end_without_answer", check_session_end_without_answer),
    ("repetitive_boilerplate", check_repetitive_boilerplate),
]
assert [n for n, _ in CHECKS] == list(CATALOGUE), "CHECKS and CATALOGUE must list the same checks"


def grade(conv: dict[str, Any], gctx: dict[str, Any] | None = None) -> dict[str, Any]:
    """Runs every deterministic check. ``passed`` is False iff any check fails.

    gctx keys (all optional): now (ISO/datetime; enables date checks), voice
    (bool; default = conv modality == 'audio'), expected_language (None |
    'auto' | ISO code), thresholds (overrides DEFAULT_THRESHOLDS),
    expected_error_actions, race_tools, order_tools, tool_names, agent_names,
    calendar (reserved), disabled_checks.
    """
    ctx = Ctx(gctx, conv)
    checks: list[dict] = []
    for name, fn in CHECKS:
        if name in ctx.disabled:
            continue
        res = fn(conv, ctx)
        if not res:
            res = [_entry(name, "pass", None, None, "")]
        checks.extend(res)
    by: dict[str, dict[str, int]] = {}
    for c in checks:
        by.setdefault(c["name"], {"fail": 0, "warn": 0, "pass": 0, "skip": 0})[c["status"]] += 1
    return {
        "passed": all(c["status"] != "fail" for c in checks),
        "checks": checks,
        "summary": {
            "fail": sum(v["fail"] for v in by.values()),
            "warn": sum(v["warn"] for v in by.values()),
            "by_check": by,
        },
    }


def failing(result: dict[str, Any], *, include_warn: bool = False) -> list[dict]:
    wanted = {"fail", "warn"} if include_warn else {"fail"}
    return [c for c in result.get("checks") or [] if c.get("status") in wanted]
