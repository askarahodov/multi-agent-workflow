"""Offline contract checks for bounded native LLM/tool conversation.

The fake provider emits the exact event types normalized by OpenRouter SSE.
No paid provider, external CLI or Hermes environment is required.
"""
from __future__ import annotations

import asyncio
import copy
import os

import pytest

from agent_management.agent_loop import AgentLoopError, run_agent_loop
from agent_management.native_tool_dispatch import NativeFilesystemDispatcher
from agent_management.scoped_fs import ScopedFilesystemExecutor

pytestmark = pytest.mark.skipif(
    os.name != "posix" or not hasattr(os, "O_NOFOLLOW"),
    reason="POSIX filesystem boundary only",
)


class ScriptedProvider:
    def __init__(self, turns):
        self.turns = turns
        self.calls = []

    async def stream(self, messages, *, tools, max_tokens):
        self.calls.append({
            "messages": copy.deepcopy(messages), "tools": tools, "max_tokens": max_tokens,
        })
        for e in self.turns[len(self.calls) - 1]:
            yield e


def usage(prompt=5, completion=3):
    return {
        "type": "usage",
        "prompt_tokens": prompt,
        "completion_tokens": completion,
        "total_tokens": prompt + completion,
    }


def done(reason):
    return {"type": "done", "finish_reason": reason, "model": "mock-stream"}


def tool(name, call_id, **kwargs):
    return {"type": "tool_call", "index": 0, "id": call_id, "name": name, "arguments": kwargs}


@pytest.fixture
def dispatcher(tmp_path):
    root = tmp_path / "workspace"
    root.mkdir()
    (root / "src").mkdir()
    (root / "out").mkdir()
    (root / "src" / "spec.txt").write_text("sample-data", encoding="utf-8")
    fs = ScopedFilesystemExecutor(
        root, {
            "fs_read": [str(root / "src" / "**")],
            "fs_write": [str(root / "out" / "**")],
        },
    )
    return NativeFilesystemDispatcher(fs), root


@pytest.mark.asyncio
async def test_two_turn_tool_cycle_and_usage(dispatcher):
    gate, root = dispatcher
    provider = ScriptedProvider([
        [tool("read_file", "call-read", path="src/spec.txt"), usage(), done("tool_calls")],
        [{"type": "text_delta", "text": "Result: sample-data"}, usage(7, 4), done("stop")],
    ])
    result = await run_agent_loop(provider, gate, [{"role": "user", "content": "inspect"}])
    assert result.output == "Result: sample-data"
    assert result.turns == 2 and result.executed_calls == 1
    assert result.total_tokens == 19
    assert provider.calls[0]["tools"] == gate.tools_schema()
    assert provider.calls[1]["messages"][-1] == {
        "role": "tool", "tool_call_id": "call-read", "content": "sample-data",
    }
    assert provider.calls[1]["messages"][-2]["tool_calls"][0]["function"] == {
        "name": "read_file", "arguments": '{"path":"src/spec.txt"}',
    }
    assert not (root / "out" / "answer.txt").exists()
    assert result.trace[-1].detail == "unverified"


@pytest.mark.asyncio
async def test_write_tool_result_before_final_and_no_task_completion(dispatcher):
    gate, root = dispatcher
    provider = ScriptedProvider([
        [tool("write_file", "call-write", path="out/report.txt", content="created"),
         usage(), done("tool_calls")],
        [{"type": "text_delta", "text": "Saved draft"}, usage(), done("stop")],
    ])
    result = await run_agent_loop(provider, gate, [{"role": "user", "content": "create"}])
    assert result.output == "Saved draft"
    assert (root / "out" / "report.txt").read_text() == "created"
    assert provider.calls[1]["messages"][-1]["content"] == "File written"
    assert not hasattr(result, "task_status")  # orchestration is sole status authority


