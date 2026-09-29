"""Run records: schema v1, digest stability, scoring, index."""

import json

import pytest

from totto_suite import records


def _t(test_id, status, repeat=1, message="", layer=None):
    return {
        "id": test_id,
        "layer": layer or test_id.split("::")[0],
        "status": status,
        "repeat": repeat,
        "message": message,
    }


def _record(tests, **overrides):
    kwargs = dict(
        mode="offline",
        run_id="20260928T220000Z_offline_abcdef1",
        started_at="2026-09-28T22:00:00Z",
        finished_at="2026-09-28T22:00:05Z",
        point_time="2026-09-28T20:55:59Z",
        agent={
            "commit": "abcdef1234567",
            "path": "cxas_app",
            "tree_hash": "h",
            "dirty": False,
            "dirty_paths_relevant": [],
            "dirty_paths_unrelated": [],
        },
        suite={"commit": "abcdef1234567", "dirty": False},
        cxas={
            "app": "projects/p/locations/l/apps/a",
            "version_id": None,
            "version_status": "not_deployed",
            "model": "gemini-3.0-flash-001",
            "app_update_time": None,
            "app_etag": None,
        },
        rationale="because",
        tests=tests,
    )
    kwargs.update(overrides)
    return records.build_record(**kwargs)


def test_digest_is_independent_of_result_order():
    a = [_t("tools::x", "PASS"), _t("tools::y", "FAIL", message="boom")]
    assert records.results_digest(a) == records.results_digest(list(reversed(a)))


def test_digest_changes_when_status_or_message_changes():
    base = [_t("tools::x", "PASS")]
    assert records.results_digest(base) != records.results_digest(
        [_t("tools::x", "FAIL")]
    )
    assert records.results_digest(base) != records.results_digest(
        [_t("tools::x", "PASS", message="different")]
    )
    assert records.results_digest(base) != records.results_digest(
        [_t("tools::x", "PASS", repeat=2)]
    )


def test_digest_ignores_durations_and_other_fields():
    a = [dict(_t("tools::x", "PASS"), duration_s=0.1, evidence="a")]
    b = [dict(_t("tools::x", "PASS"), duration_s=9.9, evidence="b")]
    assert records.results_digest(a) == records.results_digest(b)


def test_layer_summary_scores_exclude_infra_and_skipped():
    tests = [
        _t("tools::a", "PASS"),
        _t("tools::b", "FAIL"),
        _t("tools::c", "INFRA_ERROR"),
        _t("tools::d", "SKIPPED"),
        _t("lint::e", "INFRA_ERROR"),
    ]
    s = records.layer_summary(tests)
    assert s["tools"] == {
        "pass": 1,
        "fail": 1,
        "infra_error": 1,
        "skipped": 1,
        "score": 0.5,
    }
    assert s["lint"]["score"] is None  # nothing decided -> no score


def test_build_record_has_every_schema_field_and_derived_values():
    rec = _record(
        [_t("tools::a", "PASS"), _t("tools::b", "INFRA_ERROR", message="INFRA_ERROR[quota] 429: x")]
    )
    for key in records.REQUIRED_KEYS:
        assert key in rec
    assert rec["schema_version"] == 1
    assert rec["infra_errors"] == {"count": 1, "by_kind": {"quota": 1}}
    assert rec["flakiness"] is None
    assert rec["results_digest"] == records.results_digest(rec["tests"])


def test_flakiness_reports_mixed_repeats():
    rec = _record(
        [
            _t("live_sims::s", "PASS", repeat=1),
            _t("live_sims::s", "FAIL", repeat=2),
            _t("live_sims::s", "PASS", repeat=3),
            _t("live_sims::t", "PASS", repeat=1),
            _t("live_sims::t", "PASS", repeat=2),
        ],
        mode="live",
    )
    assert rec["flakiness"]["flaky_tests"] == ["live_sims::s"]
    assert rec["flakiness"]["per_test"]["live_sims::t"]["flaky"] is False


@pytest.mark.parametrize(
    "mutate, match",
    [
        (lambda r: r.pop("rationale"), "misses keys"),
        (lambda r: r.update(rationale="  "), "rationale"),
        (lambda r: r.update(mode="bogus"), "mode"),
        (lambda r: r["agent"].update(commit=""), "commit"),
        (lambda r: r["cxas"].update(version_status="in_version_list"), "version_id"),
        (lambda r: r["cxas"].update(model=""), "model"),
        (lambda r: r["tests"].append(_t("tools::z", "MAYBE")), "invalid status"),
        (lambda r: r.update(results_digest="0" * 64), "results_digest"),
    ],
)
def test_validate_rejects_schema_violations(mutate, match):
    rec = _record([_t("tools::a", "PASS")])
    mutate(rec)
    with pytest.raises(records.RecordError, match=match):
        records.validate(rec)


def test_write_load_index_roundtrip(tmp_path):
    runs = tmp_path / "runs"
    r1 = _record([_t("tools::a", "PASS")])
    r2 = _record(
        [_t("tools::a", "FAIL")],
        run_id="20260928T210000Z_offline_1234567",
        point_time="2026-09-28T17:00:00Z",
    )
    records.write_record(r1, runs_dir=runs)
    records.write_record(r2, runs_dir=runs)
    with pytest.raises(records.RecordError, match="already exists"):
        records.write_record(r1, runs_dir=runs)
    loaded = records.load_all(runs)
    assert [r["run_id"] for r in loaded] == [r2["run_id"], r1["run_id"]]  # by point_time
    idx_path = records.write_index(loaded, index_path=tmp_path / "index.json")
    idx = json.loads(idx_path.read_text())
    assert [e["run_id"] for e in idx["runs"]] == [r2["run_id"], r1["run_id"]]
    assert idx["runs"][0]["path"] == f"runs/{r2['run_id']}.json"
    assert records.latest(loaded, "offline")["run_id"] == r1["run_id"]
    assert records.latest(loaded, "snapshot") is None


def test_make_run_id_format():
    import datetime

    when = datetime.datetime(2026, 9, 28, 21, 5, 7, tzinfo=datetime.timezone.utc)
    assert (
        records.make_run_id("snapshot", "f073e02cd3466ad", when)
        == "20260928T210507Z_snapshot_f073e02"
    )
