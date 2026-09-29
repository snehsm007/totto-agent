"""Selftest: a fresh clone + the documented setup activates the pre-commit gate.

`make setup` = install deps + `make hooks`. Reinstalling deps is slow and
needs the network, so this test runs the hook-activation part (`make hooks`)
in a real temporary `git clone` and checks that `make setup` calls it. The
working-tree Makefile and hooks/ are copied over the clone so the test
covers uncommitted edits too.
"""

from __future__ import annotations

import os
from pathlib import Path
import shutil
import stat
import subprocess

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]

pytestmark = pytest.mark.skipif(shutil.which("make") is None, reason="make not installed")


def _git(cwd: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=check)


@pytest.fixture()
def clone(tmp_path: Path) -> Path:
    dest = tmp_path / "clone"
    subprocess.run(
        ["git", "clone", "--quiet", "--depth", "1", f"file://{REPO_ROOT}", str(dest)],
        check=True,
        capture_output=True,
    )
    shutil.copy2(REPO_ROOT / "Makefile", dest / "Makefile")
    shutil.rmtree(dest / "hooks")
    shutil.copytree(REPO_ROOT / "hooks", dest / "hooks")
    return dest


def test_fresh_clone_has_no_hooks_path_until_setup(clone: Path) -> None:
    res = _git(clone, "config", "--get", "core.hooksPath", check=False)
    assert res.returncode != 0 and res.stdout.strip() == ""


def test_make_hooks_activates_pre_commit_gate_in_fresh_clone(clone: Path) -> None:
    res = subprocess.run(["make", "hooks"], cwd=clone, capture_output=True, text=True)
    assert res.returncode == 0, res.stdout + res.stderr
    assert _git(clone, "config", "--get", "core.hooksPath").stdout.strip() == "hooks"
    assert "Pre-commit gate active: core.hooksPath=hooks" in res.stdout
    hook = clone / "hooks" / "pre-commit"
    assert hook.stat().st_mode & stat.S_IXUSR
    assert _git(clone, "rev-parse", "--git-path", "hooks/pre-commit").stdout.strip() == "hooks/pre-commit"


def test_make_setup_runs_the_hooks_step(clone: Path) -> None:
    # `make -n` still recurses into `$(MAKE) hooks` (dry-run), so the hook
    # activation command shows up in setup's plan; nothing is executed.
    res = subprocess.run(["make", "-n", "setup"], cwd=clone, capture_output=True, text=True)
    assert res.returncode == 0, res.stderr
    assert "git config core.hooksPath hooks" in res.stdout
    assert "pip install" in res.stdout and "-e ." in res.stdout
    assert _git(clone, "config", "--get", "core.hooksPath", check=False).returncode != 0


def test_commit_after_setup_runs_the_gate_and_blocks_on_failure(clone: Path, tmp_path: Path) -> None:
    subprocess.run(["make", "hooks"], cwd=clone, capture_output=True, check=True)
    marker = tmp_path / "gate_ran"
    fake_python = tmp_path / "fake_python"
    # Stands in for the venv python: records the gate invocation and fails it.
    fake_python.write_text(f'#!/bin/sh\necho "$@" > "{marker}"\nexit 1\n', encoding="utf-8")
    fake_python.chmod(0o755)
    (clone / "README.md").write_text("changed\n", encoding="utf-8")
    _git(clone, "add", "README.md")
    env = {**os.environ, "TOTTO_PYTHON": str(fake_python)}
    env.pop("TOTTO_SKIP_GATE", None)
    res = subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@example.invalid", "commit", "-m", "x"],
        cwd=clone,
        capture_output=True,
        text=True,
        env=env,
    )
    assert res.returncode != 0, "a failing gate must block the commit"
    assert "-m totto_suite gate" in marker.read_text(encoding="utf-8")
