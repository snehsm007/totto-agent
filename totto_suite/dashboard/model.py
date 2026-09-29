"""Dashboard data model: normalizes CI inputs into ``data/*.json``.

Inputs (all optional, all tolerated with missing fields):
  gate_summary.json  written by ``totto_suite ci-gate`` (schema
                     totto-gate-summary/v1: commit, run_id, run_url, target,
                     tool_mode, pass_rate, baseline_pass_rate, verdict,
                     reasons, layers, tests[] with app-relative platform_ids)
  deploy.json        written by the deploy-live job (CXAS version per commit)
  prior data/ dir    history.json, voice_comparison.json, local_history.json

Outputs (in ``<site>/data/``):
  latest.json        the record for this build (incl. the scrubbed gate
                     summary under ``gate_summary``)
  history.json       {"schema", "runs": [entry, ...]} oldest first, one entry
                     per run key (a re-run of the same key replaces it)
  baseline.json      copy of the last PASSing main gate summary (only written
                     by ``merge --update-baseline``)

No result is ever invented: without a gate summary the verdict is the
caller-supplied label (default ``NO GATED RUN YET``) and pass rates are null.
"""

from __future__ import annotations

import datetime
import json
import re
from pathlib import Path
from typing import Any

from totto_suite.dashboard import scrub

SCHEMA = "totto-dashboard/v1"
NO_GATE_LABEL = "NO GATED RUN YET"
UNREADABLE_LABEL = "GATE SUMMARY UNREADABLE"
GATE_VERDICTS = ("PASS", "FAIL", "INCONCLUSIVE")
MAX_HISTORY = 500

_RESOURCE_RE = re.compile(
    r"(?:evaluationRuns|evaluations|evaluationResults|results|sessions|conversations|versions"
    r"|deployments|evaluationDatasets|scheduledEvaluationRuns|evaluationExpectations|tools"
    r"|toolsets|agents|changelogs)/[A-Za-z0-9._:@-]+"
    r"(?:/[A-Za-z]+/[A-Za-z0-9._:@-]+)*"
)


class InputError(Exception):
    """A present input file could not be parsed."""


def now_utc() -> str:
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def read_json(path: Path | str | None) -> Any:
    """None if the path is None or missing; InputError if unparsable."""
    if path is None:
        return None
    p = Path(path)
    if not p.is_file():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as e:
        raise InputError(f"{p.name}: {e.__class__.__name__}: {e}") from e


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def get_path(d: Any, *paths: str) -> Any:
    """First non-empty value among dotted ``paths`` in nested dicts."""
    for path in paths:
        cur = d
        for part in path.split("."):
            if not isinstance(cur, dict) or part not in cur:
                cur = None
                break
            cur = cur[part]
        if cur not in (None, "", [], {}):
            return cur
    return None


def as_rate(value: Any) -> float | None:
    """Pass rate as a fraction 0..1 (accepts 0..1 fractions or 0..100 %)."""
    if isinstance(value, bool) or value is None:
        return None
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    if f != f or f < 0:  # NaN / negative
        return None
    return f / 100.0 if f > 1.0 else f


