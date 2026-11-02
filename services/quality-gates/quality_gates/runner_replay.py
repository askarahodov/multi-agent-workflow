"""Operator-side single-use execution ticket validation.

This is an in-memory contract test primitive, NOT a distributed replay store.
A production launcher must persist consumed IDs atomically across restarts.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from .isolated_tester import SandboxError
from .runner_result import validate_expected_runner_result

_ID = re.compile(r"[0-9a-f]{32}\Z")


@dataclass
class SingleUseRunnerResults:
    """Fail closed for repeated execution IDs within one trusted verifier."""
    consumed: set[str] = field(default_factory=set)

    def consume(
        self, raw: bytes, *, run_id: str, expected_command_id: str,
        expected_exit_code: int,
    ) -> dict[str, object]:
        if type(run_id) is not str or _ID.fullmatch(run_id) is None:
            raise SandboxError("Invalid trusted execution ID")
        if run_id in self.consumed:
            raise SandboxError("Runner execution ID already consumed")
        # Burn a valid ID before parsing attacker-supplied bytes. A failed
        # attempt must never be reusable inside this verifier's lifetime.
        self.consumed.add(run_id)
        return validate_expected_runner_result(
            raw, expected_command_id=expected_command_id,
            expected_exit_code=expected_exit_code,
        )
