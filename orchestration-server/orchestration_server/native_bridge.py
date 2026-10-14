"""Native agent result bridge — orchestration remains the sole task authority.

This adapter coordinates a *trusted* native runner with OrchestrationEngine.
The runner returns its final model output as text, never a requested task status.
Only OrchestrationEngine.submit() may verify the task Contract and complete it.

This is an offline-testable integration seam, not a worker scheduler or a
production sandbox. The trusted worker constructs its own agent permissions,
tool ledger and workspace, and passes a coroutine that invokes run_agent_loop.
"""
from __future__ import annotations

import json
import math
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from .engine import OrchestrationEngine

MAX_RESULT_BYTES = 65_536
Runner = Callable[[str, str], Awaitable[str]]


class InvalidNativeOutput(ValueError):
    """Model output could not be safely submitted to Contract Gate."""


@dataclass(frozen=True)
class NativeBridgeResult:
    task_id: str
    attempt_id: str
    status: str
    verified: bool


def _unique_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    data: dict[str, Any] = {}
    for key, value in pairs:
        if key in data:
            raise InvalidNativeOutput("Duplicate keys are not valid task output")
        data[key] = value
    return data


def _reject_nonfinite(value: str) -> None:
    raise InvalidNativeOutput("Nonfinite JSON values are not valid task output")


def _finite_float(value: str) -> float:
    parsed = float(value)
    if not math.isfinite(parsed):
        raise InvalidNativeOutput("Nonfinite JSON values are not valid task output")
    return parsed


def parse_native_output(text: str, *, max_bytes: int = MAX_RESULT_BYTES) -> dict:
    """Strict JSON object only; reject model formatting and nonstandard JSON.

    Parsing happens before submit, but never before an attempt has been claimed.
    The model is unable to specify attempt owner, verification status or scope.
    """
    if not isinstance(text, str):
        raise InvalidNativeOutput("Native agent must return UTF-8 JSON text")
    if max_bytes <= 0:
        raise ValueError("max_bytes must be positive")
    if len(text.encode("utf-8")) > max_bytes:
        raise InvalidNativeOutput("Native agent output exceeded size limit")
    try:
        data = json.loads(
            text,
            object_pairs_hook=_unique_pairs,
            parse_constant=_reject_nonfinite,
            parse_float=_finite_float,
        )
    except (ValueError, TypeError, RecursionError) as exc:
        raise InvalidNativeOutput("Native agent output is not valid JSON") from exc
    if not isinstance(data, dict):
        raise InvalidNativeOutput("Native agent result must be a JSON object")
    try:
        # json.loads accepts escaped lone surrogates; reject strings which
        # cannot be represented as proper UTF-8 downstream in the DB/API.
        json.dumps(data, ensure_ascii=False).encode("utf-8")
    except (UnicodeError, ValueError, TypeError) as exc:
        raise InvalidNativeOutput("Native agent output is not valid UTF-8 JSON") from exc
    return data


async def run_native_task_attempt(
    engine: OrchestrationEngine,
    *,
    task_id: str,
    agent_id: str,
    runner: Runner,
    max_result_bytes: int = MAX_RESULT_BYTES,
) -> NativeBridgeResult:
    """Claim once, run once, then hand output to platform-owned Contract Gate.

    Failures in the runner or strict JSON decoding go through fail_attempt with
    a stable non-sensitive reason. Engine policy decides if/when to retry.
    Cancellation is NOT swallowed: the engine's recover() path must reconcile
    an interrupted attempt without guessing whether tools have run.
    """
    if not callable(runner):
        raise TypeError("Trusted asynchronous runner required")
    if max_result_bytes <= 0:
        raise ValueError("max_result_bytes must be positive")

    attempt = await engine.claim_task(task_id, agent_id)
    try:
        output_text = await runner(task_id, attempt.id)
        output = parse_native_output(output_text, max_bytes=max_result_bytes)
    except InvalidNativeOutput:
        failed = await engine.fail_attempt(
            task_id, attempt.id, agent_id, "native_output_invalid",
        )
        return NativeBridgeResult(task_id, attempt.id, failed.status, False)
    except Exception:
        # Provider/tool errors may contain secret URLs, input text, paths,
        # headers or API keys. Never store them in task error or saga journal.
        failed = await engine.fail_attempt(
            task_id, attempt.id, agent_id, "native_runner_failed",
        )
        return NativeBridgeResult(task_id, attempt.id, failed.status, False)

    submitted = await engine.submit(task_id, attempt.id, agent_id, output)
    verification = submitted.verification_result or {}
    return NativeBridgeResult(
        task_id=task_id,
        attempt_id=attempt.id,
        status=submitted.status,
        verified=submitted.status == "completed" and verification.get("valid") is True,
    )
