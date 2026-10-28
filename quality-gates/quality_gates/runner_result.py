"""Validate unsigned runner output before *any* trusted interpretation.

Structural validation is not authentication or proof of execution provenance.
"""
from __future__ import annotations

import json

from .isolated_tester import SandboxError

_KEYS = frozenset({"schema_version", "kind", "command_id", "exit_code", "stdout_tail", "stderr_tail"})
_COMMANDS = frozenset({"python-unit", "python-version"})
_MAX_TAIL = 2000
_MAX_BYTES = 8192


def parse_untrusted_runner_result(raw: bytes) -> dict[str, object]:
    if type(raw) is not bytes or len(raw) > _MAX_BYTES:
        raise SandboxError("Invalid runner result size")
    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeError, ValueError) as exc:
        raise SandboxError("Malformed runner result") from exc
    if type(data) is not dict or set(data) != _KEYS:
        raise SandboxError("Unexpected runner result fields")
    if type(data["schema_version"]) is not int or data["schema_version"] != 1:
        raise SandboxError("Unsupported runner result version")
    if data["kind"] != "untrusted_qa_execution":
        raise SandboxError("Invalid runner result kind")
    if type(data["command_id"]) is not str or data["command_id"] not in _COMMANDS:
        raise SandboxError("Unexpected runner command")
    if type(data["exit_code"]) is not int or not -255 <= data["exit_code"] <= 255:
        raise SandboxError("Invalid runner exit code")
    for field in ("stdout_tail", "stderr_tail"):
        if type(data[field]) is not str or len(data[field]) > _MAX_TAIL:
            raise SandboxError("Runner output limit exceeded")
    return data
