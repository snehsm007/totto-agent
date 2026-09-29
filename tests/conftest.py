"""Hermetic pytest harness for the offline Totto agent tests.

Every test in ``tests/<layer>/`` runs against the agent in ``$TOTTO_APP_DIR``
(default ``<repo>/cxas_app``), so the same tests run unchanged on mutants, old
commits and exported snapshots.

What this file guarantees for every test (autouse):
  * No network: ``urllib.request.urlopen``, ``socket.create_connection`` and
    ``socket.socket.connect``/``connect_ex`` (non-AF_UNIX) raise. The tools
    under test catch the urlopen error and use their built-in snapshot, which
    is exactly what the agent does inside CXAS (finding TB-1).
  * No cross-test state: the tools' process-wide cache
    ``sys._totto_openf1_cache`` is removed before and after each test.

Helpers (fixtures):
  * ``load_tool(name, now=DEFAULT_NOW)`` imports ``tools/<name>/python_function/
    python_code.py`` fresh under a unique module name and freezes its clock.
  * ``load_callback(agent, hook_dir, name)`` imports a callback fresh.
  * ``serve_openf1(faults=...)`` replaces urlopen with a fake OpenF1 server
    that serves the captured payloads in ``tests/fixtures/openf1/`` (or
    injects faults) and records every request and its timeout.
  * ``openf1_calendar`` / ``openf1_json`` give tests the captured payloads for
    computing expectations independently of the tool under test.
"""

from __future__ import annotations

import datetime as _dt
import importlib.util
import io
import itertools
import json
import os
import socket
import sys
import types
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Callable

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
FIXTURE_DIR = REPO_ROOT / "tests" / "fixtures" / "openf1"
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

# "Today" for tests that do not choose their own date: the day this suite was
# written. Date-dependent expectations are always computed from the fixture
# calendar at the frozen instant, never hard-coded.
DEFAULT_NOW = _dt.datetime(2026, 9, 28, 12, 0, tzinfo=_dt.timezone.utc)

_CACHE_ATTR = "_totto_openf1_cache"
_module_counter = itertools.count()


def agent_app_dir() -> Path:
    """The agent under test: $TOTTO_APP_DIR or <repo>/cxas_app."""
    return Path(os.environ.get("TOTTO_APP_DIR") or REPO_ROOT / "cxas_app").resolve()


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line(
        "markers",
        "finding(*ids): finding IDs (TR-xx, TB-x, RC-xx, NEW-x, PRD-ACx) a test covers",
    )


def pytest_report_header(config: pytest.Config) -> str:
    return f"totto agent under test (TOTTO_APP_DIR): {agent_app_dir()}"


class NetworkBlockedError(urllib.error.URLError):
    """Raised for any network access attempted by an offline test."""


def _clear_cache() -> None:
    if hasattr(sys, _CACHE_ATTR):
        delattr(sys, _CACHE_ATTR)


@pytest.fixture(autouse=True)
def _hermetic(monkeypatch: pytest.MonkeyPatch):
    """Blocks all network access and resets the tools' process-wide cache."""

    def blocked_urlopen(url, *args, **kwargs):
        target = getattr(url, "full_url", url)
        raise NetworkBlockedError(f"network disabled in offline tests: {target}")

    real_connect = socket.socket.connect
    real_connect_ex = socket.socket.connect_ex

    def blocked_connect(self, address, *args, **kwargs):
        if getattr(self, "family", None) == getattr(socket, "AF_UNIX", object()):
            return real_connect(self, address, *args, **kwargs)
        raise OSError(f"network disabled in offline tests: connect({address!r})")

    def blocked_connect_ex(self, address, *args, **kwargs):
        if getattr(self, "family", None) == getattr(socket, "AF_UNIX", object()):
            return real_connect_ex(self, address, *args, **kwargs)
        raise OSError(f"network disabled in offline tests: connect_ex({address!r})")

    def blocked_create_connection(address, *args, **kwargs):
        raise OSError(f"network disabled in offline tests: create_connection({address!r})")

    monkeypatch.setattr(urllib.request, "urlopen", blocked_urlopen)
    monkeypatch.setattr(socket.socket, "connect", blocked_connect)
    monkeypatch.setattr(socket.socket, "connect_ex", blocked_connect_ex)
    monkeypatch.setattr(socket, "create_connection", blocked_create_connection)
    _clear_cache()
    yield
    _clear_cache()


# --------------------------------------------------------------------------
# Agent loading (fresh module per load, unique name, never in sys.modules).
# --------------------------------------------------------------------------


