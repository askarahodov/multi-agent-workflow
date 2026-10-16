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


@pytest.mark.asyncio
async def test_timeout_is_persisted_without_exception_text(dispatcher, tmp_path):
    import asyncio
    gate, workspace = dispatcher
    journal = AgentEventJournal(tmp_path / "timeout.db", run_id="attempt-timeout", workspace=workspace)

    class HangingProvider:
        async def stream(self, messages, *, tools, max_tokens):
            await asyncio.sleep(1)
            yield {"type": "done", "finish_reason": "stop"}

    with pytest.raises(TimeoutError):
        await run_agent_loop(
            HangingProvider(), gate, [{"role": "user", "content": "sk-hidden"}],
            timeout_seconds=0.01, journal=journal,
        )
    assert journal.snapshot()[-1][1:3] == ("failure", "timeout")


@pytest.mark.asyncio
async def test_provider_error_is_redacted_and_never_marked_final(dispatcher, tmp_path):
    gate, workspace = dispatcher
    journal = AgentEventJournal(tmp_path / "error.db", run_id="attempt-error", workspace=workspace)

    class QuotaProvider:
        async def stream(self, messages, *, tools, max_tokens):
            raise RuntimeError("429 secret-token-canary")
            yield {"type": "done"}

    with pytest.raises(RuntimeError, match="429"):
        await run_agent_loop(QuotaProvider(), gate, [{"role": "user", "content": "go"}], journal=journal)
    assert journal.snapshot()[-1][1:3] == ("failure", "loop_error")
    assert all("secret-token-canary" not in repr(row) for row in journal.snapshot())
    assert all(row[1] != "final" for row in journal.snapshot())


@pytest.mark.asyncio
async def test_reported_tokens_survive_429_after_usage_event(dispatcher, tmp_path):
    from agent_management.errors import ProviderError

    gate, workspace = dispatcher
    db = tmp_path / "post-usage-error.sqlite"
    journal = AgentEventJournal(db, run_id="attempt-429", workspace=workspace)

    class FailingAfterUsage:
        async def stream(self, messages, *, tools, max_tokens):
            yield usage(11, 6)
            raise ProviderError("Provider returned error status 429")
            yield done("stop")

    with pytest.raises(ProviderError, match="429"):
        await run_agent_loop(
            FailingAfterUsage(), gate,
            [{"role": "user", "content": "private-key-must-not-persist"}],
            journal=journal,
        )
    restored = AgentEventJournal(db, run_id="attempt-429", workspace=workspace)
    assert restored.snapshot() == (
        (0, "started", "started", None, "UNKNOWN"),
        (1, "usage", "unknown", 17, "UNKNOWN"),
        (0, "failure", "provider_error", None, "UNKNOWN"),
    )
    assert "private-key" not in repr(restored.snapshot())


@pytest.mark.asyncio
async def test_reported_tokens_survive_cancelled_stream(dispatcher, tmp_path):
    import asyncio
    gate, workspace = dispatcher
    journal = AgentEventJournal(
        tmp_path / "cancelled.sqlite", run_id="attempt-cancel", workspace=workspace,
    )
    seen = asyncio.Event()

    class InterruptedProvider:
        async def stream(self, messages, *, tools, max_tokens):
            yield usage(7, 4)
            seen.set()
            await asyncio.Event().wait()
            yield done("stop")

    pending = asyncio.create_task(run_agent_loop(
        InterruptedProvider(), gate, [{"role": "user", "content": "go"}],
        journal=journal,
    ))
    await asyncio.wait_for(seen.wait(), 2)
    pending.cancel()
    with pytest.raises(asyncio.CancelledError):
        await pending
    assert journal.snapshot()[-2:] == (
        (1, "usage", "unknown", 11, "UNKNOWN"),
        (0, "failure", "cancelled", None, "UNKNOWN"),
    )


@pytest.mark.asyncio
async def test_duplicate_usage_rejects_tool_side_effect_and_retains_first_accounting(dispatcher, tmp_path):
    gate, workspace = dispatcher
    journal = AgentEventJournal(
        tmp_path / "duplicate.sqlite", run_id="attempt-duplicate", workspace=workspace,
    )
    provider = ScriptedProvider([[
        tool("write_file", "never-run", path="out/forbidden.txt", content="bad"),
        usage(2, 2), usage(3, 3), done("tool_calls"),
    ]])
    from agent_management.agent_loop import AgentLoopError
    with pytest.raises(AgentLoopError, match="Duplicate provider token"):
        await run_agent_loop(provider, gate, [{"role": "user", "content": "test"}], journal=journal)
    assert not (workspace / "out" / "forbidden.txt").exists()
    assert journal.snapshot()[-2:] == (
        (1, "usage", "unknown", 4, "UNKNOWN"),
        (0, "failure", "loop_error", None, "UNKNOWN"),
    )
