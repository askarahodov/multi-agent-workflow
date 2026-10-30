"""Opaque control-plane Git result returned by a trusted native runner.

The LLM only supplies output text. SHA/path identities come from a separate
authenticated gateway call, not model arguments.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class NativeArtifactResult:
    output: str
    commit_sha: str
    changed_paths: tuple[str, ...]