def load_agent_module(rel_path: str, extra_globals: dict[str, Any] | None = None) -> types.ModuleType:
    path = agent_app_dir() / rel_path
    if not path.is_file():
        raise FileNotFoundError(f"agent file missing in TOTTO_APP_DIR: {path}")
    name = f"totto_under_test_{next(_module_counter)}_{path.parent.name}_{path.stem}"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    for key, value in (extra_globals or {}).items():
        module.__dict__[key] = value
    spec.loader.exec_module(module)
    return module


def make_frozen_datetime(instant: _dt.datetime) -> type:
    if instant.tzinfo is None:
        raise ValueError("frozen instant must be timezone-aware")

    class FrozenDateTime(_dt.datetime):
        """datetime whose now()/utcnow()/today() return a fixed instant."""

        @classmethod
        def now(cls, tz=None):  # noqa: D102
            if tz is None:
                return instant.astimezone().replace(tzinfo=None)
            return instant.astimezone(tz)

        @classmethod
        def utcnow(cls):  # noqa: D102
            return instant.astimezone(_dt.timezone.utc).replace(tzinfo=None)

        @classmethod
        def today(cls):  # noqa: D102
            return cls.now()

    FrozenDateTime.__name__ = "datetime"
    FrozenDateTime.__qualname__ = "datetime"
    return FrozenDateTime


def freeze_clock(module_or_fn: Any, instant: _dt.datetime) -> None:
    """Swaps the module-level ``datetime`` seam of a loaded agent module.

    Handles both ``from datetime import datetime`` (class global) and
    ``import datetime`` (module global). Raises if the module has no seam that
    could be frozen, because an unfrozen clock would make tests date-dependent.
    """
    namespace = module_or_fn.__globals__ if callable(module_or_fn) and hasattr(module_or_fn, "__globals__") else module_or_fn.__dict__
    frozen = make_frozen_datetime(instant)
    replaced = False
    for key, value in list(namespace.items()):
        if value is _dt.datetime or (isinstance(value, type) and value.__name__ == "datetime" and issubclass(value, _dt.datetime)):
            namespace[key] = frozen
            replaced = True
        elif isinstance(value, types.ModuleType) and getattr(value, "__name__", "") == "datetime":
            proxy = types.ModuleType("datetime")
            proxy.__dict__.update(_dt.__dict__)
            proxy.datetime = frozen
            namespace[key] = proxy
            replaced = True
    namespace["__totto_frozen_now__"] = instant
    namespace["__totto_clock_seam_found__"] = replaced


@pytest.fixture
def load_tool() -> Callable[..., Callable[..., dict]]:
    """Returns ``_load(name, now=DEFAULT_NOW)`` -> the tool function (fresh module, frozen clock)."""

    def _load(name: str, now: _dt.datetime | None = DEFAULT_NOW) -> Callable[..., dict]:
        module = load_agent_module(f"tools/{name}/python_function/python_code.py")
        fn = getattr(module, name)
        if now is not None:
            freeze_clock(module, now)
        return fn

    return _load


@pytest.fixture
def load_tool_module() -> Callable[..., types.ModuleType]:
    def _load(name: str) -> types.ModuleType:
        return load_agent_module(f"tools/{name}/python_function/python_code.py")

    return _load


@pytest.fixture
def load_callback() -> Callable[..., types.ModuleType]:
    """Returns ``_load(agent, hook_dir, name)`` -> fresh callback module.

    CXAS injects ``CallbackContext``/``Tool``/``Content`` into the callback's
    globals; plain ``object`` stand-ins are enough for annotations.
    """

    def _load(agent: str, hook_dir: str, name: str) -> types.ModuleType:
        return load_agent_module(
            f"agents/{agent}/{hook_dir}/{name}/python_code.py",
            extra_globals={"CallbackContext": object, "Tool": object, "Content": object},
        )

    return _load


# --------------------------------------------------------------------------
# OpenF1 fixtures and fake server.
# --------------------------------------------------------------------------


