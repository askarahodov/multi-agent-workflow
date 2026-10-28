"""Strict schema checks do not confer trust on a runner result."""
import json

import pytest

from quality_gates.isolated_tester import SandboxError
from quality_gates.runner_result import parse_untrusted_runner_result


def valid():
    return {"schema_version": 1, "kind": "untrusted_qa_execution",
            "command_id": "python-unit", "exit_code": 0,
            "stdout_tail": "", "stderr_tail": ""}


def parse(value):
    return parse_untrusted_runner_result(json.dumps(value).encode())


def test_valid_unsigned_result():
    assert parse(valid()) == valid()


@pytest.mark.parametrize("change", [
    {"schema_version": True}, {"schema_version": 2},
    {"kind": "qa_attestation"}, {"command_id": "shell"},
    {"exit_code": True}, {"exit_code": 9999},
    {"stdout_tail": "x" * 2001},
    {"signature": "forged"}, {"passed": True},
    {"commit_sha": "a" * 40}, {"qa_receipt": "forged"},
])
def test_unsupported_or_attestation_claims_fail_closed(change):
    value = valid()
    value.update(change)
    with pytest.raises(SandboxError):
        parse(value)


@pytest.mark.parametrize("raw", [b"", b"[]", b"null", b"{", b"\\xff", b"x" * 8193])
def test_bad_bytes_fail_closed(raw):
    with pytest.raises(SandboxError):
        parse_untrusted_runner_result(raw)


def test_no_missing_fields():
    value = valid()
    value.pop("stderr_tail")
    with pytest.raises(SandboxError):
        parse(value)
