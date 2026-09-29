"""Builder tests: `python -m totto_suite dashboard build/merge/check`."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from totto_suite.dashboard import command, model, render, scrub

REPO_ROOT = Path(__file__).resolve().parents[2]
SHA_A = "a" * 8 + "1234567890abcdef1234567890abcdef"
SHA_B = "b" * 8 + "1234567890abcdef1234567890abcdef"
REPO_URL = "https://github.com/example-owner/example-repo"
EVAL_RUN = "evaluationRuns/1b2c3d4e-0000-4000-8000-000000000001"
# Fake identifiers are assembled at runtime so that repository-wide identifier
# scans of tracked files never see a literal project/app ID or email address.
FAKE_PROJECT = "acme" + "-prod-42"
FAKE_APP = "0f0e0d0c-1111-4222-8333-" + "444455556666"
FAKE_FULL_APP = "projects/" + FAKE_PROJECT + "/locations/us/apps/" + FAKE_APP
FAKE_EMAIL = "alice.person" + "@" + "example.com"


def gate_summary(commit=SHA_A, run_id="ci-101", verdict="PASS", pass_rate=0.9, **extra):
    d = {
        "schema": "totto-gate-summary/v1",
        "commit": commit,
        "run_id": run_id,
        "run_url": f"https://github.com/example-owner/example-repo/actions/runs/{run_id[3:]}",
        "target": "staging",
        "tool_mode": "fake",
        "fake_verified": True,
        "pass_rate": pass_rate,
        "baseline_pass_rate": 0.85,
        "verdict": verdict,
        "reasons": [f"pass rate {pass_rate * 100:.1f}% vs baseline 85.0%"],
        "layers": {"tools": {"pass": 9, "fail": 1, "infra_error": 0, "skipped": 0, "pass_rate": 0.9}},
        "started_at": "2026-09-29T20:50:00Z",
        "finished_at": f"2026-09-29T21:{int(run_id[-2:]):02d}:00Z",
        "tests": [
            {
                "id": "tool_get_race_schedule_next",
                "layer": "tools",
                "status": "PASS",
                "repeats": [{"status": "PASS"}],
                "platform_ids": [EVAL_RUN, "sessions/5e55-1"],
                "tool_mode": "fake",
                "fake_verified": True,
            },
            {
                "id": "golden_standings",
                "layer": "goldens",
                "status": "FAIL",
                "repeats": ["PASS", "FAIL"],
                "platform_ids": {"evaluation": "evaluations/golden-standings"},
                "tool_mode": "fake",
            },
        ],
    }
    d.update(extra)
    return d


def write(path: Path, obj) -> Path:
    path.write_text(json.dumps(obj), encoding="utf-8")
    return path


def build(tmp_path: Path, out: str, *args: str) -> tuple[int, Path]:
    site = tmp_path / out
    rc = command.main(["build", "--out", str(site), "--repo-url", REPO_URL, *args])
    return rc, site


@pytest.fixture(autouse=True)
def _no_ci_env(monkeypatch):
    for var in ("DASHBOARD_DENY", "GITHUB_SERVER_URL", "GITHUB_REPOSITORY"):
        monkeypatch.delenv(var, raising=False)


def test_build_shows_commit_sha_link_verdict_and_pass_rates(tmp_path):
    g = write(tmp_path / "gate.json", gate_summary())
    rc, site = build(tmp_path, "site", "--gate-summary", str(g))
    assert rc == 0
    index = (site / "index.html").read_text()
    assert f'href="{REPO_URL}/commit/{SHA_A}"' in index
    assert f">{SHA_A}<" in index  # full SHA displayed prominently
    assert 'class="verdict PASS">PASS<' in index
    assert "90.0%" in index and "85.0%" in index
    assert "fake (fake results verified)" in index
    assert "https://github.com/example-owner/example-repo/actions/runs/101" in index
    latest = json.loads((site / "data/latest.json").read_text())
    assert latest["verdict"] == "PASS" and latest["commit"] == SHA_A
    assert latest["tests_total"] == 2 and latest["tests_passed"] == 1
    detail = (site / latest["detail_page"]).read_text()
    assert "tool_get_race_schedule_next" in detail and EVAL_RUN in detail
    assert "evaluations/golden-standings" in detail  # dict-shaped platform_ids tolerated
    assert (site / ".nojekyll").is_file()


def test_build_without_gate_summary_shows_label_and_no_invented_result(tmp_path):
    rc, site = build(tmp_path, "site", "--commit", SHA_A)
    assert rc == 0
    latest = json.loads((site / "data/latest.json").read_text())
    assert latest["verdict"] == model.NO_GATE_LABEL
    assert latest["gate_present"] is False
    assert latest["pass_rate"] is None and latest["tests"] == [] and latest["detail_page"] is None
    index = (site / "index.html").read_text()
    assert SHA_A in index and "NO GATED RUN YET" in index
    assert "not a test result" in index
    assert not (site / "runs").exists()


def test_missing_gate_file_uses_custom_label(tmp_path):
    rc, site = build(
        tmp_path,
        "site",
        "--commit",
        SHA_A,
        "--gate-summary",
        str(tmp_path / "absent.json"),
        "--missing-gate-label",
        "NO GATE RESULT (staging-gate job: failure)",
    )
    assert rc == 0
    assert "NO GATE RESULT (staging-gate job: failure)" in (site / "index.html").read_text()


def test_build_tolerates_minimal_gate_summary(tmp_path):
    g = write(tmp_path / "gate.json", {"verdict": "fail"})
    rc, site = build(tmp_path, "site", "--commit", SHA_B)
    rc, site = build(tmp_path, "site2", "--commit", SHA_B, "--gate-summary", str(g))
    assert rc == 0
    latest = json.loads((site / "data/latest.json").read_text())
    assert latest["verdict"] == "FAIL"
    assert latest["pass_rate"] is None and latest["tool_mode"] is None
    assert "n/a" in (site / "index.html").read_text()


def test_unreadable_gate_summary_is_labelled_not_guessed(tmp_path):
    bad = tmp_path / "gate.json"
    bad.write_text("{not json", encoding="utf-8")
    rc, site = build(tmp_path, "site", "--commit", SHA_A, "--gate-summary", str(bad))
    assert rc == 0
    latest = json.loads((site / "data/latest.json").read_text())
    assert latest["verdict"] == model.UNREADABLE_LABEL and latest["gate_present"] is False


def test_deploy_record_version_is_shown_app_relative(tmp_path):
    g = write(tmp_path / "gate.json", gate_summary())
    d = write(
        tmp_path / "deploy.json",
        {
            "commit": SHA_A,
            "version": {
                "name": FAKE_FULL_APP + "/versions/9a8b7c6d-1111-4222-8333-444455556666",
                "display_name": "git-aaaaaaa",
            },
        },
    )
    rc, site = build(tmp_path, "site", "--gate-summary", str(g), "--deploy-record", str(d))
    assert rc == 0
    index = (site / "index.html").read_text()
    assert "versions/9a8b7c6d-1111-4222-8333-444455556666" in index and "git-aaaaaaa" in index
    assert FAKE_PROJECT not in index and "projects/" not in index


def test_deploy_live_record_shape_version_phone_and_failure(tmp_path):
    """Shape written by scripts/ci/deploy_live.py (version dict + phone_deployments entries)."""
    g = write(tmp_path / "gate.json", gate_summary())
    ok = {
        "schema": "totto-deploy/v1",
        "commit": SHA_A,
        "status": "SUCCESS",
        "version": {"id": "versions/v-123", "display_name": "git-aaaaaaa", "verified": True},
        "phone_deployments": [
            {
                "deployment": "deployments/gtp-1",
                "previous_version": "versions/v-100",
                "new_version": "versions/v-123",
                "verified": True,
            }
        ],
    }
    rc, site = build(tmp_path, "ok", "--gate-summary", str(g), "--deploy-record", str(write(tmp_path / "d.json", ok)))
    assert rc == 0
    latest = json.loads((site / "data/latest.json").read_text())
    assert latest["deploy"]["version"] == "versions/v-123"
    assert latest["deploy"]["phone_deployments"] == ["deployments/gtp-1"]
    assert "git-aaaaaaa" in (site / "index.html").read_text()

    failed = {"commit": SHA_A, "status": "FAILED", "failed_step": "push", "version": None, "phone_deployments": []}
    rc, site = build(
        tmp_path, "bad", "--gate-summary", str(g), "--deploy-record", str(write(tmp_path / "f.json", failed))
    )
    index = (site / "index.html").read_text()
    assert "no live deploy recorded" in index and ">FAILED<" in index and "at step push" in index


def test_history_appends_across_builds_and_rerun_replaces(tmp_path):
    rc, a = build(tmp_path, "a", "--gate-summary", str(write(tmp_path / "g1.json", gate_summary())))
    assert rc == 0
    g2 = write(tmp_path / "g2.json", gate_summary(commit=SHA_B, run_id="ci-102", verdict="FAIL", pass_rate=0.5))
    rc, b = build(tmp_path, "b", "--gate-summary", str(g2), "--history-dir", str(a))
    assert rc == 0
    runs = json.loads((b / "data/history.json").read_text())["runs"]
    assert [r["commit"] for r in runs] == [SHA_A, SHA_B]
    assert [r["verdict"] for r in runs] == ["PASS", "FAIL"]
    # a re-run of the same CI run id replaces its entry instead of duplicating it
    rc, c = build(tmp_path, "c", "--gate-summary", str(g2), "--history-dir", str(b / "data"))
    assert len(json.loads((c / "data/history.json").read_text())["runs"]) == 2
    index = (b / "index.html").read_text()
    assert "<svg" in index and "<polyline" in index  # trend chart with 2 points


def test_full_resource_names_are_relativized_before_render(tmp_path):
    full = FAKE_FULL_APP
    g = write(
        tmp_path / "gate.json",
        gate_summary(
            tests=[
                {
                    "id": "t1",
                    "status": "PASS",
                    "platform_ids": [f"{full}/evaluationRuns/77", f"{full}/sessions/88"],
                    "message": f"ok for {full}/evaluations/e1",
                }
            ]
        ),
    )
    rc, site = build(tmp_path, "site", "--gate-summary", str(g))
    assert rc == 0
    for p in site.rglob("*"):
        if p.is_file():
            text = p.read_text()
            assert FAKE_PROJECT not in text and FAKE_APP not in text, p
    detail = next((site / "runs").glob("*.html")).read_text()
    assert "evaluationRuns/77" in detail and "sessions/88" in detail and "evaluations/e1" in detail


def test_build_fails_on_email_and_does_not_echo_it(tmp_path, capsys):
    g = write(tmp_path / "gate.json", gate_summary(reasons=["approved by " + FAKE_EMAIL]))
    rc, _ = build(tmp_path, "site", "--gate-summary", str(g))
    assert rc == command.EXIT_BAD
    out = capsys.readouterr().out
    assert "identifier check FAILED" in out and "email address" in out
    assert FAKE_EMAIL not in out


def test_build_fails_on_deny_listed_literal(tmp_path, monkeypatch):
    monkeypatch.setenv("DASHBOARD_DENY", "staging-app-secret-id,xx")
    g = write(tmp_path / "gate.json", gate_summary(target="staging-app-secret-id"))
    rc, _ = build(tmp_path, "site", "--gate-summary", str(g))
    assert rc == command.EXIT_BAD


@pytest.mark.parametrize(
    "text,kinds",
    [
        ("projects/your-gcp-project/locations/us/apps/x", []),
        ("projects/<YOUR_GCP_PROJECT_ID>/locations/us", []),
        ("projects/&lt;YOUR_GCP_PROJECT_ID&gt;/locations/us", []),
        ("projects/" + FAKE_PROJECT + "/locations/us", ["project id in resource name"]),
        ("apps/00000000-0000-0000-0000-000000000000/sessions/1", []),
        ("x/apps/" + FAKE_APP, ["app id in full resource name"]),
        ("evaluationRuns/" + FAKE_APP, []),
        ("mail me: " + FAKE_EMAIL, ["email address"]),
        ('<svg xmlns="http://www.w3.org/2000/svg">', []),
    ],
)
def test_find_leaks_patterns(text, kinds):
    assert [f.kind for f in scrub.find_leaks(text, deny=[])] == kinds


def test_default_deny_list_ignores_short_and_placeholder_values():
    deny = scrub.default_deny_list({"DASHBOARD_DENY": "us, ,your-gcp-project,real-app-id-123"})
    assert "real-app-id-123" in deny
    assert "us" not in deny and "your-gcp-project" not in deny
    assert scrub.ZERO_UUID not in deny


def test_voice_comparison_and_local_history_sections(tmp_path):
    voice = write(
        tmp_path / "voice.json",
        [
            {
                "model": "gemini-3.0-flash-001",
                "run_id": "evaluationRuns/v1",
                "pass_rate": 0.8,
                "passed": 4,
                "total": 5,
                "median_turn_latency_s": 1.234,
                "p90_turn_latency_s": 2.5,
                "notes": "speech",
            },
            {"model": "gemini-3.1-flash-live", "run_id": "evaluationRuns/v2"},  # sparse row
        ],
    )
    index_json = write(
        tmp_path / "index.json",
        {"runs": [{"run_id": "r1", "mode": "offline", "agent_commit": "c" * 40,
                   "layers": {"tools": {"pass": 3, "fail": 1}}}]},
    )
    rc, site = build(
        tmp_path, "site", "--commit", SHA_A, "--voice-comparison", str(voice),
        "--local-history", str(index_json),
    )
    assert rc == 0
    index = (site / "index.html").read_text()
    assert "Voice model comparison" in index and "1.23 s" in index and "gemini-3.1-flash-live" in index
    assert "Pre-CI local runs (not gate results)" in index and "3/4" in index
    # carried forward to the next build via --history-dir
    rc, site2 = build(tmp_path, "site2", "--commit", SHA_B, "--history-dir", str(site))
    index2 = (site2 / "index.html").read_text()
    assert "Voice model comparison" in index2 and "Pre-CI local runs" in index2


def test_pages_are_self_contained_and_links_relative(tmp_path):
    rc, site = build(tmp_path, "site", "--gate-summary", str(write(tmp_path / "g.json", gate_summary())))
    for page in [site / "index.html", *(site / "runs").glob("*.html")]:
        text = page.read_text()
        assert "<script" not in text and "<link" not in text and "@import" not in text
        assert 'src="http' not in text
    index = (site / "index.html").read_text()
    assert 'href="runs/ci-101.html"' in index and 'href="data/latest.json"' in index


def test_render_is_deterministic(tmp_path):
    rc, site = build(tmp_path, "site", "--gate-summary", str(write(tmp_path / "g.json", gate_summary())))
    first = (site / "index.html").read_bytes()
    render.render_site(site)
    assert (site / "index.html").read_bytes() == first


def test_merge_update_baseline_only_on_pass(tmp_path):
    rc, passed = build(tmp_path, "p", "--gate-summary", str(write(tmp_path / "g1.json", gate_summary())))
    assert command.main(["merge", "--site", str(passed), "--update-baseline"]) == 0
    base = json.loads((passed / "data/baseline.json").read_text())
    assert base["commit"] == SHA_A and base["verdict"] == "PASS" and base["pass_rate"] == 0.9
    assert "Current gate baseline: 90.0%" in (passed / "index.html").read_text()

    g2 = write(tmp_path / "g2.json", gate_summary(commit=SHA_B, run_id="ci-102", verdict="FAIL", pass_rate=0.4))
    rc, failed = build(tmp_path, "f", "--gate-summary", str(g2))
    assert command.main(
        ["merge", "--site", str(failed), "--previous-data", str(passed / "data"), "--update-baseline"]
    ) == 0
    kept = json.loads((failed / "data/baseline.json").read_text())
    assert kept["commit"] == SHA_A  # FAIL never moves the baseline
    assert len(json.loads((failed / "data/history.json").read_text())["runs"]) == 2

    rc, nogate = build(tmp_path, "n", "--commit", SHA_B)
    assert command.main(["merge", "--site", str(nogate), "--update-baseline"]) == 0
    assert not (nogate / "data/baseline.json").exists()


def test_check_subcommand_flags_leak_in_any_file(tmp_path):
    (tmp_path / "x").mkdir()
    (tmp_path / "x/page.html").write_text(FAKE_FULL_APP, encoding="utf-8")
    assert command.main(["check", str(tmp_path / "x")]) == command.EXIT_BAD
    (tmp_path / "x/page.html").write_text("evaluationRuns/1", encoding="utf-8")
    assert command.main(["check", str(tmp_path / "x")]) == 0


def test_registered_as_totto_suite_subcommand(tmp_path):
    proc = subprocess.run(
        [sys.executable, "-m", "totto_suite", "dashboard", "build", "--help"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert proc.returncode == 0, proc.stderr
    assert "--gate-summary" in proc.stdout and "--history-dir" in proc.stdout
