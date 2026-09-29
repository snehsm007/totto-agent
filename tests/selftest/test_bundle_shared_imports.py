"""Unit tests for scripts/bundle_shared_imports.py (the marker-region bundler).

Each test builds a tiny throwaway lib/ + app/ tree so the real repository is never
touched, plus one test that runs --check against the real cxas_app/.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
import shutil
import subprocess
import sys
import types

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "bundle_shared_imports.py"


def _load_bundler() -> types.ModuleType:
    spec = importlib.util.spec_from_file_location("bundle_shared_imports_under_test", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module  # dataclasses resolve string annotations via sys.modules
    spec.loader.exec_module(module)
    return module


bundler = _load_bundler()

PY_REGION = bundler.Region(
    name="helpers",
    source="shared/helpers.py",
    targets=("tools/a/code.py", "tools/b/code.py"),
    begin="# >>> BEGIN SHARED helpers <<<",
    end="# >>> END SHARED helpers <<<",
)
TAG_REGION = bundler.Region(
    name="persona",
    source="prompts/persona.txt",
    targets=("agents/x/instruction.txt",),
    begin="<persona>",
    end="</persona>",
)
REGIONS = (PY_REGION, TAG_REGION)

HELPERS_V1 = "def helper() -> int:\n    return 1\n"
PERSONA_V1 = "You are Totto.\nStay brand-safe.\n"


def _host(body: str, region: bundler.Region = PY_REGION) -> str:
    return f"import os\n\n{region.begin}\n{body}{region.end}\n\n\ndef tool():\n    return helper()\n"


@pytest.fixture
def tree(tmp_path: Path) -> tuple[Path, Path]:
    lib, app = tmp_path / "lib", tmp_path / "app"
    (lib / "shared").mkdir(parents=True)
    (lib / "prompts").mkdir(parents=True)
    (lib / "shared" / "helpers.py").write_text(HELPERS_V1, encoding="utf-8")
    (lib / "prompts" / "persona.txt").write_text(PERSONA_V1, encoding="utf-8")
    for rel in PY_REGION.targets:
        (app / rel).parent.mkdir(parents=True)
        (app / rel).write_text(_host(HELPERS_V1), encoding="utf-8")
    inst = app / TAG_REGION.targets[0]
    inst.parent.mkdir(parents=True)
    inst.write_text(f"<role>\nr\n</role>\n\n<persona>\n{PERSONA_V1}</persona>\n", encoding="utf-8")
    return app, lib


def test_in_sync_tree_reports_no_findings(tree: tuple[Path, Path]) -> None:
    app, lib = tree
    assert bundler.process(app, lib, write=False, regions=REGIONS) == []


def test_check_detects_drift_in_one_copy_and_names_file_and_region(tree: tuple[Path, Path]) -> None:
    app, lib = tree
    drifted = app / "tools" / "b" / "code.py"
    drifted.write_text(_host("def helper() -> int:\n    return 2\n"), encoding="utf-8")
    before = drifted.read_text(encoding="utf-8")

    findings = bundler.process(app, lib, write=False, regions=REGIONS)

    assert [(f.region, f.kind) for f in findings] == [("helpers", "drift")]
    assert findings[0].target.endswith("tools/b/code.py")
    assert "return 1" in findings[0].detail and "return 2" in findings[0].detail
    assert drifted.read_text(encoding="utf-8") == before, "--check must never modify files"


def test_check_detects_drift_after_the_source_changes(tree: tuple[Path, Path]) -> None:
    app, lib = tree
    (lib / "prompts" / "persona.txt").write_text("You are Totto.\nStay brand-safe and brief.\n", encoding="utf-8")
    findings = bundler.process(app, lib, write=False, regions=REGIONS)
    assert [(f.region, f.kind) for f in findings] == [("persona", "drift")]


def test_write_repairs_drift_then_check_is_clean(tree: tuple[Path, Path]) -> None:
    app, lib = tree
    new_body = "def helper() -> int:\n    return 42\n"
    (lib / "shared" / "helpers.py").write_text(new_body, encoding="utf-8")

    assert bundler.process(app, lib, write=True, regions=REGIONS) == []
    for rel in PY_REGION.targets:
        text = (app / rel).read_text(encoding="utf-8")
        assert text == _host(new_body), "only the lines between the markers may change"
    assert bundler.process(app, lib, write=False, regions=REGIONS) == []


def test_write_is_idempotent(tree: tuple[Path, Path]) -> None:
    app, lib = tree
    (app / "tools" / "a" / "code.py").write_text(_host("# stale\n"), encoding="utf-8")
    bundler.process(app, lib, write=True, regions=REGIONS)
    first = {rel: (app / rel).read_bytes() for rel in PY_REGION.targets + TAG_REGION.targets}
    bundler.process(app, lib, write=True, regions=REGIONS)
    second = {rel: (app / rel).read_bytes() for rel in PY_REGION.targets + TAG_REGION.targets}
    assert first == second


def test_empty_region_is_filled_by_write(tree: tuple[Path, Path]) -> None:
    app, lib = tree
    target = app / "tools" / "a" / "code.py"
    target.write_text(_host(""), encoding="utf-8")
    assert [f.kind for f in bundler.process(app, lib, write=False, regions=REGIONS)] == ["drift"]
    bundler.process(app, lib, write=True, regions=REGIONS)
    assert target.read_text(encoding="utf-8") == _host(HELPERS_V1)


@pytest.mark.parametrize(
    ("content", "expected"),
    [
        ("import os\n\ndef tool():\n    return 1\n", "missing marker"),
        (f"{PY_REGION.begin}\n{HELPERS_V1}\ndef tool():\n    return 1\n", "missing marker"),
        (
            f"{PY_REGION.begin}\n{HELPERS_V1}{PY_REGION.end}\n{PY_REGION.begin}\n{HELPERS_V1}{PY_REGION.end}\n",
            "duplicate markers",
        ),
        (f"{PY_REGION.end}\n{HELPERS_V1}{PY_REGION.begin}\n", "END marker appears before BEGIN"),
    ],
    ids=["no_markers", "missing_end", "duplicate_region", "end_before_begin"],
)
def test_bad_markers_are_errors_in_check_and_write_mode(
    tree: tuple[Path, Path], content: str, expected: str
) -> None:
    app, lib = tree
    target = app / "tools" / "a" / "code.py"
    target.write_text(content, encoding="utf-8")
    for write in (False, True):
        findings = bundler.process(app, lib, write=write, regions=REGIONS)
        assert [(f.region, f.kind) for f in findings] == [("helpers", "error")]
        assert expected in findings[0].detail
        assert target.read_text(encoding="utf-8") == content, "a file with bad markers must not be rewritten"


def test_missing_source_and_missing_target_are_errors(tree: tuple[Path, Path]) -> None:
    app, lib = tree
    (lib / "prompts" / "persona.txt").unlink()
    (app / "tools" / "b" / "code.py").unlink()
    findings = bundler.process(app, lib, write=False, regions=REGIONS)
    details = sorted((f.region, f.kind, f.detail) for f in findings)
    assert details == [
        ("helpers", "error", "target file does not exist"),
        ("persona", "error", f"source file {lib / 'prompts' / 'persona.txt'} does not exist"),
    ]


def test_source_containing_a_marker_line_is_rejected(tree: tuple[Path, Path]) -> None:
    app, lib = tree
    (lib / "prompts" / "persona.txt").write_text("You are Totto.\n</persona>\n", encoding="utf-8")
    findings = bundler.process(app, lib, write=True, regions=REGIONS)
    assert [(f.region, f.kind) for f in findings] == [("persona", "error")]
    assert "must not contain the marker line" in findings[0].detail


def test_real_regions_cover_every_agent_and_both_openf1_tools() -> None:
    by_name = {r.name: r for r in bundler.REGIONS}
    assert set(by_name) == {"persona", "openf1_http", "voice_sanitizer"}
    agents = ("totto_root_agent", "race_info_agent", "merch_support_agent", "ticketing_agent")
    assert set(by_name["persona"].targets) == {"global_instruction.txt"} | {
        f"agents/{a}/instruction.txt" for a in agents
    }
    assert set(by_name["openf1_http"].targets) == {
        "tools/get_race_schedule/python_function/python_code.py",
        "tools/get_driver_standings/python_function/python_code.py",
    }
    assert len(by_name["voice_sanitizer"].targets) == 4


def _run_cli(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args], cwd=str(REPO_ROOT), capture_output=True, text=True, check=False
    )


def test_cli_check_passes_on_repo_and_fails_with_exit_1_on_drifted_copy(tmp_path: Path) -> None:
    ok = _run_cli("--check")
    assert ok.returncode == 0, ok.stdout + ok.stderr
    assert "all in sync" in ok.stdout


    app_copy = tmp_path / "cxas_app"
    shutil.copytree(REPO_ROOT / "cxas_app", app_copy, ignore=shutil.ignore_patterns("__pycache__"))
    inst = app_copy / "agents" / "race_info_agent" / "instruction.txt"
    inst.write_text(
        inst.read_text(encoding="utf-8").replace("George Russell in car 63", "**George Russell** in car 63", 1),
        encoding="utf-8",
    )
    drift = _run_cli("--check", "--app-dir", str(app_copy))
    assert drift.returncode == 1, drift.stdout + drift.stderr
    assert "[BUNDLE DRIFT] region 'persona'" in drift.stdout
    assert "race_info_agent/instruction.txt" in drift.stdout

    fixed = _run_cli("--write", "--app-dir", str(app_copy))
    assert fixed.returncode == 0, fixed.stdout + fixed.stderr
    assert _run_cli("--check", "--app-dir", str(app_copy)).returncode == 0


def test_cli_exits_2_on_structural_error(tmp_path: Path) -> None:

    app_copy = tmp_path / "cxas_app"
    shutil.copytree(REPO_ROOT / "cxas_app", app_copy, ignore=shutil.ignore_patterns("__pycache__"))
    tool = app_copy / "tools" / "get_driver_standings" / "python_function" / "python_code.py"
    tool.write_text(
        "\n".join(l for l in tool.read_text(encoding="utf-8").splitlines() if "END SHARED openf1_http" not in l),
        encoding="utf-8",
    )
    res = _run_cli("--check", "--app-dir", str(app_copy))
    assert res.returncode == 2, res.stdout + res.stderr
    assert "[BUNDLE ERROR] region 'openf1_http'" in res.stdout and "missing marker" in res.stdout
