"""Bounded, provider-agnostic LLM -> scoped-file-tool -> LLM loop.

This is an offline-testable vertical slice of the future native agent runtime.
The loop NEVER marks orchestration tasks completed: only OrchestrationEngine
may verify a Contract Gate and update durable task/run lifecycle.

Security boundaries:
- The trusted caller constructs the tool dispatcher and prompt.
- Tools are limited to those exposed by NativeFilesystemDispatcher.
- All tool calls are fully assembled and validated before execution.
- Provider usage and terminal [DONE] are mandatory before ANY side effect.
- Durable replay journal, cost accounting, native shell/Git/HTTP and worker
  cancellation/recovery are separate gates, not claimed by this module.
"""
from __future__ import annotations

import asyncio
import json
import math
from dataclasses import dataclass
from typing import Any, AsyncIterator, Mapping, Protocol, Sequence

from .agent_journal import AgentEventJournal
from .errors import ProviderError
from .native_tool_dispatch import NativeFilesystemDispatcher
from .trusted_fs_client import TrustedRemoteFilesystemDispatcher


class StreamingProvider(Protocol):
    def stream(
        self,
        messages: list[dict[str, Any]],
        *,
        tools: list[dict[str, Any]],
        max_tokens: int,
    ) -> AsyncIterator[dict[str, Any]]: ...


class AgentLoopError(RuntimeError):
    """The native agent loop stopped without a verified final answer."""


@dataclass(frozen=True)
class AgentTraceEvent:
    turn: int
    kind: str
    detail: str


@dataclass(frozen=True)
class AgentLoopResult:
    output: str
    turns: int
    executed_calls: int
    total_tokens: int
    trace: tuple[AgentTraceEvent, ...]


