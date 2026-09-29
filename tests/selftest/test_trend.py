"""Trend view: ordering, per-layer cells and regression flags."""

from totto_suite import records, trend


def _rec(run_id, point_time, tests, mode="offline", imported=False):
    return records.build_record(
        mode=mode,
        run_id=run_id,
        started_at=point_time,
        finished_at=point_time,
        point_time=point_time,
        agent={
            "commit": "c0ffee1234567",
            "path": "cxas_app",
            "tree_hash": "h",
            "dirty": False,
            "dirty_paths_relevant": [],
            "dirty_paths_unrelated": [],
        },
        suite={"commit": "c0ffee1234567", "dirty": False},
        cxas={
            "app": "projects/p/locations/l/apps/a",
            "version_id": None,
            "version_status": "imported" if imported else "not_deployed",
            "model": "gemini-3.0-flash-001",
            "app_update_time": None,
            "app_etag": None,
        },
        rationale=f"why {run_id}",
        tests=tests,
        imported=imported,
    )


def _t(test_id, status, repeat=1):
    return {"id": test_id, "layer": test_id.split("::")[0], "status": status, "repeat": repeat}


def test_layer_score_drop_and_pass_to_fail_are_flagged():
    r1 = _rec("r1", "2026-09-28T17:00:00Z", [_t("tools::a", "PASS"), _t("tools::b", "PASS")])
    r2 = _rec("r2", "2026-09-28T18:00:00Z", [_t("tools::a", "PASS"), _t("tools::b", "FAIL")])
    flags = trend.compute_regressions([r1, r2])
    assert flags["r1"] == []
    kinds = sorted(f["type"] for f in flags["r2"])
    assert kinds == ["layer_score_drop", "test_pass_to_fail"]
    drop = next(f for f in flags["r2"] if f["type"] == "layer_score_drop")
    assert (drop["layer"], drop["from"], drop["to"], drop["previous_run"]) == ("tools", 1.0, 0.5, "r1")


def test_improvement_and_infra_errors_are_not_regressions():
    r1 = _rec("r1", "2026-09-28T17:00:00Z", [_t("tools::a", "FAIL"), _t("tools::b", "PASS")])
    r2 = _rec(
        "r2",
        "2026-09-28T18:00:00Z",
        [_t("tools::a", "PASS"), _t("tools::b", "INFRA_ERROR")],
    )
    assert trend.compute_regressions([r1, r2])["r2"] == []


def test_comparison_skips_points_without_the_layer():
    r1 = _rec("r1", "2026-09-28T17:00:00Z", [_t("tools::a", "PASS")])
    r2 = _rec("r2", "2026-09-28T18:00:00Z", [], mode="snapshot")
    r3 = _rec("r3", "2026-09-28T19:00:00Z", [_t("tools::a", "FAIL")])
    flags = trend.compute_regressions([r1, r2, r3])
    assert flags["r2"] == []
    assert {f["previous_run"] for f in flags["r3"]} == {"r1"}


def test_flaky_repeat_after_pass_is_flagged():
    r1 = _rec("r1", "2026-09-28T17:00:00Z", [_t("live_sims::s", "PASS")], mode="live")
    r2 = _rec(
        "r2",
        "2026-09-28T18:00:00Z",
        [_t("live_sims::s", "PASS", 1), _t("live_sims::s", "FAIL", 2)],
        mode="live",
    )
    flags = trend.compute_regressions([r1, r2])["r2"]
    assert any(f["type"] == "test_pass_to_fail" and f["to"] == "FLAKY" for f in flags)


def test_generate_writes_ordered_markdown_and_static_html(tmp_path):
    runs = tmp_path / "runs"
    late = _rec("late", "2026-09-28T19:00:00Z", [_t("tools::a", "FAIL")])
    early = _rec("early", "2026-09-28T17:00:00Z", [_t("tools::a", "PASS")], imported=True)
    records.write_record(late, runs_dir=runs)
    records.write_record(early, runs_dir=runs)
    info = trend.generate(
        runs_dir=runs,
        md_path=tmp_path / "TREND.md",
        html_path=tmp_path / "trend.html",
        index_path=tmp_path / "index.json",
    )
    assert info["points"] == 2 and info["regressions"] == 2
    md = (tmp_path / "TREND.md").read_text()
    assert md.index("why early") < md.index("why late")  # ordered by point_time
    assert "REGRESSION layer tools: 100% -> 0%" in md
    assert "REGRESSION tools::a: PASS -> FAIL" in md
    assert "| imported |" in md and "| yes |" in md
    html = (tmp_path / "trend.html").read_text()
    assert "<script" not in html and "<link" not in html
    assert 'src="http' not in html and "href=\"http" not in html
    assert "REGRESSION" in html
