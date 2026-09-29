"""Suite-wide constants and local environment config loader.

Deployment coordinates (GCP project ID, location, CXAS app UUID) are read at
runtime from gitignored local configuration (`gecx-config.json` or
`environments/dev-totto-gecx/gecx-config.json`) or environment variables:

    TOTTO_APP_NAME   full resource name projects/<p>/locations/<l>/apps/<id>
    GCP_PROJECT_ID   target GCP project ID
    CXAS_LOCATION    target CXAS region (default: us)
    CXAS_APP_ID      target CXAS application UUID
    TOTTO_APP_DIR    agent directory under test (default <repo>/cxas_app)
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import re

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_APP_DIR = REPO_ROOT / "cxas_app"
HISTORY_DIR = REPO_ROOT / "evals" / "history"
RUNS_DIR = HISTORY_DIR / "runs"
SNAPSHOTS_DIR = HISTORY_DIR / "snapshots"
ARTIFACTS_DIR = HISTORY_DIR / "artifacts"
INDEX_PATH = HISTORY_DIR / "index.json"
TREND_MD_PATH = HISTORY_DIR / "TREND.md"
TREND_HTML_PATH = HISTORY_DIR / "trend.html"


def _load_local_gecx_config() -> dict[str, str]:
    """Loads gitignored local gecx-config.json if present on disk."""
    candidates = (
        REPO_ROOT / "gecx-config.json",
        REPO_ROOT / "environments" / "dev-totto-gecx" / "gecx-config.json",
    )
    for path in candidates:
        if path.is_file():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    return {str(k): str(v) for k, v in data.items() if v is not None}
            except (OSError, ValueError):
                continue
    return {}


_LOCAL_CFG = _load_local_gecx_config()

PROJECT = (
    os.environ.get("GCP_PROJECT_ID", "").strip()
    or _LOCAL_CFG.get("gcp_project_id", "").strip()
    or "your-gcp-project"
)
LOCATION = (
    os.environ.get("CXAS_LOCATION", "").strip()
    or _LOCAL_CFG.get("location", "").strip()
    or "us"
)
APP_ID = (
    os.environ.get("CXAS_APP_ID", "").strip()
    or _LOCAL_CFG.get("app_id", "").strip()
    or _LOCAL_CFG.get("deployed_app_id", "").strip()
    or "00000000-0000-0000-0000-000000000000"
)
DEFAULT_APP_NAME = f"projects/{PROJECT}/locations/{LOCATION}/apps/{APP_ID}"
APP_DISPLAY_NAME = "totto-mercedes-f1-fan-agent"
EXPECTED_MODEL = "gemini-3.0-flash-001"

_APP_NAME_RE = re.compile(
    r"^projects/(?P<project>[^/]+)/locations/(?P<location>[^/]+)"
    r"/apps/(?P<app_id>[^/]+)$"
)

# Paths (repo-relative prefixes) whose uncommitted changes can change a test
# result. evals/history/ is output, not input, so it is excluded.
RELEVANT_PREFIXES = ("cxas_app/", "totto_suite/", "tests/", "evals/")
IRRELEVANT_PREFIXES = ("evals/history/",)


def app_name() -> str:
    """Returns the full app resource name (env TOTTO_APP_NAME overrides)."""
    name = os.environ.get("TOTTO_APP_NAME", "").strip() or DEFAULT_APP_NAME
    if not _APP_NAME_RE.match(name):
        raise ValueError(
            f"TOTTO_APP_NAME={name!r} is not projects/<p>/locations/<l>/apps/<id>"
        )
    return name


def parse_app_name(name: str) -> dict:
    """Splits a full app resource name into project, location and app_id."""
    m = _APP_NAME_RE.match(name)
    if not m:
        raise ValueError(f"not an app resource name: {name!r}")
    return m.groupdict()


def app_dir() -> Path:
    """Returns the agent directory under test (env TOTTO_APP_DIR overrides)."""
    env = os.environ.get("TOTTO_APP_DIR", "").strip()
    if not env:
        return DEFAULT_APP_DIR
    p = Path(env)
    return p if p.is_absolute() else (REPO_ROOT / p)


def repo_relative(path: Path | str) -> str:
    """Returns ``path`` relative to the repo root (posix), or absolute if outside."""
    p = Path(path).resolve()
    try:
        return p.relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return p.as_posix()
