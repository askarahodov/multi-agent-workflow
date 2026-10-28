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
    tmp_path.chmod(0o700)
    location = tmp_path / "replay.sqlite"
    assert consume(PersistentRunnerResults(location))["exit_code"] == 0
    with pytest.raises(SandboxError, match="already consumed"):
        consume(PersistentRunnerResults(location))


def test_malformed_result_burns_id_across_restart(tmp_path):
    tmp_path.chmod(0o700)
    location = tmp_path / "replay.sqlite"
    with pytest.raises(SandboxError):
        consume(PersistentRunnerResults(location), content=b"{}")
    with pytest.raises(SandboxError, match="already consumed"):
        consume(PersistentRunnerResults(location))


def test_distinct_ids_independently_consumed(tmp_path):
    tmp_path.chmod(0o700)
    store = PersistentRunnerResults(tmp_path / "replay.sqlite")
    assert consume(store, "a" * 32)["exit_code"] == 0
    assert consume(store, "b" * 32)["exit_code"] == 0


def test_store_failure_fails_closed(tmp_path):
    tmp_path.chmod(0o700)
    location = tmp_path / "replay.sqlite"
    store = PersistentRunnerResults(location)
    location.write_bytes(b"not a sqlite database")
    with pytest.raises(SandboxError, match="Replay store unavailable"):
        consume(store)


@pytest.mark.parametrize("run_id", ["A" * 32, "a" * 31, "z" * 32, True])
def test_invalid_run_id_does_not_create_db(tmp_path, run_id):
    tmp_path.chmod(0o700)
    location = tmp_path / "replay.sqlite"
    with pytest.raises(SandboxError, match="Invalid trusted"):
        consume(PersistentRunnerResults(location), run_id)
    assert not location.exists()


def test_rejects_public_parent_directory(tmp_path):
    tmp_path.chmod(0o755)
    with pytest.raises(SandboxError, match="directory must be private"):
        PersistentRunnerResults(tmp_path / "replay.sqlite")


def test_rejects_public_existing_database(tmp_path):
    tmp_path.chmod(0o700)
    path = tmp_path / "replay.sqlite"
    path.write_bytes(b"")
    path.chmod(0o644)
    with pytest.raises(SandboxError, match="private and service-owned"):
        PersistentRunnerResults(path)


def test_concurrent_consumers_only_one_wins(tmp_path):
    import concurrent.futures
    import threading

    tmp_path.chmod(0o700)
    location = tmp_path / "replay.sqlite"
    # Create the database before racing consumes so only the atomic INSERT
    # determines the winner, not the exclusive first-file creation.
    consume(PersistentRunnerResults(location), "d" * 32)
    barrier = threading.Barrier(8)

    def attempt(_):
        store = PersistentRunnerResults(location)
        barrier.wait(timeout=10)
        try:
            consume(store, "c" * 32)
            return "accepted"
        except SandboxError as exc:
            if "already consumed" not in str(exc):
                raise
            return "replayed"

    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(attempt, range(8)))
    assert results.count("accepted") == 1
    assert results.count("replayed") == 7
