#!/usr/bin/env python3
"""Post-hoc checks on saved probe/sim results (no API calls).

Reads any results JSON written by totto_test_harness.py (or a
{"results": [...]} file with the same trace format) and reports, per test:
pass counts with quota errors excluded, handoffs that end without an answer,
tool-call text leaked to the user, and tool errors the agent ran into.

Usage: analyze.py results/<file>.json [more.json ...]
"""

import collections
import json
import re
import statistics
import sys

PREFIXES = (
    "Agent Text:",
    "Tool Call:",
    "Tool Response:",
    "Agent Transfer:",
    "User Query:",
    "User:",
)
LEAK = re.compile(r"default_api\.|tool_code|print\(|\w+\(\w+=['\"]")


def blocks(entry):
    """Splits one trace entry into (kind, text) pairs; continuation lines join."""
    out = []
    for line in entry.split("\n"):
        kind = next((p for p in PREFIXES if line.startswith(p)), None)
        if kind:
            out.append([kind, line[len(kind) :].strip()])
        elif out:
            out[-1][1] += "\n" + line
    return out


def turn_flags(entry):
    parts = blocks(entry)
    texts = [t for k, t in parts if k == "Agent Text:"]
    tools = [t for k, t in parts if k == "Tool Call:"]
    responses = [t for k, t in parts if k == "Tool Response:"]
    transfer = any(k == "Agent Transfer:" for k, _ in parts)
    flags = []
    if transfer and not tools and (not texts or len(texts[-1]) < 120):
        flags.append("dead_air_handoff")
    if any(LEAK.search(t) for t in texts):
        flags.append("code_leak")
    if any("'status': 'error'" in r for r in responses):
        flags.append("tool_error")
    return flags, transfer


RACE_FACT = re.compile(r"\b\d{1,2}:\d{2}\b.*?(UTC|Grand Prix|[Qq]ualifying)|"
                       r"(Grand Prix|[Qq]ualifying).*?\b\d{1,2}:\d{2}\b", re.S)
ORDER_FACT = re.compile(r"#?100[123]\b.*?(Shipped|Delivered|In Transit|"
                        r"Processing|tracking|[A-Z]{2,5}-[A-Z0-9-]{4,})", re.S)


def grounding_flags(trace):
    """Facts stated before the tool that supplies them was ever called."""
    flags = []
    called = set()
    for entry in trace:
        parts = blocks(entry)
        for k, t in parts:
            if k == "Tool Call:":
                called.add(t.split(" ", 1)[0])
        text = "\n".join(t for k, t in parts if k == "Agent Text:")
        if RACE_FACT.search(text) and "get_race_schedule" not in called:
            flags.append("race_facts_without_tool")
        if ORDER_FACT.search(text) and "lookup_mock_merch_order" not in called:
            flags.append("order_facts_without_tool")
    return flags


def is_quota(err):
    return any(s in err for s in ("429", "RESOURCE_EXHAUSTED", "ResourceExhausted"))


def main(paths):
    rows = []
    for path in paths:
        with open(path) as f:
            data = json.load(f)
        rows.extend(data["results"] if isinstance(data, dict) else data)

    by_name = collections.defaultdict(list)
    for r in rows:
        by_name[r["name"]].append(r)

    total_valid = total_pass = total_quota = 0
    flag_counts = collections.Counter()
    for name, rs in sorted(by_name.items()):
        quota = [r for r in rs if is_quota(str(r.get("error", "")))]
        other_err = [r for r in rs if r.get("error") and r not in quota]
        valid = [r for r in rs if r not in quota]
        passed = sum(1 for r in valid if r.get("passed"))
        total_valid += len(valid)
        total_pass += passed
        total_quota += len(quota)
        if not valid:
            verdict = "NO DATA"
        elif passed == len(valid):
            verdict = "OK"
        elif passed:
            verdict = "FLAKY"
        else:
            verdict = "BROKEN"
        flags = collections.Counter()
        for r in valid:
            trace = r.get("detailed_trace") or []
            for entry in trace:
                f, _ = turn_flags(entry)
                flags.update(f)
            flags.update(grounding_flags(trace))
        flag_counts.update(flags)
        flag_text = " ".join(f"{k}={v}" for k, v in sorted(flags.items()))
        print(
            f"{passed}/{len(valid)} {verdict:7s} {name}"
            + (f"  [{flag_text}]" if flag_text else "")
            + (f"  (quota errors excluded: {len(quota)})" if quota else "")
            + (f"  (other errors: {len(other_err)})" if other_err else "")
        )
        for r in valid:
            for d in r.get("expectation_details") or []:
                if d.get("status") != "Met":
                    print(
                        f"    run {r.get('run')} NOT MET: {d['expectation'][:100]}\n"
                        f"      why: {' '.join(str(d.get('justification')).split())[:240]}"
                    )
            if r.get("error") and r not in quota:
                print(f"    run {r.get('run')} ERROR: {str(r['error'])[:200]}")

    print(
        f"\nTOTAL {total_pass}/{total_valid} passed "
        f"({total_quota} runs lost to quota, not counted)"
    )
    if flag_counts:
        print("turn flags:", dict(flag_counts))

    latencies, handoff = [], []
    for r in rows:
        for t in r.get("turns", []) if isinstance(r.get("turns"), list) else []:
            if t.get("user") == "<welcome>":
                continue
            latencies.append(t["latency_s"])
            if t.get("transfer"):
                handoff.append(t["latency_s"])
    if latencies:
        latencies.sort()
        p90 = latencies[min(len(latencies) - 1, int(0.9 * len(latencies)))]
        print(
            f"turn latency: median {statistics.median(latencies):.1f}s, "
            f"p90 {p90:.1f}s, max {max(latencies):.1f}s (n={len(latencies)})"
        )
    if handoff:
        print(
            f"  turns with a handoff: median {statistics.median(handoff):.1f}s "
            f"(n={len(handoff)})"
        )


if __name__ == "__main__":
    main(sys.argv[1:])
