"""Run records (schema v1, plan.md §4.3), the history index and digests.

Layout::

    evals/history/runs/<run_id>.json   one record per run
    evals/history/index.json           summary of all records (rebuilt)

run_id = ``<YYYYmmddTHHMMSSZ>_<mode>_<short commit>``.
"""

from __future__ import annotations

import datetime
import hashlib
import json
from pathlib import Path

from totto_suite import config, ids
from totto_suite.taxonomy import STATUSES, Status, summarize_infra

SCHEMA_VERSION = 1
MODES = (
    "offline",
    "live",
    "snapshot",
    "deploy",
    "gate",
    "imported",
    "reproduced",
    "ci",  # `ci-gate` runs against the staging (or --app-name) app
)
# "draft": the run talked to the app's current draft, which has no version id.
VERSION_STATUSES = (
    "in_version_list",
    "hidden_fetchable",
    "imported",
    "not_deployed",
    "draft",
)

REQUIRED_KEYS = (
    "schema_version",
    "run_id",
    "mode",
    "started_at",
    "finished_at",
    "point_time",
    "imported",
    "import_source",
    "agent",
    "suite",
    "cxas",
    "rationale",
    "layers",
    "tests",
    "infra_errors",
    "flakiness",
    "results_digest",
)
AGENT_KEYS = (
    "commit",
    "path",
    "tree_hash",
    "dirty",
    "dirty_paths_relevant",
    "dirty_paths_unrelated",
)
SUITE_KEYS = ("commit", "dirty")
CXAS_KEYS = (
    "app",
    "version_id",
    "version_status",
    "model",
    "app_update_time",
    "app_etag",
)


class RecordError(ValueError):
    pass


