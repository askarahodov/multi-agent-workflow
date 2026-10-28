"""Single-use runner evidence contract tests."""
import json

import pytest

from quality_gates.isolated_tester import SandboxError
from quality_gates.runner_replay import SingleUseRunnerResults


def raw():
    return json.dumps({"schema_version": 1, "kind": "untrusted_qa_execution",
                       "command_id": "python-unit", "exit_code": 0,
                       "stdout_tail": "", "stderr_tail": ""}).encode()


def test_consumes_once():
    verifier = SingleUseRunnerResults()
    data = verifier.consume(raw(), run_id="a" * 32,
                            expected_command_id="python-unit", expected_exit_code=0)
    assert data["kind"] == "untrusted_qa_execution"
    with pytest.raises(SandboxError, match="already consumed"):
        verifier.consume(raw(), run_id="a" * 32,
                         expected_command_id="python-unit", expected_exit_code=0)


def test_failed_payload_still_burns_execution_id():
    verifier = SingleUseRunnerResults()
    with pytest.raises(SandboxError):
        verifier.consume(b"{}", run_id="b" * 32,
                         expected_command_id="python-unit", expected_exit_code=0)
    with pytest.raises(SandboxError, match="already consumed"):
        verifier.consume(raw(), run_id="b" * 32,
                         expected_command_id="python-unit", expected_exit_code=0)


@pytest.mark.parametrize("value", ["", "A" * 32, "a" * 31, "z" * 32, True])
def test_rejects_invalid_trusted_ids(value):
    verifier = SingleUseRunnerResults()
    with pytest.raises(SandboxError):
        verifier.consume(raw(), run_id=value,
                         expected_command_id="python-unit", expected_exit_code=0)
    assert not verifier.consumed
