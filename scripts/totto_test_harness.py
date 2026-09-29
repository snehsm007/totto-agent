#!/usr/bin/env python3
"""Independent test harness for the live Totto app.

Talks to the deployed agent and never modifies it. Subcommands:

  tools    Deterministic tool tests (repo evals/tool_tests/tool_tests.yaml).
  goldens  Re-run the platform goldens N times (text or audio).
  sims     Gemini-simulated fans from a sims YAML, N runs (text or audio).
  probes   Scripted multi-turn conversations (exact user lines), N runs,
           judged by an LLM against plain-English expectations.
  rejudge  Re-score saved sim/probe transcripts with a different judge model
           (isolates "is the judge lenient?" from "is the agent good?").

Raw results go to ./results/<kind>_<label>_<timestamp>.json next to this file.
"""

import argparse
import collections
import datetime
import json
import os
import statistics
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import yaml

PROJECT = "your-gcp-project"
APP = (
    f"projects/{PROJECT}/locations/us/apps/"
    "00000000-0000-0000-0000-000000000000"
)
REPO = (
    "<WORKSPACE_ROOT>/"
    "totto-agent"
)
HERE = os.path.dirname(os.path.abspath(__file__))
RESULTS = os.path.join(HERE, "results")
FAST_MODEL = "gemini-3.1-flash-lite"
STRICT_MODEL = "gemini-3.1-pro-preview"


def save(kind, label, payload):
    os.makedirs(RESULTS, exist_ok=True)
    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    path = os.path.join(RESULTS, f"{kind}_{label}_{ts}.json")
    with open(path, "w") as f:
        json.dump(payload, f, indent=2, default=str)
    print(f"\nraw results: {path}")
    return path


