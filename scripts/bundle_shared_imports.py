#!/usr/bin/env python3
"""Marker-region bundler for Totto, Mercedes F1 Fan Agent.

Why this exists: CXAS runs every agent instruction, tool and callback as a
single self-contained file. There is no import mechanism between them, so text
or code that several of them need has to be physically copied into each file.
This script keeps those copies identical to one source of truth in `lib/`.

How it works: every copy lives between a BEGIN and an END marker line in its
target file. The bundler replaces the lines between the two markers with the
contents of the source file, and `--check` reports any copy that differs from
its source (drift) without writing anything. It is a plain text include, not a
code transformer.

Usage:
    python scripts/bundle_shared_imports.py            # sync (same as --write)
    python scripts/bundle_shared_imports.py --check    # exit 1 on any drift
    python scripts/bundle_shared_imports.py --check --app-dir /tmp/copy/cxas_app

Exit codes: 0 = in sync (or synced), 1 = drift found in --check mode,
2 = structural problem (missing file, missing or duplicate markers).
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_LIB_DIR = PROJECT_ROOT / "lib"
DEFAULT_APP_DIR = PROJECT_ROOT / "cxas_app"

AGENTS = ("totto_root_agent", "race_info_agent", "merch_support_agent", "ticketing_agent")


def _py_begin(name: str, source: str) -> str:
    return (
        f"# >>> BEGIN SHARED {name}: generated from lib/{source} by "
        "scripts/bundle_shared_imports.py. Edit the lib/ file, not this copy. <<<"
    )


def _py_end(name: str) -> str:
    return f"# >>> END SHARED {name} <<<"


@dataclass(frozen=True)
class Region:
    """One shared fragment and every file that must contain an identical copy of it."""

    name: str
    source: str  # relative to the lib dir
    targets: tuple[str, ...]  # relative to the app dir
    begin: str  # exact marker line (compared after stripping surrounding whitespace)
    end: str


REGIONS: tuple[Region, ...] = (
    # cxas lint rule I001 (error) requires a <persona> section in every instruction file,
    # including global_instruction.txt, so the same persona text must exist in five files.
    Region(
        name="persona",
        source="shared_prompts/persona.txt",
        targets=("global_instruction.txt",) + tuple(f"agents/{a}/instruction.txt" for a in AGENTS),
        begin="<persona>",
        end="</persona>",
    ),
    # Both OpenF1-backed tools need the same cached HTTP helper; tools cannot import each other.
    Region(
        name="openf1_http",
        source="shared_python/openf1_http.py",
        targets=(
            "tools/get_race_schedule/python_function/python_code.py",
            "tools/get_driver_standings/python_function/python_code.py",
        ),
        begin=_py_begin("openf1_http", "shared_python/openf1_http.py"),
        end=_py_end("openf1_http"),
    ),
    # Every agent runs its own after_model_callback file; all four are the same sanitizer.
    Region(
        name="voice_sanitizer",
        source="shared_python/voice_sanitizer.py",
        targets=tuple(
            f"agents/{a}/after_model_callbacks/voice_sanitizer/python_code.py" for a in AGENTS
        ),
        begin=_py_begin("voice_sanitizer", "shared_python/voice_sanitizer.py"),
        end=_py_end("voice_sanitizer"),
    ),
)


class BundleError(Exception):
    """A structural problem that prevents syncing (missing file or bad markers)."""


@dataclass
class Finding:
    region: str
    target: str  # display path
    kind: str  # "drift" | "error"
    detail: str

    def render(self) -> str:
        label = "DRIFT" if self.kind == "drift" else "ERROR"
        return f"[BUNDLE {label}] region '{self.region}' in {self.target}: {self.detail}"


def _display(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(PROJECT_ROOT))
    except ValueError:
        return str(path)


def source_body(region: Region, lib_dir: Path) -> list[str]:
    """Lines of the shared fragment, without leading/trailing blank lines."""
    src = lib_dir / region.source
    if not src.is_file():
        raise BundleError(f"source file {_display(src)} does not exist")
    lines = src.read_text(encoding="utf-8").splitlines()
    while lines and not lines[0].strip():
        lines.pop(0)
    while lines and not lines[-1].strip():
        lines.pop()
    if not lines:
        raise BundleError(f"source file {_display(src)} is empty")
    for marker in (region.begin, region.end):
        if any(line.strip() == marker for line in lines):
            raise BundleError(f"source file {_display(src)} must not contain the marker line {marker!r}")
    return lines


def locate(region: Region, lines: list[str]) -> tuple[int, int]:
    """Index of the BEGIN and END marker lines; raises BundleError unless exactly one of each, in order."""
    begins = [i for i, line in enumerate(lines) if line.strip() == region.begin]
    ends = [i for i, line in enumerate(lines) if line.strip() == region.end]
    if not begins or not ends:
        missing = [m for m, found in ((region.begin, begins), (region.end, ends)) if not found]
        raise BundleError("missing marker line(s): " + ", ".join(repr(m) for m in missing))
    if len(begins) > 1 or len(ends) > 1:
        raise BundleError(
            f"duplicate markers: {len(begins)} BEGIN and {len(ends)} END lines (expected exactly 1 each)"
        )
    if ends[0] < begins[0]:
        raise BundleError("END marker appears before BEGIN marker")
    return begins[0], ends[0]


def _first_difference(expected: list[str], actual: list[str]) -> str:
    for idx in range(max(len(expected), len(actual))):
        exp = expected[idx] if idx < len(expected) else "<no line>"
        act = actual[idx] if idx < len(actual) else "<no line>"
        if exp != act:
            col = next((c for c, (a, b) in enumerate(zip(exp, act)) if a != b), min(len(exp), len(act)))
            start = max(0, col - 30)
            return (
                f"first difference at region line {idx + 1}, column {col + 1}: "
                f"expected ...{exp[start : col + 50]!r}, found ...{act[start : col + 50]!r}"
            )
    return "content differs"


def process(app_dir: Path, lib_dir: Path, *, write: bool, regions: tuple[Region, ...] = REGIONS) -> list[Finding]:
    """Check (and with write=True, repair) every region copy. Returns the findings that remain."""
    findings: list[Finding] = []
    for region in regions:
        try:
            body = source_body(region, lib_dir)
        except BundleError as exc:
            findings.append(Finding(region.name, f"lib/{region.source}", "error", str(exc)))
            continue
        for rel in region.targets:
            target = app_dir / rel
            shown = _display(target)
            if not target.is_file():
                findings.append(Finding(region.name, shown, "error", "target file does not exist"))
                continue
            text = target.read_text(encoding="utf-8")
            lines = text.splitlines()
            try:
                begin, end = locate(region, lines)
            except BundleError as exc:
                findings.append(Finding(region.name, shown, "error", str(exc)))
                continue
            current = lines[begin + 1 : end]
            if current == body:
                continue
            if not write:
                findings.append(Finding(region.name, shown, "drift", _first_difference(body, current)))
                continue
            new_lines = lines[: begin + 1] + body + lines[end:]
            trailing = "\n" if text.endswith("\n") else ""
            target.write_text("\n".join(new_lines) + trailing, encoding="utf-8")
            print(f"[BUNDLE] synced region '{region.name}' into {shown}")
    return findings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Copy shared fragments from lib/ into the marker regions of cxas_app/ files."
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--check", action="store_true", help="Report drift without modifying files (exit 1 on drift).")
    mode.add_argument("--write", action="store_true", help="Sync every region (default).")
    parser.add_argument("--app-dir", type=Path, default=DEFAULT_APP_DIR, help="App directory (default: cxas_app/).")
    parser.add_argument("--lib-dir", type=Path, default=DEFAULT_LIB_DIR, help="Shared source directory (default: lib/).")
    args = parser.parse_args(argv)

    findings = process(args.app_dir.resolve(), args.lib_dir.resolve(), write=not args.check)
    for finding in findings:
        print(finding.render())
    copies = sum(len(r.targets) for r in REGIONS)
    if any(f.kind == "error" for f in findings):
        print(f"[BUNDLE] FAILED: {len(findings)} problem(s); fix the markers/files above.")
        return 2
    if findings:
        print(
            f"[BUNDLE CHECK] {len(findings)} of {copies} shared copies drifted from lib/. "
            "Run: python scripts/bundle_shared_imports.py"
        )
        return 1
    print(f"[BUNDLE] {len(REGIONS)} shared regions, {copies} copies: all in sync with lib/.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
