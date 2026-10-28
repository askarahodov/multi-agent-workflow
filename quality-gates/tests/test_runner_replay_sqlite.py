"""Persistent replay protection contract tests."""
from __future__ import annotations

import json
import sqlite3
import pytest

from quality_gates.isolated_tester import SandboxError
from quality_gates.runner_replay_sqlite import PersistentRunnerResults


def raw():
    return json.dumps({"schema_version": 1, "kind": "untrusted_qa_execution",
                       "command_id": "python-unit", "exit_code": 0,
                       "stdout_tail": "", "stderr_tail": ""}).encode()


def consume(store, run_id="a" * 32, content=None):
    return store.consume(raw() if content is None else content,
                         run_id=run_id, expected_command_id="python-unit",
                         expected_exit_code=0)


def test_restart_cannot_replay(tmp_path):
    location = tmp_path / "replay.sqlite"
    assert consume(PersistentRunnerResults(location))["exit_code"] == 0
    with pytest.raises(SandboxError, match="already consumed"):
        consume(PersistentRunnerResults(location))


def test_malformed_result_burns_id_across_restart(tmp_path):
    location = tmp_path / "replay.sqlite"
    with pytest.raises(SandboxError):
        consume(PersistentRunnerResults(location), content=b"{}")
    with pytest.raises(SandboxError, match="already consumed"):
        consume(PersistentRunnerResults(location))


def test_distinct_ids_independently_consumed(tmp_path):
    store = PersistentRunnerResults(tmp_path / "replay.sqlite")
    assert consume(store, "a" * 32)["exit_code"] == 0
    assert consume(store, "b" * 32)["exit_code"] == 0


def test_store_failure_fails_closed(tmp_path):
    store = PersistentRunnerResults(tmp_path / "replay.sqlite")
    store.database.mkdir()
    with pytest.raises(SandboxError, match="Replay store unavailable"):
        consume(store)


@pytest.mark.parametrize("run_id", ["A" * 32, "a" * 31, "z" * 32, True])
def test_invalid_run_id_does_not_create_db(tmp_path, run_id):
    location = tmp_path / "replay.sqlite"
    with pytest.raises(SandboxError, match="Invalid trusted"):
        consume(PersistentRunnerResults(location), run_id)
    assert not location.exists()
