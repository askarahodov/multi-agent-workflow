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


async def sse_payloads(lines: AsyncIterator[str]) -> AsyncIterator[str]:
    """Extract data messages, including multi-line SSE payloads and comments."""
    parts: list[str] = []
    async for line in lines:
        line = line.rstrip("\r")
        if not line:
            if parts:
                yield "\n".join(parts)
                parts = []
        elif line.startswith("data:"):
            parts.append(line[5:].lstrip(" "))
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
        if isinstance(usage, dict):
            try:
                events.append({
                    "type": "usage",
                    "prompt_tokens": int(usage.get("prompt_tokens") or 0),
                    "completion_tokens": int(usage.get("completion_tokens") or 0),
                    "total_tokens": int(usage.get("total_tokens") or 0),
                })
            except (TypeError, ValueError) as exc:
                raise ProviderError("Invalid usage information in provider stream") from exc

        for choice in payload.get("choices") or []:
            if not isinstance(choice, dict) or choice.get("index", 0) != 0:
                continue
            delta = choice.get("delta") or {}
            if not isinstance(delta, dict):
                raise ProviderError("Malformed provider streaming delta")
            content = delta.get("content")
            if isinstance(content, str) and content:
                events.append({"type": "text_delta", "text": content})

            for fragment in delta.get("tool_calls") or []:
                if not isinstance(fragment, dict) or not isinstance(fragment.get("index"), int):
                    raise ProviderError("Malformed provider streaming tool call")
                index = fragment["index"]
                if index < 0 or index > 100:
                    raise ProviderError("Tool call index exceeds streaming limit")
                call = self.calls.setdefault(index, {"id": "", "name": "", "arguments": ""})
                call_id = fragment.get("id")
                # Providers normally send the id in the first fragment. Repeated
                # identical ids must not be concatenated into an invalid id.
                if call_id:
                    if call["id"] and call["id"] != call_id:
                        raise ProviderError("Conflicting streamed tool call ids")
                    call["id"] = str(call_id)
                function = fragment.get("function") or {}
                if not isinstance(function, dict):
                    raise ProviderError("Malformed streamed function call")
                call["name"] += str(function.get("name") or "")
                call["arguments"] += str(function.get("arguments") or "")
                if len(call["arguments"].encode("utf-8")) > MAX_TOOL_ARGUMENT_BYTES:
                    raise ProviderError("Streamed tool arguments exceeded size limit")

            if choice.get("finish_reason") is not None:
                self.finish_reason = str(choice["finish_reason"])
        return events

    def finish(self) -> list[Dict[str, Any]]:
        events: list[Dict[str, Any]] = []
        for index, call in sorted(self.calls.items()):
            if not call["id"] or not call["name"]:
                raise ProviderError("Incomplete tool call in provider stream")
            try:
                arguments = json.loads(call["arguments"])
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
