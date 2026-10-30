"""Regression tests for credential redaction in uvicorn access logs.

These tests render records through the REAL ``uvicorn.logging.AccessFormatter``
— the production rendering path.  Asserting on ``record.getMessage()`` alone is
NOT sufficient: uvicorn's access formatter builds the request line straight from
``record.args`` (the 5-tuple emitted by its httptools implementation) and never
calls ``getMessage()``.  A filter that only rewrites ``record.msg`` therefore
still leaks the credential — which is exactly what
``test_unfiltered_uvicorn_access_formatter_leaks`` documents.
"""

from __future__ import annotations

import logging

from uvicorn.logging import AccessFormatter

from shared.auth_middleware import _API_KEY_RE, _AUTHZ_RE, _ApiKeyFilter, api_key_filter

SECRET = "SECRET123"


def _access_record(path: str, status: int = 200) -> logging.LogRecord:
    """Build a record exactly as uvicorn emits it for an HTTP request."""
    return logging.LogRecord(
        name="uvicorn.access",
        level=logging.INFO,
        pathname=__file__,
        lineno=0,
        msg='%s - "%s %s HTTP/%s" %d',
        args=("127.0.0.1:5", "GET", path, "1.1", status),
        exc_info=None,
    )


def _render(record: logging.LogRecord) -> str:
    return AccessFormatter().format(record)


def test_unfiltered_uvicorn_access_formatter_leaks() -> None:
    """Documents the vector: msg-only redaction cannot fix an access line."""
    record = _access_record(f"/api/v1/workflows/runs/abc/events?api_key={SECRET}")
    assert SECRET in _render(record)


def test_access_log_line_is_redacted_end_to_end() -> None:
    record = _access_record(f"/api/v1/workflows/runs/abc/events?api_key={SECRET}")
    assert api_key_filter.filter(record) is True
    rendered = _render(record)
    assert SECRET not in rendered, rendered
    assert "api_key=***" in rendered
    # Non-credential content must survive untouched.
    assert "GET /api/v1/workflows/runs/abc/events" in rendered
    assert "127.0.0.1:5" in rendered
    assert "200" in rendered


def test_filter_instance_redacts_args() -> None:
    record = _access_record(f"/events?api_key={SECRET}")
    assert _ApiKeyFilter().filter(record) is True
    assert SECRET not in _render(record)


def test_api_key_redacted_in_the_middle_of_a_query_string() -> None:
    record = _access_record(f"/events?foo=1&api_key={SECRET}&bar=2")
    api_key_filter.filter(record)
    rendered = _render(record)
    assert SECRET not in rendered, rendered
    assert "foo=1" in rendered and "bar=2" in rendered


def test_redaction_is_case_insensitive() -> None:
    record = _access_record(f"/events?API_KEY={SECRET}")
    api_key_filter.filter(record)
    assert SECRET not in _render(record)


def test_websocket_handshake_query_is_redacted() -> None:
    record = _access_record(f"/ws/runs/abc?api_key={SECRET}", status=101)
    api_key_filter.filter(record)
    assert SECRET not in _render(record)


def test_authorization_header_redacted_in_plain_records() -> None:
    record = logging.LogRecord(
        name="x",
        level=logging.INFO,
        pathname=__file__,
        lineno=0,
        msg="rejecting request with Authorization: Bearer %s",
        args=(SECRET,),
        exc_info=None,
    )
    api_key_filter.filter(record)
    rendered = record.getMessage()
    assert SECRET not in rendered, rendered
    assert "Authorization: ***" in rendered


def test_ordinary_records_are_left_intact() -> None:
    record = logging.LogRecord(
        name="x",
        level=logging.INFO,
        pathname=__file__,
        lineno=0,
        msg="hello %s",
        args=("world",),
        exc_info=None,
    )
    api_key_filter.filter(record)
    assert record.getMessage() == "hello world"


def test_plain_message_records_are_redacted() -> None:
    record = logging.LogRecord(
        name="x",
        level=logging.INFO,
        pathname=__file__,
        lineno=0,
        msg="User api_key=%s authenticated, request id=req-456" % SECRET,
        args=None,
        exc_info=None,
    )
    api_key_filter.filter(record)
    redacted = record.getMessage()
    assert SECRET not in redacted, redacted
    assert "api_key=***" in redacted
    assert "request id=req-456" in redacted


def test_regex_patterns() -> None:
    assert _API_KEY_RE.search("api_key=SECRET123") is not None
    assert _API_KEY_RE.search("API_KEY=token123") is not None
    assert _API_KEY_RE.search("normal text without a credential") is None
    assert _AUTHZ_RE.search("Authorization: Bearer abc") is not None
    assert _AUTHZ_RE.search("authorization: abc") is not None