def short(text, limit=160):
    text = " ".join(str(text).split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


# --- tools -------------------------------------------------------------------


def cmd_tools(args):
    from cxas_scrapi.evals.tool_evals import ToolEvals

    tool_evals = ToolEvals(app_name=APP)
    cases = tool_evals.load_tool_test_cases_from_file(args.file)
    df = tool_evals.run_tool_tests(cases)
    cols = [
        c
        for c in ("test_name", "tool", "status", "latency (ms)", "errors")
        if c in df.columns
    ]
    print(df[cols].to_string(index=False))
    passed = int((df["status"] == "PASSED").sum())
    print(f"\nTOOLS: {passed}/{len(df)} passed")
    save("tools", "text", df.to_dict(orient="records"))


# --- goldens -----------------------------------------------------------------


def cmd_goldens(args):
    from cxas_scrapi.core.evaluations import Evaluations
    from cxas_scrapi.utils.eval_utils import EvalUtils

    evaluations = Evaluations(app_name=APP)
    goldens = [e for e in evaluations.list_evaluations() if args.tag in e.tags]
    if not goldens:
        sys.exit(f"no evaluations tagged {args.tag!r}")
    before = {
        e.name: {r.name for r in evaluations.list_evaluation_results(e.name)}
        for e in goldens
    }
    want = len(goldens) * args.runs
    print(f"running {len(goldens)} goldens x {args.runs} runs ({args.modality})")
    evaluations.run_evaluation(
        evaluations=[e.name for e in goldens],
        modality=args.modality,
        run_count=args.runs,
    )

    start = time.time()
    fresh = {}
    while True:
        time.sleep(15)
        done = True
        fresh = {}
        for e in goldens:
            new = [
                r
                for r in evaluations.list_evaluation_results(e.name)
                if r.name not in before[e.name]
            ]
            fresh[e.display_name] = new
            if len(new) < args.runs or any(
                int(r.execution_state) not in (2, 3) for r in new
            ):
                done = False
        have = sum(len(v) for v in fresh.values())
        print(f"  {int(time.time() - start)}s: {have}/{want} results in")
        if done:
            break
        if time.time() - start > args.timeout:
            print("TIMEOUT waiting for golden results")
            break

    flat = [r for rs in fresh.values() for r in rs]
    utils = EvalUtils(app_name=APP)
    dfs = utils.evals_to_dataframe(results=flat)
    summary = dfs.get("summary")

    print(f"\nGOLDENS ({args.modality}):")
    total_pass = 0
    for name, rs in sorted(fresh.items()):
        statuses = [int(r.evaluation_status) for r in rs]  # 1 PASS, 2 FAIL
        errors = sum(1 for r in rs if int(r.execution_state) == 3)
        passes = statuses.count(1)
        total_pass += passes
        scores = []
        if summary is not None and not summary.empty:
            rows = summary[summary["display_name"] == name]
            scores = [s for s in rows["semantic_score"].tolist() if s]
        print(
            f"  {passes}/{len(rs)}  {name:45s} errors={errors} "
            f"similarity={scores}"
        )
    print(f"  TOTAL {total_pass}/{len(flat)}")

    failures = dfs.get("failures")
    if failures is not None and not failures.empty:
        print("\nfailure details:")
        for _, row in failures.iterrows():
            print(
                f"  - {row.get('display_name')} [{row.get('failure_type')}] "
                f"expected: {short(row.get('expected'), 120)} | "
                f"actual: {short(row.get('actual'), 220)}"
            )
    save(
        "goldens",
        args.modality,
        [type(r).to_dict(r) for r in flat],
    )


# --- shared conversation summary ---------------------------------------------


def dead_air_turns(trace):
    """Agent turns that end on a handoff without a real answer."""
    count = 0
    for entry in trace:
        if "Agent Transfer" not in entry:
            continue
        lines = entry.split("\n")
        texts = [l for l in lines if l.startswith("Agent Text")]
        tools = [l for l in lines if l.startswith("Tool Call")]
        if not tools and sum(len(t) for t in texts) < 160:
            count += 1
    return count


def summarize(results, wall_s):
    by_name = collections.defaultdict(list)
    for r in results:
        by_name[r["name"]].append(r)
    total = len(results)
    passed = sum(1 for r in results if r.get("passed"))
    print(f"\nOVERALL {passed}/{total} passed, wall clock {wall_s:.0f}s")
    for name, rs in sorted(by_name.items()):
        p = sum(1 for r in rs if r.get("passed"))
        errs = sum(1 for r in rs if "error" in r)
        durs = [r["duration_s"] for r in rs if r.get("duration_s")]
        turns = [r["turns"] for r in rs if isinstance(r.get("turns"), int)]
        dead = sum(dead_air_turns(r.get("detailed_trace") or []) for r in rs)
        verdict = "OK" if p == len(rs) else ("FLAKY" if p else "BROKEN")
        extra = ""
        if durs:
            extra += f" avg {statistics.mean(durs):.1f}s"
        if turns:
            extra += f" / {statistics.mean(turns):.1f} turns"
        print(
            f"  {p}/{len(rs)} {verdict:6s} {name}{extra} "
            f"dead-air-handoffs={dead} errors={errs}"
        )
        seen = set()
        for r in rs:
            if "error" in r:
                key = ("error", short(r["error"], 200))
                if key not in seen:
                    seen.add(key)
                    print(f"      ERROR: {key[1]}")
            for d in r.get("expectation_details") or []:
                if d.get("status") != "Met":
                    key = (d.get("expectation"), r.get("run"))
                    if key in seen:
                        continue
                    seen.add(key)
                    print(
                        f"      run {r.get('run')} NOT MET: "
                        f"{short(d.get('expectation'), 110)}\n"
                        f"         why: {short(d.get('justification'), 260)}"
                    )


# --- sims --------------------------------------------------------------------


def load_sims(path):
    with open(path) as f:
        data = yaml.safe_load(f)
    if isinstance(data, list):
        evals, common = data, []
    else:
        evals = data.get("evals", [])
        common = data.get("common_expectations", [])
    return [
        {
            "name": ev["name"],
            "steps": ev["steps"],
            "expectations": list(ev.get("expectations", [])) + list(common),
            "audio_expectations": ev.get("audio_expectations", []),
            "session_parameters": ev.get("session_parameters", {}),
            "metadata": {"tags": ev.get("tags", [])},
        }
        for ev in evals
    ]


def cmd_sims(args):
    from cxas_scrapi.evals.simulation_evals import SimulationEvals

    cases = []
    for path in args.file:
        cases.extend(load_sims(path))
    if args.only:
        cases = [c for c in cases if c["name"] in args.only]
    if args.modality == "audio" and args.audio_extra_turns:
        for case in cases:
            for step in case["steps"]:
                step["max_turns"] = (
                    int(step.get("max_turns", 6)) + args.audio_extra_turns
                )
    print(
        f"running {len(cases)} sims x {args.runs} runs ({args.modality}, "
        f"user={args.user_model}, judge={args.judge_model}, "
        f"parallel={args.parallel})"
    )
    sim = SimulationEvals(app_name=APP)
    # Default backoff (1s, 2s, give up) is shorter than the per-minute quota
    # window; 6 tries at base 3 waits 1+3+9+27+81 = 121s before giving up.
    sim.max_retries = 6
    sim.retry_delay_base = 3
    start = time.time()
    results = sim.run_simulations(
        test_cases=cases,
        runs=args.runs,
        parallel=args.parallel,
        sim_user_model=args.user_model,
        eval_model=args.judge_model,
        modality=args.modality,
    )
    wall = time.time() - start
    summarize(results, wall)
    save(
        "sims",
        f"{args.label}_{args.modality}",
        {
            "modality": args.modality,
            "user_model": args.user_model,
            "judge_model": args.judge_model,
            "runs": args.runs,
            "wall_clock_s": wall,
            "results": results,
        },
    )


# --- probes ------------------------------------------------------------------

# The CES token quota is per minute, so waits must span a full window.
QUOTA_BACKOFF_S = (10, 20, 40, 60, 60)


def is_quota_error(e):
    text = f"{type(e).__name__} {e}"
    return "429" in text or "RESOURCE_EXHAUSTED" in text or "ResourceExhausted" in text


def run_with_retry(sim, **kwargs):
    """Returns (response, seconds spent waiting on quota)."""
    waited = 0.0
    for delay in QUOTA_BACKOFF_S + (None,):
        try:
            return sim.sessions_client.run(**kwargs), waited
        except Exception as e:  # noqa: BLE001 - only quota errors are retried
            if delay is None or not is_quota_error(e):
                raise
            print(f"  quota hit, retrying in {delay}s", file=sys.stderr)
            time.sleep(delay)
            waited += delay
    raise AssertionError("unreachable")


def run_probe(sim, probe, run_idx, judge_model):
    from cxas_scrapi.core.response_parser import ParsedSessionResponse
    from cxas_scrapi.utils.eval_utils import evaluate_expectations

    session_id = sim.sessions_client.create_session_id()
    turns, trace = [], []
    start = time.time()
    quota_wait = 0.0
    try:
        for line in [None] + list(probe["turns"]):  # None = call start
            t0 = time.time()
            if line is None:
                res, waited = run_with_retry(
                    sim, session_id=session_id, event="welcome"
                )
                trace.append("User: <event>welcome</event>")
            else:
                res, waited = run_with_retry(sim, session_id=session_id, text=line)
                trace.append(f"User: {line}")
            quota_wait += waited
            # Latency excludes time spent sleeping on quota retries.
            latency = time.time() - t0 - waited
            parsed = ParsedSessionResponse(res, tools_map=sim.tools_map)
            transfer = parsed.agent_transfer
            if transfer is not None and not isinstance(transfer, str):
                transfer = getattr(transfer, "display_name", None) or str(
                    transfer
                )
            turns.append(
                {
                    "user": line or "<welcome>",
                    "agent": parsed.agent_texts,
                    "tools": [
                        {"name": tc.name, "args": tc.args}
                        for tc in parsed.tool_calls
                    ],
                    "transfer": transfer,
                    "latency_s": round(latency, 2),
                    "session_ended": parsed.session_ended,
                }
            )
            trace.append(
                "\n".join(parsed.detailed_trace) or "Agent Text: <no response>"
            )
            if parsed.session_ended:
                break
    except Exception as e:  # noqa: BLE001 - record and keep going
        return {
            "name": probe["name"],
            "run": run_idx,
            "passed": False,
            "error": f"{type(e).__name__}: {e}",
            "quota_wait_s": quota_wait,
            "turns": turns,
            "detailed_trace": trace,
        }

    judged = evaluate_expectations(
        sim.genai_client, judge_model, trace, probe["expectations"]
    )
    details = [
        {
            "expectation": j.expectation,
            "status": getattr(j.status, "value", str(j.status)),
            "justification": j.justification,
        }
        for j in judged
    ]
    passed = len(details) == len(probe["expectations"]) and all(
        d["status"] == "Met" for d in details
    )
    return {
        "name": probe["name"],
        "run": run_idx,
        "passed": passed,
        "duration_s": round(time.time() - start - quota_wait, 1),
        "quota_wait_s": quota_wait,
        "turn_count": len(turns),
        "turns": turns,
        "detailed_trace": trace,
        "expectation_details": details,
    }


def cmd_probes(args):
    from cxas_scrapi.evals.simulation_evals import SimulationEvals

    with open(args.file) as f:
        probes = yaml.safe_load(f)["probes"]
    if args.only:
        probes = [p for p in probes if p["name"] in args.only]
    print(
        f"running {len(probes)} probes x {args.runs} runs "
        f"(text, judge={args.judge_model}, parallel={args.parallel})"
    )
    sim = SimulationEvals(app_name=APP)
    jobs = [(p, i + 1) for p in probes for i in range(args.runs)]
    start = time.time()
    results = []
    with ThreadPoolExecutor(max_workers=args.parallel) as pool:
        futures = [
            pool.submit(run_probe, sim, p, i, args.judge_model) for p, i in jobs
        ]
        for fut in as_completed(futures):
            results.append(fut.result())
    wall = time.time() - start
    summarize(results, wall)

    latencies = [
        t["latency_s"]
        for r in results
        for t in r.get("turns", [])
        if t["user"] != "<welcome>"
    ]
    handoff = [
        t["latency_s"]
        for r in results
        for t in r.get("turns", [])
        if t.get("transfer")
    ]
    if latencies:
        latencies.sort()
        p90 = latencies[min(len(latencies) - 1, int(0.9 * len(latencies)))]
        print(
            f"\nturn latency: median {statistics.median(latencies):.1f}s, "
            f"p90 {p90:.1f}s, max {max(latencies):.1f}s "
            f"(n={len(latencies)})"
        )
    if handoff:
        print(
            f"turns with a handoff: median {statistics.median(handoff):.1f}s "
            f"(n={len(handoff)})"
        )
    save(
        "probes",
        "text",
        {"judge_model": args.judge_model, "wall_clock_s": wall, "results": results},
    )


# --- rejudge -----------------------------------------------------------------


def cmd_rejudge(args):
    from cxas_scrapi.evals.simulation_evals import SimulationEvals
    from cxas_scrapi.utils.eval_utils import evaluate_expectations

    with open(args.results) as f:
        data = json.load(f)
    results = data["results"] if isinstance(data, dict) else data
    sim = SimulationEvals(app_name=APP)

    def rejudge_one(r):
        old = r.get("expectation_details") or []
        if not old or not r.get("detailed_trace"):
            return r, []
        expectations = [d["expectation"] for d in old]
        new = evaluate_expectations(
            sim.genai_client, args.judge_model, r["detailed_trace"], expectations
        )
        return r, [
            {
                "expectation": n.expectation,
                "status": getattr(n.status, "value", str(n.status)),
                "justification": n.justification,
            }
            for n in new
        ]

    flips, old_pass, new_pass, rows = [], 0, 0, []
    with ThreadPoolExecutor(max_workers=args.parallel) as pool:
        for r, new in pool.map(rejudge_one, results):
            old = r.get("expectation_details") or []
            if not new:
                continue
            was = all(d["status"] == "Met" for d in old)
            now = len(new) == len(old) and all(d["status"] == "Met" for d in new)
            old_pass += was
            new_pass += now
            rows.append({"name": r["name"], "run": r.get("run"), "new": new})
            for o, n in zip(old, new):
                if o["status"] != n["status"]:
                    flips.append((r["name"], r.get("run"), o, n))
    print(
        f"judge {args.judge_model}: {new_pass}/{len(rows)} conversations pass "
        f"(original judge: {old_pass}/{len(rows)})"
    )
    for name, run, o, n in flips:
        print(
            f"  FLIP {name} run {run}: {o['status']} -> {n['status']}\n"
            f"     {short(o['expectation'], 110)}\n"
            f"     why: {short(n['justification'], 260)}"
        )
    save("rejudge", args.judge_model, rows)


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("tools")
    p.add_argument(
        "--file", default=os.path.join(REPO, "evals/tool_tests/tool_tests.yaml")
    )
    p.set_defaults(func=cmd_tools)

    p = sub.add_parser("goldens")
    p.add_argument("--tag", default="goldens")
    p.add_argument("--modality", choices=["text", "audio"], default="text")
    p.add_argument("--runs", type=int, default=3)
    p.add_argument("--timeout", type=int, default=1500)
    p.set_defaults(func=cmd_goldens)

    p = sub.add_parser("sims")
    p.add_argument(
        "--file",
        action="append",
        default=None,
        help="sims YAML (repeatable); default: repo simulations.yaml",
    )
    p.add_argument("--only", nargs="*")
    p.add_argument("--label", default="repo")
    p.add_argument("--modality", choices=["text", "audio"], default="text")
    p.add_argument("--runs", type=int, default=3)
    p.add_argument("--parallel", type=int, default=7)
    p.add_argument("--user-model", default=FAST_MODEL)
    p.add_argument("--judge-model", default=FAST_MODEL)
    p.add_argument("--audio-extra-turns", type=int, default=4)
    p.set_defaults(func=cmd_sims)

    p = sub.add_parser("probes")
    p.add_argument("--file", default=os.path.join(HERE, "probes.yaml"))
    p.add_argument("--only", nargs="*")
    p.add_argument("--runs", type=int, default=3)
    p.add_argument("--parallel", type=int, default=10)
    p.add_argument("--judge-model", default=STRICT_MODEL)
    p.set_defaults(func=cmd_probes)

    p = sub.add_parser("rejudge")
    p.add_argument("--results", required=True)
    p.add_argument("--judge-model", default=STRICT_MODEL)
    p.add_argument("--parallel", type=int, default=6)
    p.set_defaults(func=cmd_rejudge)

    args = parser.parse_args()
    if args.cmd == "sims" and not args.file:
        args.file = [os.path.join(REPO, "evals/simulations/simulations.yaml")]
    args.func(args)


if __name__ == "__main__":
    main()
