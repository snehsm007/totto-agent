"""Tests for the hill-climbing, bundling, diff-check, and dynamic evaluation scripts."""

from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = PROJECT_ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import bundle_shared_imports  # noqa: E402
import diff_check  # noqa: E402
import local_eval_runner  # noqa: E402


def test_bundle_shared_prompts_sync_check() -> None:
    assert bundle_shared_imports.sync_shared_prompts(check_only=True) is True


def test_diff_check_detects_modified_files(tmp_path: Path) -> None:
    dir_a = tmp_path / "a"
    dir_b = tmp_path / "b"
    dir_a.mkdir()
    dir_b.mkdir()
    (dir_a / "instruction.txt").write_text("<role>v1</role>\n", encoding="utf-8")
    (dir_b / "instruction.txt").write_text("<role>v2</role>\n", encoding="utf-8")

    diffs = diff_check.compute_dir_diff(dir_a, dir_b)
    assert any("-<role>v1</role>" in line for line in diffs)
    assert any("+<role>v2</role>" in line for line in diffs)


def test_local_eval_runner_passes_100_percent_on_final_state() -> None:
    summary = local_eval_runner.evaluate_all()
    assert summary["tool_tests"]["pass_rate"] == 100.0
    assert summary["public_evals"]["pass_rate"] == 100.0
    assert summary["secret_holdout"]["pass_rate"] == 100.0
    assert summary["overall"]["pass_rate"] == 100.0
    assert summary["failing_ids"] == []


def test_hill_climb_artifacts_and_three_iterations_recorded() -> None:
    results_tsv = PROJECT_ROOT / "results.tsv"
    assert results_tsv.exists()
    lines = [line.strip() for line in results_tsv.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert len(lines) >= 4  # header + at least 3 iterations
    statuses = [line.split("\t")[7] for line in lines[1:4]]
    assert statuses == ["baseline", "kept", "reverted"]

    for iter_num, badge in [(1, "[BASELINE]"), (2, "[KEPT]"), (3, "[REVERTED]")]:
        report_path = PROJECT_ROOT / "evals" / "results" / f"iteration-{iter_num}.md"
        assert report_path.exists()
        assert badge in report_path.read_text(encoding="utf-8")

    dashboard_path = PROJECT_ROOT / "evals" / "results" / "dashboard.html"
    assert dashboard_path.exists()
    dashboard_html = dashboard_path.read_text(encoding="utf-8")
    assert "Totto, Mercedes F1 Fan Agent" in dashboard_html
    assert "[KEPT]" in dashboard_html
    assert "[REVERTED]" in dashboard_html

    release_notes = PROJECT_ROOT / "release-notes.md"
    assert release_notes.exists()
    rn_text = release_notes.read_text(encoding="utf-8")
    assert "Iteration 1" in rn_text and "Iteration 2" in rn_text and "Iteration 3" in rn_text