def safe_key(s: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", s).strip("._") or "run"


def platform_ids(value: Any) -> list[str]:
    """App-relative resource IDs found anywhere in ``value`` (list/dict/str)."""
    found: list[str] = []

    def walk(v: Any) -> None:
        if isinstance(v, str):
            for m in _RESOURCE_RE.finditer(v):
                if m.group(0) not in found:
                    found.append(m.group(0))
        elif isinstance(v, dict):
            for x in v.values():
                walk(x)
        elif isinstance(v, (list, tuple)):
            for x in v:
                walk(x)

    walk(value)
    return found


def _status(t: dict) -> str:
    s = get_path(t, "status", "verdict", "result")
    return str(s).upper() if s is not None else "UNKNOWN"


def normalize_tests(tests: Any) -> list[dict]:
    out = []
    if not isinstance(tests, list):
        return out
    for i, t in enumerate(tests):
        if not isinstance(t, dict):
            continue
        repeats = t.get("repeats")
        rep_status = []
        if isinstance(repeats, list):
            for r in repeats:
                rep_status.append(_status(r) if isinstance(r, dict) else str(r).upper())
        out.append(
            {
                "id": str(get_path(t, "id", "name", "test_id") or f"test-{i + 1}"),
                "layer": get_path(t, "layer", "kind"),
                "status": _status(t),
                "repeats": rep_status,
                "tool_mode": get_path(t, "tool_mode"),
                "fake_verified": t.get("fake_verified"),
                "platform_ids": platform_ids(
                    t.get("platform_ids") if t.get("platform_ids") is not None else t
                ),
                "message": (str(t["message"]).splitlines() or [""])[0][:240]
                if t.get("message")
                else None,
            }
        )
    return out


def normalize_deploy(deploy: Any) -> dict | None:
    if not isinstance(deploy, dict):
        return None
    version = get_path(
        deploy,
        "version",
        "version_name",
        "version_id",
        "cxas_version",
        "app_version",
        "cxas.version_id",
        "cxas.version",
    )
    display = get_path(deploy, "version_display_name", "display_name", "version.display_name")
    if isinstance(version, dict):
        display = display or get_path(version, "display_name", "displayName")
        version = get_path(version, "name", "id", "version_id")
    if isinstance(version, str) and "/" not in version and version:
        version = f"versions/{version}"
    phones = get_path(deploy, "phone_deployments", "telephony", "deployments", "gtp_deployments")
    return {
        "version": version,
        "version_display_name": display,
        "commit": get_path(deploy, "commit", "git_commit", "agent.commit"),
        "status": get_path(deploy, "status", "result"),
        "deployed_at": get_path(deploy, "deployed_at", "finished_at", "created_at", "timestamp"),
        "run_url": get_path(deploy, "run_url"),
        "phone_deployments": platform_ids(phones) if phones else [],
    }


def build_latest(
    gate: Any,
    deploy: Any,
    *,
    commit: str | None = None,
    run_url: str | None = None,
    missing_gate_label: str = NO_GATE_LABEL,
    repo_url: str | None = None,
    generated_at: str | None = None,
    gate_error: str | None = None,
) -> dict:
    """The latest.json record. ``gate``/``deploy`` are raw parsed inputs."""
    gate = scrub.relativize(gate) if isinstance(gate, dict) else None
    deploy_n = normalize_deploy(scrub.relativize(deploy))
    generated_at = generated_at or now_utc()

    if gate is not None:
        raw_verdict = str(get_path(gate, "verdict") or "").upper()
        verdict = raw_verdict if raw_verdict in GATE_VERDICTS else (raw_verdict or "UNKNOWN")
    elif gate_error:
        verdict = UNREADABLE_LABEL
    else:
        verdict = missing_gate_label
    gate = gate or {}

    tests = normalize_tests(gate.get("tests"))
    passed = sum(1 for t in tests if t["status"] == "PASS")
    commit = commit or get_path(gate, "commit") or (deploy_n or {}).get("commit")
    run_url = run_url or get_path(gate, "run_url") or (deploy_n or {}).get("run_url")
    run_id = get_path(gate, "run_id")
    if gate:
        key = safe_key(str(run_id or f"gate-{(commit or 'unknown')[:12]}-{generated_at}"))
    else:
        suffix = (run_url or "").rstrip("/").rsplit("/", 1)[-1] if run_url else ""
        key = safe_key(f"nogate-{(commit or 'unknown')[:12]}" + (f"-{suffix}" if suffix else ""))

    layers = {}
    for name, s in (gate.get("layers") or {}).items():
        if isinstance(s, dict):
            layers[str(name)] = {
                "pass": s.get("pass"),
                "fail": s.get("fail"),
                "infra_error": s.get("infra_error"),
                "skipped": s.get("skipped"),
                "pass_rate": as_rate(get_path(s, "pass_rate", "score")),
            }

    reasons = gate.get("reasons")
    return {
        "schema": SCHEMA,
        "key": key,
        "source": "ci-gate" if gate else "no-gate",
        "gate_present": bool(gate),
        "gate_error": gate_error,
        "commit": commit,
        "repo_url": repo_url,
        "verdict": verdict,
        "pass_rate": as_rate(get_path(gate, "pass_rate")),
        "baseline_pass_rate": as_rate(get_path(gate, "baseline_pass_rate")),
        "tool_mode": get_path(gate, "tool_mode"),
        "fake_verified": gate.get("fake_verified"),
        "target": get_path(gate, "target", "app_ref"),
        "run_id": run_id,
        "run_url": run_url,
        "started_at": get_path(gate, "started_at"),
        "finished_at": get_path(gate, "finished_at", "completed_at", "timestamp"),
        "generated_at": generated_at,
        "duration_s": get_path(gate, "duration_s"),
        "app_version": get_path(gate, "app_version"),
        "reasons": [str(r) for r in reasons] if isinstance(reasons, list) else [],
        "thresholds": gate.get("thresholds") if isinstance(gate.get("thresholds"), dict) else {},
        "layers": layers,
        "deploy": deploy_n,
        "tests": tests,
        "tests_total": len(tests),
        "tests_passed": passed,
        "detail_page": f"runs/{key}.html" if gate else None,
        "gate_summary": gate or None,
    }


HISTORY_FIELDS = (
    "key",
    "source",
    "commit",
    "verdict",
    "pass_rate",
    "baseline_pass_rate",
    "tool_mode",
    "fake_verified",
    "target",
    "run_id",
    "run_url",
    "generated_at",
    "finished_at",
    "tests_total",
    "tests_passed",
    "detail_page",
)


def history_entry(latest: dict) -> dict:
    entry = {k: latest.get(k) for k in HISTORY_FIELDS}
    dep = latest.get("deploy") or {}
    entry["cxas_version"] = dep.get("version")
    entry["cxas_version_display_name"] = dep.get("version_display_name")
    return entry


def _entry_time(e: dict) -> str:
    return str(e.get("finished_at") or e.get("generated_at") or "")


def load_history(data_dir: Path | None) -> list[dict]:
    if data_dir is None:
        return []
    h = read_json(Path(data_dir) / "history.json")
    runs = h.get("runs") if isinstance(h, dict) else h
    return [r for r in runs if isinstance(r, dict) and r.get("key")] if isinstance(runs, list) else []


def merge_history(*histories: list[dict]) -> list[dict]:
    """Union by key (later arguments win), oldest first, capped."""
    by_key: dict[str, dict] = {}
    for hist in histories:
        for e in hist:
            by_key[str(e["key"])] = e
    runs = sorted(by_key.values(), key=lambda e: (_entry_time(e), str(e["key"])))
    return runs[-MAX_HISTORY:]


def history_doc(runs: list[dict]) -> dict:
    return {"schema": SCHEMA, "runs": runs}


def local_history_rows(index: Any) -> list[dict]:
    """Rows for the 'pre-CI local runs' section from evals/history/index.json."""
    runs = index.get("runs") if isinstance(index, dict) else None
    rows = []
    for r in runs or []:
        if not isinstance(r, dict):
            continue
        p = f = 0
        for s in (r.get("layers") or {}).values():
            if isinstance(s, dict):
                p += int(s.get("pass") or 0)
                f += int(s.get("fail") or 0)
        rows.append(
            {
                "run_id": r.get("run_id"),
                "mode": r.get("mode"),
                "point_time": r.get("point_time"),
                "imported": bool(r.get("imported")),
                "agent_commit": (r.get("agent_commit") or "")[:7] or None,
                "agent_dirty": r.get("agent_dirty"),
                "model": r.get("model"),
                "passed": p,
                "decided": p + f,
                "infra_errors": r.get("infra_errors"),
                "rationale": (str(r.get("rationale") or "")[:160]) or None,
            }
        )
    return scrub.relativize(rows)


def baseline_from_latest(latest: dict, set_at: str | None = None) -> dict | None:
    """Gate summary to store as data/baseline.json, or None if not eligible
    (only a present gate summary with verdict PASS qualifies)."""
    gate = latest.get("gate_summary")
    if not latest.get("gate_present") or not isinstance(gate, dict):
        return None
    if latest.get("verdict") != "PASS":
        return None
    out = dict(gate)
    out["baseline_set_at"] = set_at or now_utc()
    out["baseline_source_key"] = latest.get("key")
    return out