def make_run_id(mode: str, commit: str, when: datetime.datetime | None = None) -> str:
    when = when or datetime.datetime.now(datetime.timezone.utc)
    stamp = when.astimezone(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"{stamp}_{mode}_{(commit or 'nocommit')[:7]}"


def results_digest(tests: list[dict]) -> str:
    """sha256 over the sorted (id, repeat, status, message) tuples."""
    rows = sorted(
        (
            str(t.get("id", "")),
            int(t.get("repeat", 1) or 1),
            str(t.get("status", "")),
            str(t.get("message", "") or ""),
        )
        for t in tests
    )
    blob = json.dumps(rows, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def layer_summary(tests: list[dict]) -> dict:
    """Per-layer {pass, fail, infra_error, skipped, score}; score=P/(P+F)."""
    layers: dict[str, dict] = {}
    for t in tests:
        layer = str(t.get("layer", "unknown"))
        s = layers.setdefault(
            layer, {"pass": 0, "fail": 0, "infra_error": 0, "skipped": 0}
        )
        status = t.get("status")
        if status == Status.PASS.value:
            s["pass"] += 1
        elif status == Status.FAIL.value:
            s["fail"] += 1
        elif status == Status.INFRA_ERROR.value:
            s["infra_error"] += 1
        elif status == Status.SKIPPED.value:
            s["skipped"] += 1
    for s in layers.values():
        decided = s["pass"] + s["fail"]
        s["score"] = round(s["pass"] / decided, 4) if decided else None
    return dict(sorted(layers.items()))


def flakiness_summary(tests: list[dict]) -> dict | None:
    """For tests run more than once: per id pass/fail counts and flaky flag."""
    by_id: dict[str, list[str]] = {}
    for t in tests:
        by_id.setdefault(str(t["id"]), []).append(t["status"])
    repeated = {k: v for k, v in by_id.items() if len(v) > 1}
    if not repeated:
        return None
    per_test = {}
    for test_id, statuses in sorted(repeated.items()):
        p = statuses.count(Status.PASS.value)
        f = statuses.count(Status.FAIL.value)
        per_test[test_id] = {
            "runs": len(statuses),
            "pass": p,
            "fail": f,
            "infra_error": statuses.count(Status.INFRA_ERROR.value),
            "flaky": p > 0 and f > 0,
        }
    return {
        "repeated_tests": len(per_test),
        "flaky_tests": sorted(k for k, v in per_test.items() if v["flaky"]),
        "per_test": per_test,
    }


def build_record(
    *,
    mode: str,
    run_id: str,
    started_at: str,
    finished_at: str,
    point_time: str,
    agent: dict,
    suite: dict,
    cxas: dict,
    rationale: str,
    tests: list[dict],
    imported: bool = False,
    import_source: str | None = None,
    extra: dict | None = None,
) -> dict:
    """Assembles a schema-v1 record; derived fields are computed, not passed.

    Configured project/app identifiers (env, gecx-config.json) are scrubbed
    from every input first and ``cxas.app`` is reduced to an app_ref, so no
    command can write them into a record, the index or the trend.
    """
    cxas = dict(cxas)
    if "app" in cxas:
        cxas["app"] = ids.app_ref_for(cxas["app"])
    agent, suite, cxas, rationale, tests, extra = ids.scrub_configured(
        [dict(agent), dict(suite), cxas, rationale, list(tests), dict(extra or {})]
    )
    record = {
        "schema_version": SCHEMA_VERSION,
        "run_id": run_id,
        "mode": mode,
        "started_at": started_at,
        "finished_at": finished_at,
        "point_time": point_time,
        "imported": bool(imported),
        "import_source": import_source,
        "agent": dict(agent),
        "suite": dict(suite),
        "cxas": dict(cxas),
        "rationale": rationale,
        "layers": layer_summary(tests),
        "tests": list(tests),
        "infra_errors": summarize_infra(tests),
        "flakiness": flakiness_summary(tests),
        "results_digest": results_digest(tests),
    }
    for k, v in (extra or {}).items():
        if k in record:
            raise RecordError(f"extra key {k!r} would overwrite a schema field")
        record[k] = v
    validate(record)
    return record


def validate(record: dict) -> None:
    """Raises RecordError if ``record`` violates schema v1."""
    missing = [k for k in REQUIRED_KEYS if k not in record]
    if missing:
        raise RecordError(f"record misses keys {missing}")
    if record["schema_version"] != SCHEMA_VERSION:
        raise RecordError(f"schema_version {record['schema_version']!r} != 1")
    if record["mode"] not in MODES:
        raise RecordError(f"mode {record['mode']!r} not in {MODES}")
    for block, keys in (
        ("agent", AGENT_KEYS),
        ("suite", SUITE_KEYS),
        ("cxas", CXAS_KEYS),
    ):
        miss = [k for k in keys if k not in record[block]]
        if miss:
            raise RecordError(f"record.{block} misses keys {miss}")
    if not record["agent"]["commit"]:
        raise RecordError("record.agent.commit must name a git commit")
    status = record["cxas"]["version_status"]
    if status not in VERSION_STATUSES:
        raise RecordError(f"cxas.version_status {status!r} not in {VERSION_STATUSES}")
    if status in ("in_version_list", "hidden_fetchable") and not record["cxas"][
        "version_id"
    ]:
        raise RecordError(f"version_status {status} needs cxas.version_id")
    if not str(record.get("rationale") or "").strip():
        raise RecordError("record.rationale must say why the change was made")
    if not record["cxas"].get("model"):
        raise RecordError("record.cxas.model must name the model")
    for t in record["tests"]:
        if t.get("status") not in STATUSES:
            raise RecordError(f"test {t.get('id')!r} has invalid status")
    if record["results_digest"] != results_digest(record["tests"]):
        raise RecordError("results_digest does not match tests")


def record_path(run_id: str, runs_dir: Path | None = None) -> Path:
    return Path(runs_dir or config.RUNS_DIR) / f"{run_id}.json"


def check_no_identifiers(text: str, what: str) -> None:
    """Raises RecordError if ``text`` contains a configured project/app identifier."""
    found = ids.find_configured(text)
    if found:
        raise RecordError(f"{what} would contain configured identifiers {found}; refusing to write")


def write_record(record: dict, runs_dir: Path | None = None) -> Path:
    validate(record)
    path = record_path(record["run_id"], runs_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        raise RecordError(f"{path} already exists; run ids must be unique")
    text = json.dumps(record, indent=2, ensure_ascii=False, sort_keys=False) + "\n"
    check_no_identifiers(text, f"record {record['run_id']}")
    path.write_text(text, encoding="utf-8")
    return path


def load_record(path: Path) -> dict:
    record = json.loads(Path(path).read_text(encoding="utf-8"))
    validate(record)
    return record


def load_all(runs_dir: Path | None = None) -> list[dict]:
    """All records, sorted by (point_time, started_at, run_id)."""
    runs_dir = Path(runs_dir or config.RUNS_DIR)
    if not runs_dir.is_dir():
        return []
    records = [load_record(p) for p in sorted(runs_dir.glob("*.json"))]
    records.sort(key=lambda r: (r["point_time"], r["started_at"], r["run_id"]))
    return records


def index_entry(record: dict) -> dict:
    return {
        "run_id": record["run_id"],
        "mode": record["mode"],
        "point_time": record["point_time"],
        "started_at": record["started_at"],
        "imported": record["imported"],
        "agent_commit": record["agent"]["commit"],
        "agent_path": record["agent"]["path"],
        "agent_dirty": record["agent"]["dirty"],
        "version_id": record["cxas"]["version_id"],
        "version_status": record["cxas"]["version_status"],
        "model": record["cxas"]["model"],
        "app_ref": record.get("app_ref"),
        "tool_mode": record.get("tool_mode"),
        "rationale": record["rationale"],
        "layers": record["layers"],
        "infra_errors": record["infra_errors"]["count"],
        "results_digest": record["results_digest"],
        "path": f"runs/{record['run_id']}.json",
    }


def write_index(
    records: list[dict] | None = None,
    index_path: Path | None = None,
    runs_dir: Path | None = None,
) -> Path:
    """Rebuilds index.json from the records (sorted like load_all)."""
    records = load_all(runs_dir) if records is None else records
    index_path = Path(index_path or config.INDEX_PATH)
    index_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": SCHEMA_VERSION,
        "runs": [index_entry(r) for r in records],
    }
    # Older local records may predate scrubbing; the index never repeats them.
    text = json.dumps(ids.scrub_configured(payload), indent=2, ensure_ascii=False) + "\n"
    check_no_identifiers(text, "index.json")
    index_path.write_text(text, encoding="utf-8")
    return index_path


def latest(records: list[dict], mode: str) -> dict | None:
    """The most recently *started* record of ``mode`` (None if none)."""
    matching = [r for r in records if r["mode"] == mode]
    if not matching:
        return None
    return max(matching, key=lambda r: (r["started_at"], r["run_id"]))
