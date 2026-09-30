"""Canonical golden evaluation definitions loaded from ``evals/goldens/goldens.yaml``."""

from __future__ import annotations

from pathlib import Path
from typing import Any
import yaml

from totto_suite.config import REPO_ROOT

GOLDENS_YAML: Path = REPO_ROOT / "evals" / "goldens" / "goldens.yaml"


def load_golden_definitions(path: Path = GOLDENS_YAML) -> dict[str, Any]:
    """Loads the raw canonical golden evaluation YAML dictionary."""
    return yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
