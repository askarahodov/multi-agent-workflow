"""Incremental OpenAI-compatible Server-Sent Events decoding.

This module only assembles provider output. It NEVER executes a tool call:
the future native agent executor must validate permissions, budgets and the
orchestration contract before doing anything with a completed call.
"""
from __future__ import annotations

import json
from typing import Any, AsyncIterator, Dict

from ..errors import ProviderError

MAX_TOOL_ARGUMENT_BYTES = 262_144
MAX_SSE_EVENT_BYTES = 1_048_576
MAX_TOOL_NAME_CHARS = 128
MAX_TOOL_ID_CHARS = 128


async def sse_payloads(lines: AsyncIterator[str]) -> AsyncIterator[str]:
    """Extract data messages, including multi-line SSE payloads and comments."""
    parts: list[str] = []
    size = 0
    async for line in lines:
        line = line.rstrip("\r")
        if not line:
            if parts:
                yield "\n".join(parts)
                parts = []
                size = 0
        elif line.startswith("data:"):
            value = line[5:].lstrip(" ")
            size += len(value.encode("utf-8")) + 1
            if size > MAX_SSE_EVENT_BYTES:
                raise ProviderError("Provider SSE event exceeded size limit")
            parts.append(value)
        # event:, id:, retry: and comment lines are not payload.
    if parts:
        yield "\n".join(parts)


class StreamAssembler:
    """Combine incremental delta fragments into non-executable tool call events."""

    def __init__(self) -> None:
        self.calls: Dict[int, Dict[str, Any]] = {}
        self.response_id: str | None = None
        self.model: str | None = None
        self.finish_reason: str | None = None
        self.usage_seen = False

    def feed(self, payload: Dict[str, Any]) -> list[Dict[str, Any]]:
        if not isinstance(payload, dict):
            raise ProviderError("Provider streaming event is not an object")
        if payload.get("error"):
            raise ProviderError("Provider returned an error in the streaming response")
        if payload.get("id") and not self.response_id:
            self.response_id = str(payload["id"])
        if payload.get("model"):
            self.model = str(payload["model"])

        events: list[Dict[str, Any]] = []
        usage = payload.get("usage")
        if usage is not None:
            if self.usage_seen:
                raise ProviderError("Duplicate usage in provider stream")
            if not isinstance(usage, dict) or not all(
                type(usage.get(key)) is int
                for key in ("prompt_tokens", "completion_tokens", "total_tokens")
            ):
                raise ProviderError("Invalid usage information in provider stream")
            if (
                usage["prompt_tokens"] < 0 or usage["completion_tokens"] < 0
                or usage["total_tokens"] <= 0
                or usage["total_tokens"] < usage["prompt_tokens"] + usage["completion_tokens"]
            ):
                raise ProviderError("Invalid usage information in provider stream")
            self.usage_seen = True
            events.append({
                "type": "usage",
                "prompt_tokens": usage["prompt_tokens"],
                "completion_tokens": usage["completion_tokens"],
                "total_tokens": usage["total_tokens"],
            })

        choices = payload.get("choices") or []
        if not isinstance(choices, list):
            raise ProviderError("Malformed provider choices")
        for choice in choices:
            if not isinstance(choice, dict) or choice.get("index", 0) != 0:
                continue
            delta = choice.get("delta") or {}
            if not isinstance(delta, dict):
                raise ProviderError("Malformed provider streaming delta")
            content = delta.get("content")
            if isinstance(content, str) and content:
                events.append({"type": "text_delta", "text": content})

            for fragment in delta.get("tool_calls") or []:
                if (
                    not isinstance(fragment, dict)
                    or type(fragment.get("index")) is not int
                ):
                    raise ProviderError("Malformed provider streaming tool call")
                index = fragment["index"]
                if index < 0 or index > 100:
                    raise ProviderError("Tool call index exceeds streaming limit")
                call = self.calls.setdefault(index, {"id": "", "name": "", "arguments": ""})
                call_id = fragment.get("id")
                # Providers normally send the id in the first fragment. Repeated
                # identical ids must not be concatenated into an invalid id.
                if call_id:
                    if type(call_id) is not str or len(call_id) > MAX_TOOL_ID_CHARS:
                        raise ProviderError("Invalid streamed tool call ID")
                    if call["id"] and call["id"] != call_id:
                        raise ProviderError("Conflicting streamed tool call ids")
                    call["id"] = str(call_id)
                function = fragment.get("function") or {}
                if not isinstance(function, dict):
                    raise ProviderError("Malformed streamed function call")
                name = function.get("name") or ""
                arguments = function.get("arguments") or ""
                if type(name) is not str or type(arguments) is not str:
                    raise ProviderError("Malformed streamed function fragments")
                call["name"] += name
                if len(call["name"]) > MAX_TOOL_NAME_CHARS:
                    raise ProviderError("Streamed tool name exceeded size limit")
                call["arguments"] += arguments
                if len(call["arguments"].encode("utf-8")) > MAX_TOOL_ARGUMENT_BYTES:
                    raise ProviderError("Streamed tool arguments exceeded size limit")

            if choice.get("finish_reason") is not None:
                new_reason = choice["finish_reason"]
                if type(new_reason) is not str or (
                    self.finish_reason is not None and self.finish_reason != new_reason
                ):
                    raise ProviderError("Conflicting streamed finish reason")
                self.finish_reason = new_reason
        return events

    def finish(self) -> list[Dict[str, Any]]:
        events: list[Dict[str, Any]] = []
        for index, call in sorted(self.calls.items()):
            if not call["id"] or not call["name"]:
                raise ProviderError("Incomplete tool call in provider stream")
            try:
                def unique_pairs(pairs):
                    values = {}
                    for key, value in pairs:
                        if key in values:
                            raise ValueError("Duplicate object key")
                        values[key] = value
                    return values
                def reject_constant(_value):
                    raise ValueError("Nonfinite JSON")
                arguments = json.loads(
                    call["arguments"], object_pairs_hook=unique_pairs,
                    parse_constant=reject_constant,
                )
            except (TypeError, ValueError) as exc:
                raise ProviderError("Invalid JSON arguments in streamed tool call") from exc
            if not isinstance(arguments, dict):
                raise ProviderError("Streamed function arguments must be a JSON object")
            events.append({
                "type": "tool_call",
                "index": index,
                "id": call["id"],
                "name": call["name"],
                "arguments": arguments,
            })
        events.append({
            "type": "done",
            "id": self.response_id,
            "model": self.model,
            "finish_reason": self.finish_reason,
        })
        return events