async def run_agent_loop(
    provider: StreamingProvider,
    dispatcher: NativeFilesystemDispatcher | TrustedRemoteFilesystemDispatcher,
    messages: Sequence[Mapping[str, Any]],
    *,
    max_turns: int = 4,
    max_total_tokens: int = 4096,
    max_tool_calls: int = 8,
    timeout_seconds: float = 60.0,
    max_output_chars: int = 65_536,
    journal: AgentEventJournal | None = None,
) -> AgentLoopResult:
    """Execute bounded streaming provider turns with only approved file tools.

    The model cannot control workspace/policy, deadlines, or budgets.
    Provider errors, missing usage, truncated streams and exceeding any limit
    fail without returning a success result; the upstream orchestration task
    therefore remains uncompleted until its own Contract Gate accepts output.
    """
    if (
        type(max_turns) is not int or not 1 <= max_turns <= 128
        or type(max_total_tokens) is not int or not 1 <= max_total_tokens <= 10_000_000
        or type(max_tool_calls) is not int or not 0 <= max_tool_calls <= 128
        or isinstance(timeout_seconds, bool)
        or not isinstance(timeout_seconds, (int, float))
        or not 0 < timeout_seconds <= 86_400
        or (isinstance(timeout_seconds, float) and not math.isfinite(timeout_seconds))
        or type(max_output_chars) is not int
        or not 1 <= max_output_chars <= 1_000_000
    ):
        raise ValueError("Invalid agent execution limits")
    if not isinstance(dispatcher, (NativeFilesystemDispatcher, TrustedRemoteFilesystemDispatcher)):
        raise TypeError("A trusted native tool dispatcher is required")
    if journal is not None and not isinstance(journal, AgentEventJournal):
        raise TypeError("Trusted agent journal required")
    history = [dict(msg) for msg in messages]
    if not history or any(not isinstance(msg.get("role"), str) for msg in history):
        raise ValueError("Trusted caller must provide at least one valid message")

    if journal is not None:
        journal.record(0, "started", "started")
    trace: list[AgentTraceEvent] = []
    spent_tokens = 0
    executed_calls = 0
    total_output_chars = 0

    try:
        async with asyncio.timeout(timeout_seconds):
            for turn in range(1, max_turns + 1):
                remaining = max_total_tokens - spent_tokens
                if remaining <= 0:
                    raise AgentLoopError("Agent token budget exhausted")

                fragments: list[str] = []
                queued_calls: list[dict[str, Any]] = []
                terminal: dict[str, Any] | None = None
                usage: dict[str, Any] | None = None

                async for event in provider.stream(
                    history,
                    tools=(dispatcher.available_tools_schema() if isinstance(dispatcher, NativeFilesystemDispatcher)
                           else dispatcher.tools_schema()),
                    max_tokens=remaining,
                ):
                    if not isinstance(event, dict):
                        raise AgentLoopError("Malformed streaming event")
                    kind = event.get("type")
                    if terminal is not None:
                        raise AgentLoopError("Provider sent data after completion")
                    if kind == "text_delta":
                        text = event.get("text")
                        if not isinstance(text, str):
                            raise AgentLoopError("Malformed text delta")
                        total_output_chars += len(text)
                        if total_output_chars > max_output_chars:
                            raise AgentLoopError("Agent output size exceeded")
                        fragments.append(text)
                    elif kind == "tool_call":
                        queued_calls.append(event)
                        if len(queued_calls) + executed_calls > max_tool_calls:
                            raise AgentLoopError("Agent tool call limit exceeded")
                    elif kind == "usage":
                        if usage is not None:
                            raise AgentLoopError("Duplicate provider token accounting")
                        # A provider may report billable usage and then fail,
                        # disconnect or time out before a final DONE marker.
                        # Record validated usage as soon as it is observed, so
                        # the durable journal survives that interrupted turn.
                        if not all(
                            type(event.get(key)) is int
                            for key in ("prompt_tokens", "completion_tokens", "total_tokens")
                        ):
                            raise AgentLoopError("Invalid provider token accounting")
                        if (
                            event["prompt_tokens"] < 0
                            or event["completion_tokens"] < 0
                            or event["total_tokens"] <= 0
                            or event["total_tokens"] < (
                                event["prompt_tokens"] + event["completion_tokens"]
                            )
                        ):
                            raise AgentLoopError("Invalid provider token accounting")
                        usage = event
                        if journal is not None:
                            journal.record(
                                turn, "usage", "unknown",
                                tokens=(event["total_tokens"] if event["total_tokens"] <= 10_000_000 else None),
                            )
                    elif kind == "done":
                        terminal = event
                    else:
                        raise AgentLoopError("Unsupported provider streaming event")

                if terminal is None:
                    raise AgentLoopError("Provider stream ended without done event")
                if usage is None:
                    # No write is allowed based on a stream with unknown accounting.
                    raise AgentLoopError("Provider stream missing token accounting")
                if not all(
                    type(usage.get(key)) is int
                    for key in ("prompt_tokens", "completion_tokens", "total_tokens")
                ):
                    raise AgentLoopError("Invalid provider token accounting")
                input_tokens = usage["prompt_tokens"]
                output_tokens = usage["completion_tokens"]
                used_tokens = usage["total_tokens"]
                if (
                    input_tokens < 0 or output_tokens < 0
                    or used_tokens <= 0 or used_tokens < input_tokens + output_tokens
                ):
                    raise AgentLoopError("Invalid provider token accounting")
                if spent_tokens + used_tokens > max_total_tokens:
                    raise AgentLoopError("Agent token budget exceeded")
                spent_tokens += used_tokens

                finish_reason = terminal.get("finish_reason")
                text = "".join(fragments)
                trace.append(AgentTraceEvent(turn, "provider_turn", str(finish_reason or "unknown")))
                if journal is not None:
                    journal.record(turn, "provider_turn", str(finish_reason or "unknown"))

                if queued_calls:
                    if finish_reason != "tool_calls":
                        raise AgentLoopError("Tool call stream has invalid finish reason")
                    # The provider's complete response and usage have been received.
                    # Only now may policy-checked I/O begin.
                    assistant_calls: list[dict[str, Any]] = []
                    for call in queued_calls:
                        if not isinstance(call.get("id"), str):
                            raise AgentLoopError("Malformed tool call ID")
                        if not isinstance(call.get("name"), str) or not isinstance(call.get("arguments"), dict):
                            raise AgentLoopError("Malformed tool call arguments")
                        assistant_calls.append({
                            "id": call["id"],
                            "type": "function",
                            "function": {
                                "name": call["name"],
                                "arguments": json.dumps(call["arguments"], ensure_ascii=False, separators=(",", ":")),
                            },
                        })
                    history.append({
                        "role": "assistant",
                        "content": text or None,
                        "tool_calls": assistant_calls,
                    })
                    for call in queued_calls:
                        if isinstance(dispatcher, TrustedRemoteFilesystemDispatcher):
                            outcome = await dispatcher.dispatch_async(call)
                        else:
                            outcome = await asyncio.to_thread(dispatcher.dispatch, call)
                        executed_calls += 1
                        history.append(outcome.to_provider_message())
                        trace.append(AgentTraceEvent(
                            turn, "tool_result", "OK" if outcome.ok else str(outcome.error_code),
                        ))
                        if journal is not None:
                            journal.record(turn, "tool_result", "OK" if outcome.ok else str(outcome.error_code))
                    continue

                if finish_reason != "stop" or not text.strip():
                    raise AgentLoopError("Provider did not produce a final answer")
                trace.append(AgentTraceEvent(turn, "final", "unverified"))
                if journal is not None:
                    journal.record(turn, "final", "unverified")
                # Final is NOT an orchestration completion. Contract Gate is external.
                return AgentLoopResult(
                    output=text,
                    turns=turn,
                    executed_calls=executed_calls,
                    total_tokens=spent_tokens,
                    trace=tuple(trace),
                )

        raise AgentLoopError("Agent turn limit exceeded")

    except asyncio.CancelledError:
        if journal is not None:
            journal.record(0, "failure", "cancelled")
        raise
    except TimeoutError:
        if journal is not None:
            journal.record(0, "failure", "timeout")
        raise
    except ProviderError:
        if journal is not None:
            journal.record(0, "failure", "provider_error")
        raise
    except Exception:
        if journal is not None:
            journal.record(0, "failure", "loop_error")
        raise
