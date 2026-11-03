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
from time import perf_counter

from uvicorn.config import LOGGING_CONFIG
from uvicorn.logging import AccessFormatter

from shared.auth_middleware import _API_KEY_RE, _AUTHZ_RE, _ApiKeyFilter, api_key_filter

SECRET = "SECRET123"

# The formatter string uvicorn actually installs for its access log. Rendering
# with a bare ``AccessFormatter()`` would inherit logging.Formatter's default
# ``%(message)s``, which resolves through ``record.getMessage()`` — i.e. NOT the
# path the fix targets — and the tests would then pass on the broken code too.
ACCESS_FMT = LOGGING_CONFIG["formatters"]["access"]["fmt"]


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
    return AccessFormatter(fmt=ACCESS_FMT, use_colors=False).format(record)


def test_unfiltered_uvicorn_access_formatter_leaks() -> None:
    """Documents the vector: msg-only redaction cannot fix an access line."""
    record = _access_record(f"/api/v1/workflows/runs/abc/events?api_key={SECRET}")
    assert SECRET in _render(record)


def test_access_log_line_is_redacted_end_to_end() -> None:
    record = _access_record(f"/api/v1/workflows/runs/abc/events?api_key={SECRET}")
    assert api_key_filter.filter(record) is True
    rendered = _render(record)
    assert SECRET not in rendered, rendered
    assert "?" not in rendered
    # Non-query request metadata must survive untouched.
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
    assert "foo=1" not in rendered and "bar=2" not in rendered
    assert "?" not in rendered


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


def test_percent_encoded_param_name_is_redacted() -> None:
    """``api%5Fkey`` decodes to ``api_key`` — and the server accepts it."""
    record = _access_record(f"/events?api%5Fkey={SECRET}")
    api_key_filter.filter(record)
    rendered = _render(record)
    assert SECRET not in rendered, rendered


def test_hyphenated_and_prefixed_names_are_redacted() -> None:
    for name in ("api-key", "X-API-KEY", "API_KEY"):
        record = _access_record(f"/events?{name}={SECRET}")
        api_key_filter.filter(record)
        assert SECRET not in _render(record), name


def test_other_query_parameters_are_removed() -> None:
    record = _access_record(f"/events?run_id=abc&api_key={SECRET}&limit=10")
    api_key_filter.filter(record)
    rendered = _render(record)
    assert "run_id=abc" not in rendered and "limit=10" not in rendered
    assert "GET /events " in rendered


def test_install_helper_is_idempotent() -> None:
    import logging as _logging

    from shared.auth_middleware import _ApiKeyFilter, install_access_log_redaction

    install_access_log_redaction()
    install_access_log_redaction()
    logger = _logging.getLogger("uvicorn.access")
    assert sum(isinstance(f, _ApiKeyFilter) for f in logger.filters) == 1


def test_stream_ticket_redacted_in_real_access_formatter() -> None:
    for name in ("stream_ticket", "stream%5Fticket", "STREAM-TICKET"):
        record = _access_record(f"/api/v1/workflows/runs/r/ws?{name}={SECRET}", status=101)
        api_key_filter.filter(record)
        rendered = _render(record)
        assert SECRET not in rendered, name
        assert "?" not in rendered, name


def test_access_log_strips_arbitrary_query_names_and_preserves_path() -> None:
    for target in (
        "/api/v1/workflows/runs/abc/events?session_token=hidden&after=12",
        "/api/v1/workflows/runs/abc/ws?signature=hidden&stream_ticket=hidden",
        "/api/v1/workflows/runs/abc/events?opaque_without_equals",
        "/api/v1/workflows/runs/abc/events?encoded%5Fcredential=hidden",
        "/api/v1/workflows/runs/abc/events?token=hidden#fragment",
    ):
        record = _access_record(target, status=101)
        api_key_filter.filter(record)
        rendered = _render(record)
        assert "?" not in rendered, rendered
        assert "hidden" not in rendered, rendered
        assert "GET /api/v1/workflows/runs/abc/" in rendered, rendered
        assert "101" in rendered


