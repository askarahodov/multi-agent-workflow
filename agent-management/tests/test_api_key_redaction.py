"""Regression test for API key redaction in uvicorn access logs.

Verifies that the `_ApiKeyFilter` strips ``api_key=*** and ``Authorization: ***`
from log records while preserving the rest of the message.
"""
import logging

from shared.auth_middleware import _API_KEY_RE, _AUTHZ_RE, _ApiKeyFilter


def test_api_key_redaction():
    """Test that api_key= values are redacted in log records."""
    filter_instance = _ApiKeyFilter()

    # Create a mock log record
    record = logging.LogRecord(
        name="test",
        level=logging.INFO,
        pathname="",
        lineno=0,
        msg="Request processed: GET /api/v1/events?api_key=SECRET123",
        args=None,
        exc_info=None,
    )

    assert filter_instance.filter(record) is True
    # The filter modifies record.msg in-place, so getMessage should return redacted version
    redacted = record.getMessage()
    assert "SECRET123" not in redacted, f"api_key value should be redacted, got: {redacted}"
    assert "api_key=*** " in redacted or "api_key=***" in redacted, f"api_key should be replaced with api_key=*** , got: {redacted}"
    print(f"PASS: api_key redaction: {redacted}")


def test_authz_redaction():
    """Test that Authorization: values are redacted in log records."""
    filter_instance = _ApiKeyFilter()

    record = logging.LogRecord(
        name="test",
        level=logging.INFO,
        pathname="",
        lineno=0,
        msg="Authorization: sk-abc123 processed successfully",
        args=None,
        exc_info=None,
    )

    assert filter_instance.filter(record) is True
    original_msg = record.getMessage()
    record.msg = original_msg
    record.getMessage = lambda: original_msg

    redacted = record.getMessage()
    assert "sk-abc123" not in redacted, f"Auth token should be redacted, got: {redacted}"
    assert "Authorization: ***" in redacted, f"Auth should be replaced with Authorization: *** , got: {redacted}"
    print(f"PASS: authz redaction: {redacted}")


def test_partial_redaction_preserves_rest():
    """Test that only the sensitive parts are redacted, rest of message preserved."""
    filter_instance = _ApiKeyFilter()

    record = logging.LogRecord(
        name="test",
        level=logging.INFO,
        pathname="",
        lineno=0,
        msg="User api_key=SECRET123 authenticated, request id=req-456",
        args=None,
        exc_info=None,
    )

    assert filter_instance.filter(record) is True
    original_msg = record.getMessage()
    record.msg = original_msg
    record.getMessage = lambda: original_msg

    redacted = record.getMessage()
    assert "SECRET123" not in redacted, f"api_key value should be redacted, got: {redacted}"
    assert "api_key=*** " in redacted, f"api_key should be replaced, got: {redacted}"
    assert "request id=req-456" in redacted, f"rest of message should be preserved, got: {redacted}"
    print(f"PASS: partial redaction: {redacted}")


def test_regex_patterns():
    """Test the regex patterns directly."""
    # Test api_key regex
    assert _API_KEY_RE.search("api_key=SECRET123") is not None
    assert _API_KEY_RE.search("API_KEY=token123") is not None
    assert _API_KEY_RE.search("normal text without api_key") is None

    # Test authz regex - matches "Authorization: <token>"
    assert _AUTHZ_RE.search("Authorization: sk-abc123") is not None
    # Case insensitive - should match "authorization:" or "Authorization:"
    assert _AUTHZ_RE.search("authorization: token123") is not None
    # Replacement should work
    result = _AUTHZ_RE.sub(r"Authorization: ***", "Authorization: sk-abc123")
    assert result == "Authorization: ***", f"Expected 'Authorization: ***', got '{result}'"

    print("PASS: regex patterns work correctly")


if __name__ == "__main__":
    test_api_key_redaction()
    test_authz_redaction()
    test_partial_redaction_preserves_rest()
    test_regex_patterns()
    print("\nAll tests passed!")
