"""Layer discovery and execution.

A *layer module* is a file inside this package named ``offline_<name>.py`` or
``live_<name>.py`` that exposes::

    def run(ctx: dict) -> list[dict]: ...

Each returned dict is a TestResult (plan.md §4.1)::

    {"id": "<layer>::<stable name>", "layer": "<layer>",
     "status": "PASS|FAIL|INFRA_ERROR|SKIPPED", "repeat": 1,
     "duration_s": float, "message": str, "findings": [...],
     "platform_ids": {...}, "evidence": str|None,
     "deterministic": {...}|None, "judge": {...}|None}

One module may report results for several layers (the ``layer`` field of each
result decides which layer it is scored under, not the module name).

``ctx`` keys (plan.md §4.2): ``repo_root``, ``app_dir`` (agent under test),
``mode``, ``run_id``, ``artifacts_dir``, ``repeats``, ``now`` (optional ISO
override), ``app_name``. Offline modules must make no cloud/network calls and
must be deterministic.

Discovery is purely name based and sorted, so the execution order is stable.
"""

from __future__ import annotations

import dataclasses
import importlib
import re
import time
import traceback
from pathlib import Path
from typing import Any, Callable

KINDS = ("offline", "live")

# Matches e.g. offline_tools.py, live_sims.py (lowercase identifiers only).
_MODULE_RE = re.compile(r"^(offline|live)_([a-z0-9][a-z0-9_]*)\.py$")

REQUIRED_RESULT_KEYS = ("id", "layer", "status")
VALID_STATUSES = ("PASS", "FAIL", "INFRA_ERROR", "SKIPPED")


class LayerContractError(Exception):
    """A layer module violated the layer contract (suite bug, not agent bug)."""


@dataclasses.dataclass(frozen=True)
class LayerModule:
    """A discovered (not yet imported) layer module."""

    kind: str  # "offline" | "live"
    name: str  # module name without the kind prefix, e.g. "lint"
    module: str  # importable name, e.g. "totto_suite.layers.offline_lint"
    path: Path

    def load_run(self) -> Callable[[dict], list]:
        mod = importlib.import_module(self.module)
        run = getattr(mod, "run", None)
        if not callable(run):
            raise LayerContractError(
                f"{self.module} ({self.path}) does not define a callable run(ctx)"
            )
        return run


@dataclasses.dataclass
class LayerOutcome:
    """Result of running one layer module."""

    layer: LayerModule
    results: list[dict]
    duration_s: float
    crashed: bool = False
    error: str | None = None  # traceback text if crashed


def discover(
    kind: str,
    directory: Path | None = None,
    package: str = __name__,
) -> list[LayerModule]:
    """Returns the layer modules of ``kind`` in ``directory``, sorted by name.

    ``directory`` defaults to this package's directory and ``package`` is the
    importable package name of ``directory`` (tests point both at a temporary
    package so no fake module ever lives in the real package).
    """
    if kind not in KINDS:
        raise ValueError(f"unknown layer kind {kind!r}; expected one of {KINDS}")
    directory = Path(directory) if directory else Path(__file__).resolve().parent
    found = []
    for path in sorted(directory.iterdir(), key=lambda p: p.name):
        if not path.is_file():
            continue
        m = _MODULE_RE.match(path.name)
        if not m or m.group(1) != kind:
            continue
        found.append(
            LayerModule(
                kind=kind,
                name=m.group(2),
                module=f"{package}.{path.stem}",
                path=path,
            )
        )
    return found


def validate_results(layer: LayerModule, results: Any) -> list[dict]:
    """Checks the TestResult contract and fills optional keys with defaults.

    Raises LayerContractError on violations: a malformed result is a suite bug
    and must never be silently scored.
    """
    if not isinstance(results, list):
        raise LayerContractError(
            f"{layer.module}.run() returned {type(results).__name__}, not list"
        )
    seen = set()
    out = []
    for i, r in enumerate(results):
        if not isinstance(r, dict):
            raise LayerContractError(
                f"{layer.module}.run() result #{i} is {type(r).__name__}, not dict"
            )
        missing = [k for k in REQUIRED_RESULT_KEYS if k not in r]
        if missing:
            raise LayerContractError(
                f"{layer.module}.run() result #{i} misses keys {missing}: {r!r:.200}"
            )
        if r["status"] not in VALID_STATUSES:
            raise LayerContractError(
                f"{layer.module}.run() result {r['id']!r} has invalid status"
                f" {r['status']!r}; expected one of {VALID_STATUSES}"
            )
        if not str(r["id"]).startswith(f"{r['layer']}::"):
            raise LayerContractError(
                f"{layer.module}.run() result id {r['id']!r} must start with"
                f" '{r['layer']}::'"
            )
        full = {
            "repeat": 1,
            "duration_s": 0.0,
            "message": "",
            "findings": [],
            "platform_ids": {},
            "evidence": None,
            "deterministic": None,
            "judge": None,
        }
        full.update(r)
        key = (full["id"], full["repeat"])
        if key in seen:
            raise LayerContractError(
                f"{layer.module}.run() returned duplicate (id, repeat) {key!r}"
            )
        seen.add(key)
        out.append(full)
    return out


def run_layer(layer: LayerModule, ctx: dict) -> LayerOutcome:
    """Imports and runs one layer module; never raises.

    An exception escaping ``run()`` (or a contract violation) marks the outcome
    as crashed. The caller decides what that means (the CLI exits 2: a suite
    crash is neither an agent PASS nor an agent FAIL).
    """
    start = time.monotonic()
    try:
        run = layer.load_run()
        results = validate_results(layer, run(dict(ctx)))
    except Exception:  # pylint: disable=broad-except
        return LayerOutcome(
            layer=layer,
            results=[],
            duration_s=time.monotonic() - start,
            crashed=True,
            error=traceback.format_exc(),
        )
    return LayerOutcome(
        layer=layer, results=results, duration_s=time.monotonic() - start
    )
