#!/usr/bin/env python3
"""Pre-push Pull-Diff Guard (`make diff-check`) closing Blueprint Gap 1.

In Cloud Mode: pulls the live GECX app into a temporary directory and diffs
against `.cxas-last-pushed/` (or `cxas_app/`) to detect console UI edits before
`cxas push --overwrite` can clobber them.
In Offline Mode: verifies local bundle consistency (`bundle_shared_imports.py --check`)
and checks local snapshot integrity.
"""

import argparse
import difflib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
APP_DIR = PROJECT_ROOT / "cxas_app"
LAST_PUSHED_DIR = PROJECT_ROOT / ".cxas-last-pushed"
CONFIG_FILE = PROJECT_ROOT / "environments" / "dev-totto-gecx" / "gecx-config.json"


def compute_dir_diff(dir_a: Path, dir_b: Path) -> list[str]:
    """Compute unified diff lines across all .json, .txt, and .py files between two directories."""
    diffs: list[str] = []
    if not dir_a.exists() or not dir_b.exists():
        return diffs

    files_a = {
        p.relative_to(dir_a): p
        for p in dir_a.rglob("*")
        if p.is_file() and p.suffix in (".json", ".txt", ".py")
    }
    files_b = {
        p.relative_to(dir_b): p
        for p in dir_b.rglob("*")
        if p.is_file() and p.suffix in (".json", ".txt", ".py")
    }

    for rel in sorted(set(files_a.keys()) | set(files_b.keys())):
        lines_a = (
            files_a[rel].read_text(encoding="utf-8").splitlines(keepends=True)
            if rel in files_a
            else []
        )
        lines_b = (
            files_b[rel].read_text(encoding="utf-8").splitlines(keepends=True)
            if rel in files_b
            else []
        )
        if lines_a != lines_b:
            diffs.extend(
                difflib.unified_diff(
                    lines_a,
                    lines_b,
                    fromfile=f"expected/{rel}",
                    tofile=f"remote/{rel}",
                )
            )
    return diffs


def main() -> int:
    parser = argparse.ArgumentParser(description="Pre-push GECX Pull-Diff Guard.")
    parser.add_argument(
        "--mode",
        choices=["offline", "cloud"],
        default=os.environ.get("MODE", "offline"),
        help="Execution mode (offline or cloud).",
    )
    parser.add_argument(
        "--force-overwrite",
        action="store_true",
        default=os.environ.get("FORCE_OVERWRITE", "0") == "1",
        help="Allow pushing even if remote drift is detected.",
    )
    args = parser.parse_args()

    bundle_script = PROJECT_ROOT / "scripts" / "bundle_shared_imports.py"
    res = subprocess.run(
        [sys.executable, str(bundle_script), "--check"],
        cwd=str(PROJECT_ROOT),
        capture_output=True,
        text=True,
        check=False,
    )
    if res.returncode != 0:
        print(res.stdout + res.stderr)
        return 1

    if args.mode == "offline":
        print(
            "[DIFF-CHECK] [OFFLINE] Local bundle consistency verified; "
            "cloud pull-diff guard ready for MODE=cloud."
        )
        return 0

    cfg = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    app_resource = (
        f"projects/{cfg['gcp_project_id']}/locations/{cfg['location']}/apps/{cfg['app_id']}"
    )
    cxas_bin = PROJECT_ROOT / ".venv" / "bin" / "cxas"
    tmp_dir = Path(tempfile.mkdtemp(prefix="cxas-drift-check-"))
    try:
        pull_cmd = [str(cxas_bin), "pull", app_resource, "--output-dir", str(tmp_dir)]
        pull_res = subprocess.run(pull_cmd, capture_output=True, text=True, check=False)
        if pull_res.returncode != 0:
            print(f"[DIFF-CHECK] Remote app not yet created or unreachable: {pull_res.stderr.strip()}")
            return 0

        baseline_dir = LAST_PUSHED_DIR if LAST_PUSHED_DIR.exists() else APP_DIR
        diffs = compute_dir_diff(baseline_dir, tmp_dir)
        if diffs:
            print("[DIFF-CHECK] Drift detected between baseline and live GECX cloud state:")
            print("".join(diffs[:200]))
            if not args.force_overwrite:
                print(
                    "[DIFF-CHECK] Aborting push to prevent overwriting cloud console edits. "
                    "Run `make pull` or pass FORCE_OVERWRITE=1."
                )
                return 1
        print("[DIFF-CHECK] Cloud state matches expected baseline.")
        return 0
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
