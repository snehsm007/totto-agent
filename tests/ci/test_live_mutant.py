"""The live-only mutant (red-run demo) still applies to the current agent.

Full offline-invisibility is proven with
`scripts/ci/apply_live_mutant.sh race_schedule_blackout --check-offline`
(runs the whole offline suite, ~15-30 s, so it is not repeated here).
These fast checks catch drift: prompt edits elsewhere must not stop the
patch from applying, and it must only add text.
"""

from __future__ import annotations

from pathlib import Path
import shutil
import subprocess

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "ci" / "apply_live_mutant.sh"
PATCH = REPO_ROOT / "evals" / "mutants" / "live" / "race_schedule_blackout.patch"
TARGET = "cxas_app/agents/race_info_agent/instruction.txt"


def test_patch_only_adds_lines_to_race_info_instruction() -> None:
    lines = PATCH.read_text(encoding="utf-8").splitlines()
    assert lines[0] == f"--- a/{TARGET}" and lines[1] == f"+++ b/{TARGET}"
    body = lines[2:]
    assert not [l for l in body if l.startswith("-")], "mutant must not delete agent text"
    added = "\n".join(l[1:] for l in body if l.startswith("+"))
    assert "NEVER call {@TOOL: get_race_schedule}" in added
    assert "unavailable" in added


def test_apply_to_copy_appends_mutation_and_keeps_original_text(tmp_path: Path) -> None:
    shutil.copytree(REPO_ROOT / "cxas_app", tmp_path / "cxas_app")
    original = (REPO_ROOT / TARGET).read_text(encoding="utf-8")
    res = subprocess.run(
        ["bash", str(SCRIPT), "race_schedule_blackout", "--apply-to", str(tmp_path)],
        capture_output=True,
        text=True,
    )
    assert res.returncode == 0, res.stdout + res.stderr
    mutated = (tmp_path / TARGET).read_text(encoding="utf-8")
    assert mutated.startswith(original)
    assert "<live_mutant_schedule_blackout>" in mutated[len(original):]
    # The repo copy is untouched.
    assert (REPO_ROOT / TARGET).read_text(encoding="utf-8") == original


def test_unknown_mutant_is_rejected_with_list() -> None:
    res = subprocess.run(["bash", str(SCRIPT), "nope"], capture_output=True, text=True)
    assert res.returncode == 2
    assert "race_schedule_blackout" in res.stderr


@pytest.mark.parametrize("args", [["--list"]])
def test_list_shows_available_mutants(args) -> None:
    res = subprocess.run(["bash", str(SCRIPT), *args], capture_output=True, text=True)
    assert res.returncode == 0 and "race_schedule_blackout" in res.stdout.split()
