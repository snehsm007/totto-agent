"""scripts/publish_dashboard.sh against a local bare repository acting as origin."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from totto_suite.dashboard import command

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "publish_dashboard.sh"
SHA_A = "a" * 40
SHA_B = "b" * 40

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git not installed")


def git_env(home: Path) -> dict:
    env = dict(os.environ)
    env.update(
        {
            "HOME": str(home),
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_AUTHOR_NAME": "test",
            "GIT_AUTHOR_EMAIL": "test@localhost.invalid",
            "GIT_COMMITTER_NAME": "test",
            "GIT_COMMITTER_EMAIL": "test@localhost.invalid",
            "PYTHON": sys.executable,
        }
    )
    for var in ("DASHBOARD_UPDATE_BASELINE", "DASHBOARD_DENY", "GITHUB_SERVER_URL", "GITHUB_REPOSITORY"):
        env.pop(var, None)
    return env


def git(cwd: Path, env: dict, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=cwd, env=env, check=True, capture_output=True, text=True, timeout=60
    ).stdout.strip()


@pytest.fixture()
def repos(tmp_path):
    """(origin bare repo, working clone with one commit on main, env)."""
    env = git_env(tmp_path)
    origin = tmp_path / "origin.git"
    work = tmp_path / "work"
    git(tmp_path, env, "init", "-q", "--bare", "-b", "main", str(origin))
    git(tmp_path, env, "init", "-q", "-b", "main", str(work))
    (work / "README.md").write_text("hello\n", encoding="utf-8")
    git(work, env, "add", "README.md")
    git(work, env, "commit", "-q", "-m", "init")
    git(work, env, "remote", "add", "origin", str(origin))
    git(work, env, "push", "-q", "origin", "main")
    return origin, work, env


def gate(commit: str, run_id: str, verdict: str, rate: float) -> dict:
    return {
        "commit": commit,
        "run_id": run_id,
        "verdict": verdict,
        "pass_rate": rate,
        "tool_mode": "fake",
        "finished_at": f"2026-09-29T21:{int(run_id[-2:]):02d}:00Z",
        "tests": [{"id": "t1", "status": verdict, "platform_ids": ["evaluationRuns/1"]}],
    }


def build_site(tmp_path: Path, name: str, g: dict | None, commit: str | None = None) -> Path:
    site = tmp_path / name
    args = ["build", "--out", str(site), "--repo-url", "https://github.com/o/r"]
    if g is not None:
        gp = tmp_path / f"{name}.gate.json"
        gp.write_text(json.dumps(g), encoding="utf-8")
        args += ["--gate-summary", str(gp)]
    if commit:
        args += ["--commit", commit]
    assert command.main(args) == 0
    return site


def publish(work: Path, env: dict, site: Path, *flags: str, extra_env: dict | None = None):
    return subprocess.run(
        ["bash", str(SCRIPT), *flags, str(site)],
        cwd=work,
        env={**env, **(extra_env or {})},
        capture_output=True,
        text=True,
        timeout=120,
    )


def show(origin: Path, env: dict, path: str) -> str:
    return git(origin, env, "show", f"dashboard:{path}")


def test_publish_twice_grows_history_and_never_touches_main(tmp_path, repos):
    origin, work, env = repos
    main_before = git(origin, env, "rev-parse", "refs/heads/main")
    head_before = git(work, env, "rev-parse", "HEAD")

    site1 = build_site(tmp_path, "s1", gate(SHA_A, "ci-01", "PASS", 0.9))
    p1 = publish(work, env, site1)
    assert p1.returncode == 0, p1.stdout + p1.stderr
    assert "creating it" in p1.stdout
    h1 = json.loads(show(origin, env, "data/history.json"))["runs"]
    assert [r["commit"] for r in h1] == [SHA_A]

    # Second build does NOT pass --history-dir: the publisher must merge history itself.
    site2 = build_site(tmp_path, "s2", gate(SHA_B, "ci-02", "FAIL", 0.4))
    p2 = publish(work, env, site2)
    assert p2.returncode == 0, p2.stdout + p2.stderr
    h2 = json.loads(show(origin, env, "data/history.json"))["runs"]
    assert [(r["commit"], r["verdict"]) for r in h2] == [(SHA_A, "PASS"), (SHA_B, "FAIL")]

    index = show(origin, env, "index.html")
    assert SHA_B in index and 'class="verdict FAIL"' in index
    # the first run's detail page is kept from the previous publish
    assert "t1" in show(origin, env, "runs/ci-01.html")
    assert show(origin, env, ".nojekyll") == ""

    # linear branch history (fast-forward, parent = previous tip)
    log = git(origin, env, "log", "--format=%s", "dashboard").splitlines()
    assert len(log) == 2 and log[0].startswith("dashboard: bbbbbbb FAIL")

    # main branch, HEAD, index and working tree untouched
    assert git(origin, env, "rev-parse", "refs/heads/main") == main_before
    assert git(work, env, "rev-parse", "HEAD") == head_before
    assert git(work, env, "status", "--porcelain") == ""
    assert git(work, env, "symbolic-ref", "HEAD") == "refs/heads/main"


def test_publish_same_site_again_is_a_no_op(tmp_path, repos):
    origin, work, env = repos
    site = build_site(tmp_path, "s1", gate(SHA_A, "ci-01", "PASS", 0.9))
    assert publish(work, env, site).returncode == 0
    tip = git(origin, env, "rev-parse", "dashboard")
    again = publish(work, env, site)
    assert again.returncode == 0, again.stderr
    assert "no changes" in again.stdout
    assert git(origin, env, "rev-parse", "dashboard") == tip


def test_baseline_written_only_when_flag_set_and_gate_passed(tmp_path, repos):
    origin, work, env = repos
    s_pass = build_site(tmp_path, "p", gate(SHA_A, "ci-01", "PASS", 0.9))
    # PASS but no flag: no baseline
    assert publish(work, env, s_pass).returncode == 0
    with pytest.raises(subprocess.CalledProcessError):
        show(origin, env, "data/baseline.json")
    # PASS + env flag: baseline = this gate summary
    s_pass2 = build_site(tmp_path, "p2", gate(SHA_A, "ci-02", "PASS", 0.95))
    r = publish(work, env, s_pass2, extra_env={"DASHBOARD_UPDATE_BASELINE": "1"})
    assert r.returncode == 0, r.stdout + r.stderr
    base = json.loads(show(origin, env, "data/baseline.json"))
    assert base["run_id"] == "ci-02" and base["pass_rate"] == 0.95
    # FAIL + flag (e.g. misconfigured workflow): baseline kept
    s_fail = build_site(tmp_path, "f", gate(SHA_B, "ci-03", "FAIL", 0.2))
    r = publish(work, env, s_fail, "--update-baseline")
    assert r.returncode == 0 and "baseline NOT updated" in r.stdout
    assert json.loads(show(origin, env, "data/baseline.json"))["run_id"] == "ci-02"
    # no gate summary at all: baseline kept, verdict label shown
    s_none = build_site(tmp_path, "n", None, commit=SHA_B)
    assert publish(work, env, s_none, "--update-baseline").returncode == 0
    assert json.loads(show(origin, env, "data/baseline.json"))["run_id"] == "ci-02"
    assert "NO GATED RUN YET" in show(origin, env, "index.html")


def test_leaky_site_is_not_published(tmp_path, repos):
    origin, work, env = repos
    site = build_site(tmp_path, "s1", gate(SHA_A, "ci-01", "PASS", 0.9))
    # simulate an identifier sneaking into the data after the build
    latest = json.loads((site / "data/latest.json").read_text())
    latest["target"] = "projects/" + "acme" + "-prod-42/locations/us/apps/x"
    (site / "data/latest.json").write_text(json.dumps(latest), encoding="utf-8")
    r = publish(work, env, site)
    assert r.returncode != 0
    assert "identifier check FAILED" in r.stdout
    assert git(origin, env, "ls-remote", "--heads", str(origin), "dashboard") == ""


def test_dry_run_does_not_push(tmp_path, repos):
    origin, work, env = repos
    site = build_site(tmp_path, "s1", gate(SHA_A, "ci-01", "PASS", 0.9))
    r = publish(work, env, site, "--dry-run")
    assert r.returncode == 0 and "dry run" in r.stdout
    assert git(origin, env, "ls-remote", "--heads", str(origin), "dashboard") == ""


def test_requires_a_built_site(tmp_path, repos):
    _, work, env = repos
    (tmp_path / "empty").mkdir()
    r = publish(work, env, tmp_path / "empty")
    assert r.returncode == 2 and "dashboard build" in r.stderr
