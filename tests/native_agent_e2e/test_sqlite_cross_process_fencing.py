"""Actual OS-process SQLite lock/fencing acceptance, no paid LLM or Docker.

A separate Python interpreter holds BEGIN IMMEDIATE. Orchestration lease
revocation must not commit until the OS process releases the writer lock.
Once revoked, a trusted file operation using the old credential is denied.
"""
from __future__ import annotations

import asyncio
import os
import sys

import pytest

from agent_management.native_tool_dispatch import NativeFilesystemDispatcher
from agent_management.scoped_fs import ScopedFilesystemExecutor
from orchestration_server.attempt_leases import AttemptLeaseService
from shared.attempt_fence import TrustedSqliteAttemptFence

from test_native_contract_pipeline import runtime, tool


_CHILD = """
import sqlite3, sys
connection = sqlite3.connect(sys.argv[1], timeout=20, isolation_level=None)
connection.execute('BEGIN IMMEDIATE')
print('LOCKED', flush=True)
sys.stdin.readline()
connection.execute('COMMIT')
connection.close()
"""


@pytest.mark.asyncio
async def test_real_subprocess_sqlite_writer_blocks_revoke_then_fences_tool(runtime, tmp_path):
    attempt = await runtime["orch"].claim_task(
        runtime["task"].id, runtime["agent"].id,
    )
    service = AttemptLeaseService(runtime["factory"], ttl_seconds=60)
    grant = await service.issue(attempt.id, runtime["agent"].id)
    db = tmp_path / "orchestration.sqlite3"
    os.chmod(db, 0o600)

    child = await asyncio.create_subprocess_exec(
        sys.executable, "-c", _CHILD, str(db),
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    revoking = None
    try:
        assert child.stdout is not None
        ready = await asyncio.wait_for(child.stdout.readline(), timeout=8)
        assert ready == b"LOCKED\n", "Independent SQLite writer failed to start"
        revoking = asyncio.create_task(service.revoke(attempt.id))
        await asyncio.sleep(0.2)
        assert not revoking.done(), "Revocation committed while a different process held SQLite lock"
    finally:
        if child.stdin and not child.stdin.is_closing():
            child.stdin.write(b"release\n")
            await child.stdin.drain()
            child.stdin.close()
        try:
            await asyncio.wait_for(child.wait(), timeout=8)
        except asyncio.TimeoutError:
            child.kill()
            await child.wait()
    assert child.returncode == 0
    assert revoking is not None
    assert await asyncio.wait_for(revoking, timeout=12)
    root = runtime["workspace"]
    fs = ScopedFilesystemExecutor(root, {
        "fs_write": [str(root / "out" / "**")],
    })
    fence = TrustedSqliteAttemptFence(
        db, run_id=runtime["run"].id, task_id=runtime["task"].id,
        attempt_id=attempt.id, agent_id=runtime["agent"].id,
        lease_token=grant.token, require_lease=True,
    )
    dispatch = NativeFilesystemDispatcher(
        fs, ledger=runtime["ledger"],
        execution_scope=fence.execution_scope, attempt_fence=fence,
    )
    result = await asyncio.to_thread(
        dispatch.dispatch,
        tool("write_file", "after-subprocess-revoke",
             path="out/after-subprocess.txt", content="UNAUTHORIZED"),
    )
    assert result.error_code == "ATTEMPT_FENCED"
    assert not (root / "out" / "after-subprocess.txt").exists()
