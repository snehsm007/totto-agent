"""Result taxonomy: every infrastructure kind is classified, nothing else is."""

import socket
import urllib.error

import pytest
from google.api_core import exceptions as gexc
from google.auth import exceptions as auth_exc

from totto_suite import taxonomy
from totto_suite.taxonomy import classify_exception


@pytest.mark.parametrize(
    "exc, kind, status",
    [
        (gexc.ResourceExhausted("Quota exceeded for tokens per minute"), "quota", 429),
        (gexc.TooManyRequests("slow down"), "quota", 429),
        (gexc.ServiceUnavailable("backend down"), "unavailable", 503),
        (gexc.InternalServerError("oops"), "server_error", 500),
        (gexc.BadGateway("bad gateway"), "server_error", 502),
        (gexc.DeadlineExceeded("took too long"), "deadline", 504),
        (gexc.GatewayTimeout("gateway timeout"), "deadline", 504),
        (gexc.PermissionDenied("caller lacks permission"), "permission", 403),
        (gexc.PermissionDenied("Quota exceeded for project"), "quota", 403),
        (gexc.Unauthenticated("token expired"), "auth", 401),
        (gexc.Cancelled("cancelled"), "cancelled", 499),
    ],
)
def test_google_api_core_errors(exc, kind, status):
    got = classify_exception(exc)
    assert got is not None
    assert (got.kind, got.http_status) == (kind, status)
    assert got.message().startswith(f"INFRA_ERROR[{kind}] {status}: ")


@pytest.mark.parametrize(
    "exc",
    [
        gexc.NotFound("no such session"),
        gexc.InvalidArgument("bad request"),
        gexc.FailedPrecondition("precondition"),
        ValueError("a suite bug"),
        KeyError("x"),
        AssertionError("agent answered wrongly"),
    ],
)
def test_non_infra_errors_are_not_classified(exc):
    assert classify_exception(exc) is None


@pytest.mark.parametrize(
    "exc, kind",
    [
        (auth_exc.DefaultCredentialsError("no ADC"), "auth"),
        (auth_exc.RefreshError("invalid_grant"), "auth"),
        (auth_exc.TransportError("connection reset"), "network"),
        (TimeoutError("read timed out"), "timeout"),
        (socket.timeout("timed out"), "timeout"),
        (ConnectionRefusedError(111, "refused"), "network"),
        (ConnectionResetError(104, "reset"), "network"),
        (socket.gaierror(-3, "Temporary failure in name resolution"), "network"),
        (urllib.error.URLError("unreachable"), "network"),
        (urllib.error.URLError(TimeoutError("timed out")), "timeout"),
        (urllib.error.HTTPError("u", 429, "Too Many Requests", {}, None), "quota"),
        (urllib.error.HTTPError("u", 503, "Unavailable", {}, None), "unavailable"),
        (taxonomy.JudgeError("judge returned no verdict"), "judge"),
    ],
)
def test_auth_network_timeout_and_judge_errors(exc, kind):
    got = classify_exception(exc)
    assert got is not None and got.kind == kind


def test_http_404_via_urllib_is_not_infra():
    assert classify_exception(urllib.error.HTTPError("u", 404, "NF", {}, None)) is None


def test_scrapi_bidi_session_error_quota_and_other():
    from cxas_scrapi.core.sessions import BidiSessionError

    quota = BidiSessionError(
        "closed", close_status_code=1011, server_error_kind="resource_exhausted"
    )
    other = BidiSessionError("closed", close_status_code=1007, server_error_kind="internal")
    assert classify_exception(quota).kind == "quota"
    assert classify_exception(other).kind == "bidi_session"


def test_genai_client_error_429_is_quota():
    errors = pytest.importorskip("google.genai.errors")
    exc = errors.ClientError(429, {"error": {"code": 429, "message": "RESOURCE_EXHAUSTED"}})
    got = classify_exception(exc)
    assert got is not None and got.kind == "quota"


def test_cause_chain_is_followed():
    try:
        try:
            raise gexc.ResourceExhausted("429 tokens")
        except gexc.ResourceExhausted as inner:
            raise RuntimeError("simulation job failed") from inner
    except RuntimeError as outer:
        got = classify_exception(outer)
    assert got is not None and got.kind == "quota"


@pytest.mark.parametrize(
    "text, kind",
    [
        ("429 RESOURCE_EXHAUSTED: token quota", "quota"),
        ("503 Service Unavailable", "unavailable"),
        ("DEADLINE_EXCEEDED while waiting", "deadline"),
        ("Read timed out", "timeout"),
        ("Connection refused", "network"),
        ("401 Unauthenticated", "auth"),
        ("Agent said the wrong race", None),
        ("", None),
        (None, None),
    ],
)
def test_classify_error_text(text, kind):
    assert taxonomy.classify_error_text(text) == kind


def test_summarize_infra_counts_by_kind():
    results = [
        {"status": "INFRA_ERROR", "message": "INFRA_ERROR[quota] 429: x"},
        {"status": "INFRA_ERROR", "message": "INFRA_ERROR[quota] 429: y"},
        {"status": "INFRA_ERROR", "message": "whatever", "infra_kind": "judge"},
        {"status": "INFRA_ERROR", "message": "no prefix"},
        {"status": "FAIL", "message": "INFRA_ERROR[quota] 429: not counted"},
    ]
    assert taxonomy.summarize_infra(results) == {
        "count": 4,
        "by_kind": {"judge": 1, "quota": 2, "unknown": 1},
    }


def test_status_values():
    assert taxonomy.STATUSES == ("PASS", "FAIL", "INFRA_ERROR", "SKIPPED")
    assert str(taxonomy.Status.INFRA_ERROR) == "INFRA_ERROR"
