"""In-process pytest runner that converts pytest items into TestResult dicts."""

from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
import io
import os
from pathlib import Path
import re
from typing import Any

import pytest

from totto_suite import config

_HEX_ADDR_RE = re.compile(r"0x[0-9a-fA-F]+")


def _normalize_message(msg: str, app_dir: Path, repo_root: Path) -> str:
    if not msg:
        return ""
    first_line = msg.strip().splitlines()[0].strip()
    first_line = first_line.replace(str(app_dir), "<APP_DIR>")
    first_line = first_line.replace(str(repo_root), "<REPO_ROOT>")
    first_line = _HEX_ADDR_RE.sub("0xADDR", first_line)
    return first_line


class _LayerCollector:
    """Pytest plugin collecting per-test outcomes and @pytest.mark.finding IDs."""

    def __init__(self, layer: str, layer_rel_prefix: str, app_dir: Path, repo_root: Path) -> None:
        self.layer = layer
        self.layer_rel_prefix = layer_rel_prefix.rstrip("/") + "/"
        self.app_dir = app_dir
        self.repo_root = repo_root
        self.findings_by_nodeid: dict[str, list[str]] = {}
        self.results_by_id: dict[str, dict[str, Any]] = {}

    def pytest_collection_modifyitems(
        self, session: Any, config: Any, items: list[Any]
    ) -> None:
        for item in items:
            fids: list[str] = []
            for marker in item.iter_markers("finding"):
                for arg in marker.args:
                    s = str(arg).strip()
                    if s and s not in fids:
                        fids.append(s)
            self.findings_by_nodeid[item.nodeid] = fids

    def _extract_crash_message(self, report: Any) -> str:
        longrepr = getattr(report, "longrepr", None)
        if longrepr is None:
            return ""
        reprcrash = getattr(longrepr, "reprcrash", None)
        if reprcrash is not None and getattr(reprcrash, "message", None):
            return _normalize_message(str(reprcrash.message), self.app_dir, self.repo_root)
        if isinstance(longrepr, tuple) and len(longrepr) >= 3:
            return _normalize_message(str(longrepr[2]), self.app_dir, self.repo_root)
        return _normalize_message(str(longrepr), self.app_dir, self.repo_root)

    def pytest_runtest_logreport(self, report: Any) -> None:
        if report.when != "call" and not (
            report.when in ("setup", "teardown") and (report.failed or report.skipped)
        ):
            return

        nodeid = str(report.nodeid)
        rel = nodeid
        if rel.startswith(self.layer_rel_prefix):
            rel = rel[len(self.layer_rel_prefix) :]
        test_id = f"{self.layer}::{rel}"

        if report.passed:
            status = "PASS"
            msg = ""
        elif report.skipped:
            status = "SKIPPED"
            msg = self._extract_crash_message(report)
        else:
            status = "FAIL"
            msg = self._extract_crash_message(report)

        prev = self.results_by_id.get(test_id)
        if prev is not None and prev["status"] == "FAIL":
            return

        self.results_by_id[test_id] = {
            "id": test_id,
            "layer": self.layer,
            "status": status,
            "repeat": 1,
            "duration_s": round(float(getattr(report, "duration", 0.0) or 0.0), 6),
            "message": msg,
            "findings": list(self.findings_by_nodeid.get(nodeid, [])),
            "platform_ids": {},
            "evidence": msg or None,
            "deterministic": {"passed": status != "FAIL"} if status in ("PASS", "FAIL") else None,
            "judge": None,
        }


def run_pytest_layer(ctx: dict[str, Any], layer: str, subdir: str | None = None) -> list[dict[str, Any]]:
    """Runs pytest on ``tests/<subdir or layer>`` and returns TestResult dicts."""
    repo_root = Path(ctx.get("repo_root") or config.REPO_ROOT).resolve()
    app_dir = Path(ctx.get("app_dir") or config.DEFAULT_APP_DIR).resolve()
    rel_dir = f"tests/{subdir or layer}"
    target_dir = repo_root / rel_dir
    if not target_dir.is_dir():
        return []

    prev_app_dir = os.environ.get("TOTTO_APP_DIR")
    os.environ["TOTTO_APP_DIR"] = str(app_dir)
    collector = _LayerCollector(layer=layer, layer_rel_prefix=rel_dir, app_dir=app_dir, repo_root=repo_root)
    buf = io.StringIO()
    orig_cwd = Path.cwd()
    try:
        os.chdir(repo_root)
        with redirect_stdout(buf), redirect_stderr(buf):
            code = pytest.main(
                [
                    str(target_dir),
                    "-q",
                    "--tb=short",
                    "-p",
                    "no:cacheprovider",
                    "--import-mode=importlib",
                ],
                plugins=[collector],
            )
    finally:
        os.chdir(orig_cwd)
        if prev_app_dir is None:
            os.environ.pop("TOTTO_APP_DIR", None)
        else:
            os.environ["TOTTO_APP_DIR"] = prev_app_dir

    # Exit codes 0 (all pass) and 1 (some test failures) are normal test outcomes.
    # Exit codes >= 2 indicate collection/internal/usage errors.
    if int(code) >= 2 and not collector.results_by_id:
        raise RuntimeError(f"pytest collection/internal error (code {code}) in {rel_dir}:\n{buf.getvalue()}")

    return [collector.results_by_id[k] for k in sorted(collector.results_by_id)]