def test_access_log_queryless_paths_remain_unchanged() -> None:
    record = _access_record("/api/v1/workflows/runs/abc/events", status=200)
    before = _render(record)
    api_key_filter.filter(record)
    assert _render(record) == before


def test_error_logger_strips_unknown_query_parameters_from_websocket_target() -> None:
    record = logging.LogRecord(
        name="uvicorn.error",
        level=logging.INFO,
        pathname=__file__,
        lineno=0,
        msg="WebSocket /api/v1/workflows/runs/r/ws?session_secret=%s&after=8 [accepted]",
        args=(SECRET,),
        exc_info=None,
    )
    api_key_filter.filter(record)
    rendered = record.getMessage()
    assert SECRET not in rendered
    assert "session_secret" not in rendered
    assert "after=8" not in rendered
    assert "/api/v1/workflows/runs/r/ws [accepted]" in rendered


def test_error_logger_strips_queries_from_absolute_urls() -> None:
    record = logging.LogRecord(
        name="uvicorn.error",
        level=logging.ERROR,
        pathname=__file__,
        lineno=0,
        msg="Unable to connect to https://example.org/callback?nonstandard_secret=%s",
        args=(SECRET,),
        exc_info=None,
    )
    api_key_filter.filter(record)
    rendered = record.getMessage()
    assert SECRET not in rendered
    assert "nonstandard_secret" not in rendered
    assert "https://example.org/callback" in rendered


def test_error_logger_never_exposes_query_after_literal_apostrophe() -> None:
    record = logging.LogRecord(
        name="uvicorn.error",
        level=logging.INFO,
        pathname=__file__,
        lineno=0,
        msg="WebSocket /api/v1/workflows/runs/r/ws?noise='&signature=%s [accepted]",
        args=(SECRET,),
        exc_info=None,
    )
    api_key_filter.filter(record)
    rendered = record.getMessage()
    assert SECRET not in rendered
    assert "signature" not in rendered
    assert "noise" not in rendered
    assert "/api/v1/workflows/runs/r/ws [accepted]" in rendered


def test_queryless_slash_heavy_paths_do_not_block_log_filter() -> None:
    path = "/" * 64_000
    access = _access_record(path)
    started = perf_counter()
    api_key_filter.filter(access)
    access_line = _render(access)
    assert path in access_line
    error = logging.LogRecord(
        name="uvicorn.error",
        level=logging.INFO,
        pathname=__file__,
        lineno=0,
        msg="WebSocket %s [accepted]",
        args=(path,),
        exc_info=None,
    )
    api_key_filter.filter(error)
    assert path in error.getMessage()
    # A generous CI threshold catches the old quadratic regex behavior;
    # a linear scan completes orders of magnitude faster for this input.
    assert perf_counter() - started < 2.0


def test_error_logger_strips_root_and_absolute_root_query_targets() -> None:
    for target in ("/?signature=", "https://example.org?signature="):
        record = logging.LogRecord(
            name="uvicorn.error",
            level=logging.INFO,
            pathname=__file__,
            lineno=0,
            msg=f"WebSocket {target}%s [accepted]",
            args=(SECRET,),
            exc_info=None,
        )
        api_key_filter.filter(record)
        rendered = record.getMessage()
        assert SECRET not in rendered
        assert "signature" not in rendered
        assert "?" not in rendered
        assert " [accepted]" in rendered


