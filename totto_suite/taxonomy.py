"""Result taxonomy: PASS | FAIL | INFRA_ERROR | SKIPPED (plan.md decision D3).

Score = PASS / (PASS + FAIL). INFRA_ERROR (quota/429, 5xx, deadlines and
timeouts, auth, network, websocket session errors, judge errors) is reported
as its own category and is never counted as an agent pass or fail.

``classify_exception`` maps an exception (or anything in its cause/context
chain) to an infrastructure *kind*, or returns None when the exception is not
an infrastructure failure (then it is a suite bug or a genuine failure, and
the caller must decide; it must not be silently scored as PASS).
"""

from __future__ import annotations

import dataclasses
import enum
import http.client
import re
import socket
import ssl
import urllib.error


class Status(str, enum.Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    INFRA_ERROR = "INFRA_ERROR"
    SKIPPED = "SKIPPED"

    def __str__(self) -> str:
        return self.value


STATUSES = tuple(s.value for s in Status)

# Infrastructure kinds, in reporting order.
INFRA_KINDS = (
    "quota",  # HTTP 429 / RESOURCE_EXHAUSTED / token quota
    "unavailable",  # HTTP 503
    "server_error",  # other HTTP 5xx
    "deadline",  # HTTP 504 / DEADLINE_EXCEEDED / retry deadline
    "timeout",  # client-side timeouts (TimeoutError, socket timeouts)
    "cancelled",  # HTTP 499 / CANCELLED
    "auth",  # HTTP 401, missing/expired credentials
    "permission",  # HTTP 403 (not quota related)
    "network",  # DNS, connection refused/reset, TLS, transport errors
    "bidi_session",  # SCRAPI BidiSessionError (voice websocket)
    "judge",  # LLM judge raised or returned nothing usable
)


@dataclasses.dataclass(frozen=True)
class InfraError:
    """Classification of an infrastructure failure."""

    kind: str
    http_status: int | None
    detail: str

    def message(self) -> str:
        """Canonical TestResult message prefix, parsed back by infra_kind_of."""
        code = f" {self.http_status}" if self.http_status else ""
        return f"INFRA_ERROR[{self.kind}]{code}: {self.detail}"


class JudgeError(Exception):
    """Raised by graders when an LLM judge fails or returns no usable verdict.

    Deterministic PASS + JudgeError => INFRA_ERROR (never PASS), per D3.
    """


_HTTP_KIND = {
    401: "auth",
    403: "permission",
    408: "timeout",
    429: "quota",
    499: "cancelled",
    500: "server_error",
    501: "server_error",
    502: "server_error",
    503: "unavailable",
    504: "deadline",
}

_GRPC_KIND = {
    "RESOURCE_EXHAUSTED": "quota",
    "UNAVAILABLE": "unavailable",
    "INTERNAL": "server_error",
    "UNKNOWN": "server_error",
    "DEADLINE_EXCEEDED": "deadline",
    "CANCELLED": "cancelled",
    "UNAUTHENTICATED": "auth",
    "PERMISSION_DENIED": "permission",
}

# Class names of third-party exceptions recognized without importing their
# libraries (requests, httpx, websockets, aiohttp, google.genai).
_NETWORK_CLASS_NAMES = {
    "ConnectionError",  # requests.ConnectionError
    "ConnectError",  # httpx
    "ProxyError",
    "SSLError",
    "RemoteProtocolError",
    "NetworkError",
    "ConnectionClosed",  # websockets
    "ConnectionClosedError",
    "InvalidHandshake",
    "ClientConnectionError",  # aiohttp
    "ServerDisconnectedError",
    "TransportError",  # google.auth.exceptions.TransportError, httpx
}
_TIMEOUT_CLASS_NAMES = {
    "Timeout",  # requests.Timeout
    "ReadTimeout",
    "ConnectTimeout",
    "WriteTimeout",
    "PoolTimeout",
    "TimeoutException",  # httpx
    "ServerTimeoutError",  # aiohttp
}
_AUTH_CLASS_NAMES = {"DefaultCredentialsError", "RefreshError"}

_QUOTA_TEXT = re.compile(
    r"\b429\b|resource[ _]exhausted|quota|rate[ _-]?limit|too many requests",
    re.IGNORECASE,
)


def _mro_names(exc: BaseException) -> set[str]:
    return {c.__name__ for c in type(exc).__mro__}


def _http_status(exc: BaseException) -> int | None:
    """Best-effort HTTP status of API errors (google.api_core, google.genai)."""
    for attr in ("code", "status_code", "status"):
        value = getattr(exc, attr, None)
        if callable(value):  # grpc.RpcError.code() returns a StatusCode
            continue
        if isinstance(value, int) and 100 <= value <= 599:
            return value
    return None


def _grpc_status_name(exc: BaseException) -> str | None:
    code = getattr(exc, "code", None)
    if not callable(code):
        return None
    try:
        value = code()
    except Exception:  # pylint: disable=broad-except
        return None
    name = getattr(value, "name", None)
    return name if isinstance(name, str) else None


def _classify_one(exc: BaseException) -> InfraError | None:
    names = _mro_names(exc)
    detail = f"{type(exc).__name__}: {exc}".strip()
    detail = detail[:500]

    if isinstance(exc, JudgeError):
        return InfraError("judge", None, detail)

    if "BidiSessionError" in names:
        server_kind = str(getattr(exc, "server_error_kind", "") or "").lower()
        if "resource_exhausted" in server_kind or _QUOTA_TEXT.search(str(exc)):
            return InfraError("quota", 429, detail)
        return InfraError("bidi_session", None, detail)

    if names & _AUTH_CLASS_NAMES:
        return InfraError("auth", None, detail)

    # google.api_core.exceptions.GoogleAPICallError / google.genai APIError.
    if "GoogleAPICallError" in names or "APIError" in names:
        status = _http_status(exc)
        if status is not None:
            kind = _HTTP_KIND.get(status)
            if kind is None and 500 <= status <= 599:
                kind = "server_error"
            if kind == "permission" and _QUOTA_TEXT.search(str(exc)):
                kind = "quota"
            if kind is not None:
                return InfraError(kind, status, detail)
        return None  # 400/404/409 etc.: a request bug, not infrastructure.

    if "RetryError" in names:  # google.api_core.exceptions.RetryError
        return InfraError("deadline", None, detail)

    grpc_name = _grpc_status_name(exc)
    if grpc_name in _GRPC_KIND:
        return InfraError(_GRPC_KIND[grpc_name], None, detail)

    if names & _TIMEOUT_CLASS_NAMES:
        return InfraError("timeout", None, detail)
    if isinstance(exc, (TimeoutError, socket.timeout)):
        return InfraError("timeout", None, detail)

    if isinstance(exc, urllib.error.HTTPError):
        kind = _HTTP_KIND.get(exc.code)
        if kind is None and 500 <= exc.code <= 599:
            kind = "server_error"
        return InfraError(kind, exc.code, detail) if kind else None
    if isinstance(exc, urllib.error.URLError):
        reason = getattr(exc, "reason", None)
        if isinstance(reason, (TimeoutError, socket.timeout)):
            return InfraError("timeout", None, detail)
        return InfraError("network", None, detail)

    if isinstance(
        exc,
        (
            ConnectionError,  # refused/reset/aborted, BrokenPipeError
            socket.gaierror,
            socket.herror,
            ssl.SSLError,
            http.client.HTTPException,  # RemoteDisconnected, IncompleteRead
        ),
    ):
        return InfraError("network", None, detail)

    if names & _NETWORK_CLASS_NAMES:
        return InfraError("network", None, detail)

    return None


def classify_exception(exc: BaseException) -> InfraError | None:
    """Returns the InfraError for ``exc`` (or its cause chain), else None."""
    seen = set()
    current: BaseException | None = exc
    depth = 0
    while current is not None and id(current) not in seen and depth < 8:
        seen.add(id(current))
        found = _classify_one(current)
        if found is not None:
            return found
        current = current.__cause__ or current.__context__
        depth += 1
    return None


_TEXT_RULES = (
    ("quota", _QUOTA_TEXT),
    (
        "unavailable",
        re.compile(r"\b503\b|\bUNAVAILABLE\b|service unavailable", re.I),
    ),
    ("deadline", re.compile(r"\b504\b|deadline[ _]exceeded", re.I)),
    (
        "server_error",
        re.compile(r"\b50[0-2]\b|internal server error|\bINTERNAL\b", re.I),
    ),
    ("auth", re.compile(r"\b401\b|unauthenticated|credentials", re.I)),
    ("permission", re.compile(r"\b403\b|permission[ _]denied", re.I)),
    ("timeout", re.compile(r"timed? ?out|timeout", re.I)),
    (
        "network",
        re.compile(
            r"connection (?:refused|reset|aborted|error)|name resolution"
            r"|temporary failure in name|network is unreachable",
            re.I,
        ),
    ),
)


def classify_error_text(text: str | None) -> str | None:
    """Maps an error *string* (e.g. a SCRAPI sim ``error`` field) to a kind.

    Returns None when the text does not look like an infrastructure failure.
    """
    if not text:
        return None
    for kind, pattern in _TEXT_RULES:
        if pattern.search(text):
            return kind
    return None


_INFRA_MSG = re.compile(r"^INFRA_ERROR\[([a-z_]+)\]")


def infra_kind_of(result: dict) -> str:
    """Returns the infra kind of an INFRA_ERROR TestResult ("unknown" if none).

    Uses an explicit ``infra_kind`` key when present, else the canonical
    ``INFRA_ERROR[<kind>]`` message prefix written by ``InfraError.message``.
    """
    kind = result.get("infra_kind")
    if isinstance(kind, str) and kind:
        return kind
    m = _INFRA_MSG.match(str(result.get("message") or ""))
    return m.group(1) if m else "unknown"


def summarize_infra(results: list[dict]) -> dict:
    """Returns {"count", "by_kind"} over INFRA_ERROR results (by_kind sorted)."""
    by_kind: dict[str, int] = {}
    for r in results:
        if r.get("status") != Status.INFRA_ERROR.value:
            continue
        kind = infra_kind_of(r)
        by_kind[kind] = by_kind.get(kind, 0) + 1
    return {
        "count": sum(by_kind.values()),
        "by_kind": dict(sorted(by_kind.items())),
    }
