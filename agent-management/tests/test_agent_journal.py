"""Issue #21: durable, sanitized usage and tool ledger evidence."""
import sqlite3

import pytest

from agent_management.agent_journal import AgentEventJournal
from agent_management.agent_loop import run_agent_loop
from test_agent_loop import dispatcher, ScriptedProvider, done, usage, tool


@pytest.mark.asyncio
async def test_journal_persists_across_reopen_and_never_records_model_text(dispatcher, tmp_path):
    gate, workspace = dispatcher
    db = tmp_path / "agent-events.sqlite"
    writer = AgentEventJournal(db, run_id="task-attempt-1", workspace=workspace)
    provider = ScriptedProvider([
        [tool("read_file", "read-one", path="src/spec.txt"), usage(), done("tool_calls")],
        [{"type": "text_delta", "text": "secret-answer-canary"}, usage(), done("stop")],
    ])
    result = await run_agent_loop(provider, gate, [{"role": "user", "content": "private-input-canary"}], journal=writer)
    assert result.output == "secret-answer-canary"
    reopened = AgentEventJournal(db, run_id="task-attempt-1", workspace=workspace)
    rows = reopened.snapshot()
    assert [row[1] for row in rows] == [
        "started", "usage", "provider_turn", "tool_result",
        "usage", "provider_turn", "final",
    ]
    assert sum(row[3] or 0 for row in rows) == result.total_tokens
    assert all(row[4] == "UNKNOWN" for row in rows)
    with sqlite3.connect(db) as conn:
        contents = repr(conn.execute("SELECT * FROM agent_loop_events").fetchall())
    assert "secret-answer-canary" not in contents
    assert "private-input-canary" not in contents
    assert str(workspace) not in contents


def test_journal_rejects_untrusted_location_and_redacts_details(tmp_path):
    root = tmp_path / "workspace"
    root.mkdir()
    with pytest.raises(Exception):
        AgentEventJournal(root / "agent.sqlite", run_id="trusted-run", workspace=root)
    journal = AgentEventJournal(tmp_path / "safe.sqlite", run_id="trusted-run", workspace=root)
    journal.record(1, "failure", "sk-secret-other-canary")
    assert journal.snapshot() == ((1, "failure", "error", None, "UNKNOWN"),)
    with pytest.raises(ValueError):
        journal.record(1, "arbitrary", "text")