def test_uvicorn_error_exception_traceback_strips_stream_query() -> None:
    """Formatter appends exc_info after record.msg; it must be redacted too."""
    import sys

    try:
        raise RuntimeError(
            "Handshake failed https://example.test/ws?opaque_ticket=SECRET123&after=1"
        )
    except RuntimeError:
        exc = sys.exc_info()
    record = logging.LogRecord(
        name="uvicorn.error",
        level=logging.ERROR,
        pathname=__file__,
        lineno=0,
        msg="WebSocket handshake failed",
        args=(),
        exc_info=exc,
    )
    unfiltered = logging.Formatter("%(message)s").format(record)
    assert SECRET in unfiltered
    record.exc_text = None  # reset formatter cache from baseline assertion
    api_key_filter.filter(record)
    rendered = logging.Formatter("%(message)s").format(record)
    assert "RuntimeError:" in rendered
    assert "Handshake failed https://example.test/ws" in rendered
    assert "opaque_ticket" not in rendered
    assert SECRET not in rendered
    assert record.exc_info is None
    # Re-rendering with a different formatter cannot resurrect the original.
    assert SECRET not in logging.Formatter("%(levelname)s: %(message)s").format(record)


def test_existing_exception_text_and_stack_info_are_redacted() -> None:
    record = logging.LogRecord(
        name="uvicorn.error",
        level=logging.ERROR,
        pathname=__file__,
        lineno=0,
        msg="Failed to open /ws?signature=SECRET123",
        args=(),
        exc_info=None,
        sinfo="Stack at /events?token=SECRET123",
    )
    record.exc_text = "previous traceback at wss://example.test/ws?ticket=SECRET123"
    api_key_filter.filter(record)
    rendered = logging.Formatter("%(message)s").format(record)
    assert SECRET not in rendered
    assert "signature=" not in rendered
    assert "token=" not in rendered
    assert "ticket=" not in rendered
    assert "previous traceback at wss://example.test/ws" in rendered


def test_queryless_exception_traceback_remains_diagnostic() -> None:
    import sys

    try:
        raise ValueError("invalid workflow ID")
    except ValueError:
        exc = sys.exc_info()
    record = logging.LogRecord(
        name="uvicorn.error", level=logging.ERROR, pathname=__file__,
        lineno=0, msg="Validation failed", args=(), exc_info=exc,
    )
    api_key_filter.filter(record)
    rendered = logging.Formatter("%(message)s").format(record)
    assert "ValueError: invalid workflow ID" in rendered
    assert "Traceback (most recent call last)" in rendered


def test_exception_and_source_line_strip_embedded_absolute_url_query() -> None:
    import sys

    try:
        raise RuntimeError("https://example.test/ws?opaque_ticket=SECRET123")
    except RuntimeError:
        exc = sys.exc_info()
    record = logging.LogRecord(
        name="uvicorn.error", level=logging.ERROR, pathname=__file__,
        lineno=0, msg="Handshake failed", args=(), exc_info=exc,
    )
    api_key_filter.filter(record)
    rendered = logging.Formatter("%(message)s").format(record)
    assert SECRET not in rendered
    assert "opaque_ticket" not in rendered
    assert 'raise RuntimeError("https://example.test/ws' in rendered
    assert "RuntimeError: https://example.test/ws" in rendered


def test_error_log_strips_embedded_url_after_equals_and_relative_target() -> None:
    for message in (
        "Failed url=https://example.test/ws?opaque_ticket=SECRET123",
        "Failed uri=wss://example.test/ws?opaque_ticket=SECRET123",
        'Failed RuntimeError("/events?opaque_ticket=SECRET123")',
        'Bad request path=/events?opaque_ticket=SECRET123',
    ):
        record = logging.LogRecord(
            name="uvicorn.error", level=logging.ERROR, pathname=__file__,
            lineno=0, msg=message, args=(), exc_info=None,
        )
        api_key_filter.filter(record)
        rendered = logging.Formatter("%(message)s").format(record)
        assert SECRET not in rendered, rendered
        assert "opaque_ticket" not in rendered, rendered


def test_embedded_redaction_stays_linear_for_long_input() -> None:
    text = "/" * 64_000 + "?opaque_ticket=SECRET123"
    record = logging.LogRecord(
        name="uvicorn.error", level=logging.INFO, pathname=__file__,
        lineno=0, msg="request=%s", args=(text,), exc_info=None,
    )
    started = perf_counter()
    api_key_filter.filter(record)
    rendered = logging.Formatter("%(message)s").format(record)
    assert SECRET not in rendered
    assert perf_counter() - started < 2.0
