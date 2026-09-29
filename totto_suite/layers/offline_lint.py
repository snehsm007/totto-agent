"""Offline layer: lint (cxas lint + bundle_shared_imports --check)."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import time
from typing import Any

from totto_suite import config


def run(ctx: dict[str, Any]) -> list[dict[str, Any]]:
    repo_root = Path(ctx.get("repo_root") or config.REPO_ROOT).resolve()
    app_dir = Path(ctx.get("app_dir") or config.DEFAULT_APP_DIR).resolve()
    cxas_bin = repo_root / ".venv" / "bin" / "cxas"
    if not cxas_bin.is_file():
        cxas_bin = Path(sys.executable).parent / "cxas"

    results: list[dict[str, Any]] = []

    # 1. cxas lint --app-dir <app_dir> --json
    t0 = time.monotonic()
    proc = subprocess.run(
        [str(cxas_bin), "lint", "--app-dir", str(app_dir), "--json"],
        cwd=str(repo_root),
        capture_output=True,
        text=True,
        check=False,
    )
    dur = round(time.monotonic() - t0, 6)
    issues = []
    try:
        parsed = json.loads(proc.stdout.strip() or "[]")
        if isinstance(parsed, list):
            issues = parsed
    except json.JSONDecodeError:
        issues = [{"rule": "PARSE_ERROR", "message": (proc.stderr or proc.stdout).strip()[:200]}]

    passed = proc.returncode == 0 and len(issues) == 0
    msg = ""
    if not passed:
        summaries = [
            f"{i.get('rule_id') or i.get('rule') or 'LINT'}: {i.get('message', '')}"
            for i in issues[:5]
        ]
        msg = "; ".join(summaries) or f"cxas lint exited with code {proc.returncode}"
        msg = msg.replace(str(app_dir), "<APP_DIR>").replace(str(repo_root), "<REPO_ROOT>")

    results.append(
        {
            "id": "lint::cxas_lint",
            "layer": "lint",
            "status": "PASS" if passed else "FAIL",
            "repeat": 1,
            "duration_s": dur,
            "message": msg,
            "findings": ["TR-01", "TR-02", "TR-05"],
            "platform_ids": {},
            "evidence": msg or None,
            "deterministic": {"passed": passed, "issue_count": len(issues)},
            "judge": None,
        }
    )

    # 2. scripts/bundle_shared_imports.py --check
    t1 = time.monotonic()
    bproc = subprocess.run(
        [sys.executable, str(repo_root / "scripts" / "bundle_shared_imports.py"), "--check"],
        cwd=str(repo_root),
        capture_output=True,
        text=True,
        check=False,
    )
    bdur = round(time.monotonic() - t1, 6)
    bpassed = bproc.returncode == 0
    bmsg = "" if bpassed else (bproc.stdout.strip() or bproc.stderr.strip()).splitlines()[0]
    results.append(
        {
            "id": "lint::bundle_shared_imports",
            "layer": "lint",
            "status": "PASS" if bpassed else "FAIL",
            "repeat": 1,
            "duration_s": bdur,
            "message": bmsg,
            "findings": [],
            "platform_ids": {},
            "evidence": bmsg or None,
            "deterministic": {"passed": bpassed},
            "judge": None,
        }
    )
    return results