@pytest.mark.asyncio
async def test_unauthorized_function_never_executes(dispatcher):
    gate, _ = dispatcher
    provider = ScriptedProvider([
        [tool("shell", "call-shell", command="rm -rf /"), usage(), done("tool_calls")],
        [{"type": "text_delta", "text": "Tool rejected"}, usage(), done("stop")],
    ])
    result = await run_agent_loop(provider, gate, [{"role": "user", "content": "work"}])
    assert result.output == "Tool rejected"
    assert provider.calls[1]["messages"][-1]["content"] == '{"error":"UNKNOWN_TOOL"}'
    assert gate.audit_snapshot()[0].name == "<unsupported>"


@pytest.mark.asyncio
async def test_missing_usage_cannot_run_tools(dispatcher):
    gate, root = dispatcher
    provider = ScriptedProvider([[
        tool("write_file", "call-w", path="out/file.txt", content="unsafe"),
        done("tool_calls"),
    ]])
    with pytest.raises(AgentLoopError, match="missing token accounting"):
        await run_agent_loop(provider, gate, [{"role": "user", "content": "go"}])
    assert not (root / "out" / "file.txt").exists()


@pytest.mark.asyncio
async def test_truncated_stream_cannot_run_tools(dispatcher):
    gate, root = dispatcher
    provider = ScriptedProvider([[
        tool("write_file", "call-w", path="out/file.txt", content="unsafe"),
        usage(),
    ]])
    with pytest.raises(AgentLoopError, match="without done"):
        await run_agent_loop(provider, gate, [{"role": "user", "content": "go"}])
    assert not (root / "out" / "file.txt").exists()


@pytest.mark.asyncio
async def test_overbudget_provider_cannot_run_tools(dispatcher):
    gate, root = dispatcher
    provider = ScriptedProvider([[
        tool("write_file", "call-w", path="out/file.txt", content="unsafe"),
        usage(8, 8),
        done("tool_calls"),
    ]])
    with pytest.raises(AgentLoopError, match="budget exceeded"):
        await run_agent_loop(
            provider, gate, [{"role": "user", "content": "go"}], max_total_tokens=12,
        )
    assert not (root / "out" / "file.txt").exists()


@pytest.mark.asyncio
async def test_tool_count_limit_prevents_partial_batch(dispatcher):
    gate, root = dispatcher
    provider = ScriptedProvider([[
        tool("write_file", "call-1", path="out/one.txt", content="1"),
        tool("write_file", "call-2", path="out/two.txt", content="2"),
        usage(), done("tool_calls"),
    ]])
    with pytest.raises(AgentLoopError, match="tool call limit"):
        await run_agent_loop(
            provider, gate, [{"role": "user", "content": "go"}], max_tool_calls=1,
        )
    assert not (root / "out" / "one.txt").exists()
    assert not (root / "out" / "two.txt").exists()


@pytest.mark.asyncio
async def test_turn_limit_rejects_incomplete_workflow(dispatcher):
    gate, _ = dispatcher
    provider = ScriptedProvider([[
        tool("read_file", "call-1", path="src/spec.txt"),
        usage(), done("tool_calls"),
    ]])
    with pytest.raises(AgentLoopError, match="turn limit exceeded"):
        await run_agent_loop(
            provider, gate, [{"role": "user", "content": "go"}], max_turns=1,
        )


@pytest.mark.asyncio
async def test_finish_length_cannot_be_accepted_as_success(dispatcher):
    gate, _ = dispatcher
    provider = ScriptedProvider([[
        {"type": "text_delta", "text": "truncated"},
        usage(), done("length"),
    ]])
    with pytest.raises(AgentLoopError, match="did not produce a final answer"):
        await run_agent_loop(provider, gate, [{"role": "user", "content": "go"}])


@pytest.mark.asyncio
async def test_output_size_cap(dispatcher):
    gate, _ = dispatcher
    provider = ScriptedProvider([[
        {"type": "text_delta", "text": "x" * 20},
        usage(), done("stop"),
    ]])
    with pytest.raises(AgentLoopError, match="output size exceeded"):
        await run_agent_loop(
            provider, gate, [{"role": "user", "content": "go"}], max_output_chars=12,
        )