def openf1_payload(stem: str) -> Any:
    return json.loads((FIXTURE_DIR / f"{stem}.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="session")
def openf1_json() -> Callable[[str], Any]:
    return openf1_payload


@pytest.fixture(scope="session")
def openf1_calendar() -> dict[str, list[dict]]:
    return {"meetings": openf1_payload("meetings_2026"), "sessions": openf1_payload("sessions_2026")}


def _fixture_for_endpoint(path: str, query: dict[str, list[str]]) -> Path | None:
    """Maps an OpenF1 request to a captured payload file (None = no data)."""
    q = {k: v[0] for k, v in query.items()}
    simple = {
        ("meetings", "year", "2026"): "meetings_2026",
        ("sessions", "year", "2026"): "sessions_2026",
        ("championship_drivers", "session_key", "latest"): "championship_drivers_latest",
        ("championship_teams", "session_key", "latest"): "championship_teams_latest",
        ("drivers", "session_key", "latest"): "drivers_latest",
    }
    if len(q) == 1:
        (k, v), = q.items()
        stem = simple.get((path, k, v))
        if stem:
            return FIXTURE_DIR / f"{stem}.json"
        if path == "weather":
            # Captured weather is per race session; a meeting_key query is served
            # with that meeting's race-session readings (a subset of the real
            # meeting payload whose last reading is the race's last reading).
            pattern = f"weather_meeting_{v}_race_session_*.json" if k == "meeting_key" else f"weather_meeting_*_race_session_{v}.json"
            matches = sorted(FIXTURE_DIR.glob(pattern)) if k in ("meeting_key", "session_key") else []
            if matches:
                return matches[0]
    return None


class _FakeResponse(io.BytesIO):
    def __init__(self, body: bytes, status: int = 200, url: str = ""):
        super().__init__(body)
        self.status = status
        self.code = status
        self.url = url

    def getcode(self) -> int:
        return self.status

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
        return False


class FakeOpenF1:
    """In-process stand-in for api.openf1.org.

    ``faults`` maps an endpoint name (``meetings``, ``sessions``, ``weather``,
    ``championship_teams``, ..., or ``*`` for all) to one of:
      timeout | http500 | http429 | malformed | empty | non_list | hang | slow
    ``hang``: the request blocks until its timeout expires (simulated, no sleep)
    and then raises ``socket.timeout``; ``slow``: the response arrives just
    before the timeout. ``virtual_elapsed_s`` accumulates simulated wall time.
    """

    def __init__(self, faults: dict[str, str] | None = None):
        self.faults = dict(faults or {})
        self.calls: list[dict[str, Any]] = []
        self.virtual_elapsed_s = 0.0

    def __call__(self, url, data=None, timeout=None, *args, **kwargs):
        full_url = getattr(url, "full_url", url)
        parsed = urllib.parse.urlparse(str(full_url))
        path = parsed.path.rsplit("/", 1)[-1]
        query = urllib.parse.parse_qs(parsed.query)
        self.calls.append({"url": str(full_url), "endpoint": path, "timeout": timeout})
        fault = self.faults.get(path, self.faults.get("*"))
        if fault == "hang":
            if timeout is None:
                raise AssertionError(f"urlopen({full_url}) without timeout would hang forever")
            self.virtual_elapsed_s += float(timeout)
            raise socket.timeout("timed out")
        if fault == "timeout":
            raise TimeoutError("timed out")
        if fault in ("http500", "http429"):
            code = 500 if fault == "http500" else 429
            raise urllib.error.HTTPError(str(full_url), code, "Internal Server Error" if code == 500 else "Too Many Requests", {}, io.BytesIO(b"{}"))
        if fault == "malformed":
            return _FakeResponse(b'[{"meeting_key": 1279, "meeting_name": "Austr', url=str(full_url))
        if fault == "empty":
            return _FakeResponse(b"[]", url=str(full_url))
        if fault == "non_list":
            return _FakeResponse(b'{"detail": "No results found."}', url=str(full_url))
        if fault == "slow":
            if timeout is None:
                raise AssertionError(f"urlopen({full_url}) without timeout has no latency bound")
            self.virtual_elapsed_s += float(timeout)
        fixture = _fixture_for_endpoint(path, query)
        if fixture is None:
            raise urllib.error.HTTPError(str(full_url), 404, "Not Found", {}, io.BytesIO(b'{"detail": "No results found."}'))
        return _FakeResponse(fixture.read_bytes(), url=str(full_url))


@pytest.fixture
def serve_openf1(monkeypatch: pytest.MonkeyPatch) -> Callable[..., FakeOpenF1]:
    """Returns ``_serve(faults=None)`` that installs a FakeOpenF1 as urlopen."""

    def _serve(faults: dict[str, str] | None = None) -> FakeOpenF1:
        fake = FakeOpenF1(faults)
        monkeypatch.setattr(urllib.request, "urlopen", fake)
        _clear_cache()
        return fake

    return _serve


@pytest.fixture(scope="session")
def agent_dir() -> Path:
    """The agent directory under test ($TOTTO_APP_DIR or <repo>/cxas_app)."""
    return agent_app_dir()
