"""Identifier scrubbing and leak checks for the public dashboard.

The dashboard is public, so it must never contain project IDs, app IDs or
personal identifiers. Two steps:

1. ``relativize`` (scrub): every string in the inputs that contains a full
   CXAS resource name ``projects/<p>/locations/<l>/apps/<a>/<rest>`` is
   rewritten to the app-relative ``<rest>`` (``evaluationRuns/<uuid>`` etc.).
2. ``find_leaks`` / ``check_tree`` (validation): the rendered output is
   scanned; any remaining email address, ``projects/<real id>/locations/``,
   ``apps/<uuid>`` (other than the all-zero placeholder) or deny-listed
   literal is a hard failure. Findings are masked so a public CI log never
   repeats the identifier.

Deny-listed literals come from ``$DASHBOARD_DENY`` (comma separated; CI passes
the app IDs from repo variables) plus, on a developer machine, the project
and app IDs found in the gitignored local config.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

_UUID = r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
_SEG = r"[^/\s\"'<>]+"

# projects/<p>/locations/<l>/apps/<a>[/<rest>]
_FULL_APP_NAME_RE = re.compile(
    rf"projects/{_SEG}/locations/{_SEG}/apps/{_SEG}(?:/(?P<rest>[^\s\"'<>,;)]+))?"
)
# projects/<p>/locations/<l>/<rest> (operations etc., not under an app)
_FULL_LOCATION_NAME_RE = re.compile(
    rf"projects/{_SEG}/locations/{_SEG}/(?P<rest>[^\s\"'<>,;)]+)"
)

EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}")
PROJECT_RE = re.compile(r"projects/([^/\s\"']+)/locations/")
APP_UUID_RE = re.compile(rf"apps/({_UUID})")

ZERO_UUID = "00000000-0000-0000-0000-000000000000"
_PLACEHOLDER_PROJECT_RE = re.compile(
    r"^(?:your-gcp-project|your-project(?:-id)?|example-project|my-project"
    r"|PROJECT_ID|PROJECT|project|-|\*"
    r"|<[^>]*>|&lt;.*?&gt;|\{[^}]*\}|\$\{?[A-Za-z_]+\}?)$"
)
_MIN_DENY_LEN = 6
TEXT_SUFFIXES = {".html", ".htm", ".json", ".md", ".txt", ".svg", ".csv", ".css", ".js", ""}


class LeakError(Exception):
    """Raised when rendered output still contains an identifier."""

    def __init__(self, findings: list["Finding"]):
        self.findings = findings
        lines = [f"  {f}" for f in findings[:50]]
        more = f"\n  ... and {len(findings) - 50} more" if len(findings) > 50 else ""
        super().__init__(
            f"identifier check FAILED ({len(findings)} finding(s)):\n" + "\n".join(lines) + more
        )


@dataclass(frozen=True)
class Finding:
    kind: str
    where: str
    line: int
    masked: str

    def __str__(self) -> str:
        return f"{self.where}:{self.line}: {self.kind}: {self.masked}"


def mask(value: str) -> str:
    """Masks an identifier so logs never repeat it: 'abc…(12 chars)'."""
    if "@" in value:
        return f"***@*** ({len(value)} chars)"
    return f"{value[:3]}… ({len(value)} chars)"


def _relativize_str(s: str) -> str:
    if "projects/" not in s:
        return s
    s = _FULL_APP_NAME_RE.sub(lambda m: m.group("rest") or "(app)", s)
    return _FULL_LOCATION_NAME_RE.sub(lambda m: m.group("rest"), s)


def relativize(value: Any) -> Any:
    """Returns a copy of a JSON-like value with full resource names made
    app-relative in every string (keys included)."""
    if isinstance(value, str):
        return _relativize_str(value)
    if isinstance(value, list):
        return [relativize(v) for v in value]
    if isinstance(value, tuple):
        return tuple(relativize(v) for v in value)
    if isinstance(value, dict):
        return {relativize(k) if isinstance(k, str) else k: relativize(v) for k, v in value.items()}
    return value


def _is_placeholder_project(pid: str) -> bool:
    return bool(_PLACEHOLDER_PROJECT_RE.match(pid))


def default_deny_list(env: dict[str, str] | None = None) -> list[str]:
    """Literals that must never appear: $DASHBOARD_DENY plus local config IDs."""
    env = os.environ if env is None else env
    deny = [x.strip() for x in env.get("DASHBOARD_DENY", "").split(",")]
    try:
        from totto_suite import config  # local gitignored config, if any

        local = getattr(config, "_LOCAL_CFG", {}) or {}
        deny += [config.PROJECT, config.APP_ID]
        deny += [str(v) for k, v in local.items() if k.endswith("app_id") or k.endswith("project_id")]
    except Exception:  # pragma: no cover - config import problems must not hide leaks
        pass
    out = []
    for d in deny:
        if len(d) < _MIN_DENY_LEN or d == ZERO_UUID or _is_placeholder_project(d):
            continue
        if d not in out:
            out.append(d)
    return out


def find_leaks(text: str, where: str = "<text>", deny: list[str] | None = None) -> list[Finding]:
    """All identifier findings in ``text`` (masked)."""
    findings: list[Finding] = []

    def line_of(pos: int) -> int:
        return text.count("\n", 0, pos) + 1

    for m in EMAIL_RE.finditer(text):
        findings.append(Finding("email address", where, line_of(m.start()), mask(m.group(0))))
    for m in PROJECT_RE.finditer(text):
        pid = m.group(1)
        if not _is_placeholder_project(pid):
            findings.append(
                Finding("project id in resource name", where, line_of(m.start()), mask(pid))
            )
    for m in APP_UUID_RE.finditer(text):
        if m.group(1) != ZERO_UUID:
            findings.append(
                Finding("app id in full resource name", where, line_of(m.start()), mask(m.group(1)))
            )
    for lit in deny or []:
        start = 0
        while (pos := text.find(lit, start)) != -1:
            findings.append(Finding("deny-listed identifier", where, line_of(pos), mask(lit)))
            start = pos + len(lit)
    return findings


def check_tree(root: Path, deny: list[str] | None = None) -> list[Finding]:
    """Scans every text file under ``root`` (skipping .git)."""
    root = Path(root)
    deny = default_deny_list() if deny is None else deny
    findings: list[Finding] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file() or ".git" in path.relative_to(root).parts:
            continue
        if path.suffix.lower() not in TEXT_SUFFIXES:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        findings += find_leaks(text, str(path.relative_to(root)), deny)
    return findings


def assert_clean(root: Path, deny: list[str] | None = None) -> None:
    findings = check_tree(root, deny)
    if findings:
        raise LeakError(findings)