@pytest.mark.asyncio
async def test_negative_or_missing_provider_token_accounting(dispatcher):
    gate, _ = dispatcher
    for bad in ({"type": "usage", "prompt_tokens": -2, "completion_tokens": 1, "total_tokens": 4},
                {"type": "usage", "prompt_tokens": 3, "completion_tokens": 3, "total_tokens": 2}):
        provider = ScriptedProvider([[{"type": "text_delta", "text": "answer"}, bad, done("stop")]])
        with pytest.raises(AgentLoopError, match="Invalid provider token accounting"):
            await run_agent_loop(provider, gate, [{"role": "user", "content": "go"}])


@pytest.mark.asyncio
async def test_timeout_cancels_provider_stream(dispatcher):
    gate, _ = dispatcher

    class HangingProvider:
        async def stream(self, messages, *, tools, max_tokens):
            await asyncio.sleep(1)
            yield done("stop")

    with pytest.raises(TimeoutError):
        await run_agent_loop(
            HangingProvider(), gate, [{"role": "user", "content": "go"}],
            timeout_seconds=0.01,
        )


@pytest.mark.asyncio
async def test_replayed_tool_id_denied_inside_same_loop(dispatcher):
    gate, root = dispatcher
    provider = ScriptedProvider([
        [tool("write_file", "call-same", path="out/file.txt", content="first"),
         usage(), done("tool_calls")],
        [tool("write_file", "call-same", path="out/file.txt", content="second"),
         usage(), done("tool_calls")],
        [{"type": "text_delta", "text": "done"}, usage(), done("stop")],
    ])
    result = await run_agent_loop(provider, gate, [{"role": "user", "content": "go"}])
    assert result.output == "done"
    assert (root / "out" / "file.txt").read_text() == "first"
    assert provider.calls[2]["messages"][-1]["content"] == '{"error":"DUPLICATE_CALL"}'


def test_bad_limits_fail_before_model_or_tools(dispatcher):
    gate, _ = dispatcher
    with pytest.raises(ValueError):
        asyncio.run(run_agent_loop(None, gate, [{"role": "user", "content": "go"}], max_turns=0))


@pytest.mark.parametrize("bad_usage", [
    {"prompt_tokens": True, "completion_tokens": 1, "total_tokens": 2},
    {"prompt_tokens": 1, "completion_tokens": False, "total_tokens": 2},
    {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": True},
    {"prompt_tokens": "1", "completion_tokens": 1, "total_tokens": 2},
    {"prompt_tokens": 1.5, "completion_tokens": 1, "total_tokens": 3},
    {"prompt_tokens": None, "completion_tokens": 1, "total_tokens": 2},
    {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": "2"},
    {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2.5},
    {"prompt_tokens": 1, "completion_tokens": 1},
])
@pytest.mark.asyncio
async def test_invalid_usage_never_authorizes_file_side_effect(dispatcher, bad_usage):
    gate, root = dispatcher
    provider = ScriptedProvider([[
        tool("write_file", "usage-invalid", path="out/not-written.txt", content="denied"),
        {"type": "usage", **bad_usage}, done("tool_calls"),
    ]])
    with pytest.raises(AgentLoopError, match="Invalid provider token accounting"):
        await run_agent_loop(provider, gate, [{"role": "user", "content": "test"}])
    assert not (root / "out" / "not-written.txt").exists()


@pytest.mark.parametrize("field,bad", [
    ("max_turns", True), ("max_total_tokens", True), ("max_tool_calls", False),
    ("max_output_chars", 1.5), ("max_turns", "2"),
    ("timeout_seconds", True), ("timeout_seconds", float("nan")),
    ("timeout_seconds", float("inf")), ("timeout_seconds", 10**400),
])
@pytest.mark.asyncio
async def test_malformed_loop_budgets_rejected_before_provider(dispatcher, field, bad):
    gate, _ = dispatcher
    with pytest.raises(ValueError, match="Invalid agent execution limits"):
        await run_agent_loop(None, gate, [{"role": "user", "content": "test"}], **{field: bad})
