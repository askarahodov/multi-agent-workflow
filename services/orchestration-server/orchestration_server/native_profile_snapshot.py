"""Private operator-owned snapshot of persisted Agent Management configuration.

One immutable deployment checkpoint, not a live revision or cost resolver.
No credentials, task input, or model output is accepted as configuration.
"""
from __future__ import annotations

import json
import os
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .native_profile_binding import TrustedProfileBinding, UUID


class NativeProfileSnapshotError(ValueError):
    """Redacted profile-snapshot validation failure."""


@dataclass(frozen=True, repr=False)
class NativeProfileSnapshot:
    binding: TrustedProfileBinding
    model_id: str
    system_prompt: str
    model_max_tokens: int | None
    permissions: dict[str, list[str]]
    definition_version: int
    model_version: int
    policy_version: int
    provider_id: str
    provider_version: int

    def __repr__(self) -> str:
        return "NativeProfileSnapshot(<redacted>)"


_FIELDS = {
    "schema_version", "agent_definition_id", "agent_definition_version",
    "model_profile_id", "model_profile_version", "tool_policy_id",
    "tool_policy_version", "provider_id", "provider_version", "provider_type",
    "model_id", "system_prompt", "model_max_tokens", "permissions",
}
_KINDS = {"fs_read", "fs_write", "git", "shell", "network"}


def _unique_fields(pairs: list[tuple[str, Any]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise NativeProfileSnapshotError("Duplicate profile field")
        result[key] = value
    return result


def read_native_profile_snapshot(path: str, binding: TrustedProfileBinding) -> NativeProfileSnapshot:
    if not isinstance(binding, TrustedProfileBinding):
        raise NativeProfileSnapshotError("Trusted profile UUIDs required")
    candidate = Path(path)
    if not candidate.is_absolute() or any(p.is_symlink() for p in (candidate, *candidate.parents)):
        raise NativeProfileSnapshotError("Private profile snapshot path invalid")
    try:
        st = os.lstat(candidate)
        if (
            not stat.S_ISREG(st.st_mode) or st.st_nlink != 1
            or st.st_mode & 0o077 or not 1 <= st.st_size <= 65536
            or (hasattr(os, "geteuid") and st.st_uid != os.geteuid())
        ):
            raise NativeProfileSnapshotError("Private profile snapshot file invalid")
        fd = os.open(candidate, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        try:
            checked = os.fstat(fd)
            if (
                (checked.st_dev, checked.st_ino) != (st.st_dev, st.st_ino)
                or checked.st_nlink != 1 or checked.st_mode & 0o077
            ):
                raise NativeProfileSnapshotError("Profile snapshot changed")
            raw = os.read(fd, 65537)
        finally:
            os.close(fd)
        if len(raw) > 65536:
            raise NativeProfileSnapshotError("Profile snapshot too large")
        def reject_constant(_value):
            raise NativeProfileSnapshotError("Nonfinite profile value")
        data = json.loads(
            raw.decode("utf-8"), object_pairs_hook=_unique_fields,
            parse_constant=reject_constant,
        )
    except (OSError, ValueError, UnicodeError, TypeError):
        raise NativeProfileSnapshotError("Trusted profile snapshot unavailable") from None
    if type(data) is not dict or set(data) != _FIELDS or type(data["schema_version"]) is not int or data["schema_version"] != 1:
        raise NativeProfileSnapshotError("Unsupported snapshot schema")
    ids = (data["agent_definition_id"], data["model_profile_id"], data["tool_policy_id"])
    if (
        any(type(value) is not str or not UUID.fullmatch(value) for value in ids)
        or not binding.matches(dict(zip(("agent_definition_id", "model_profile_id", "tool_policy_id"), ids)))
    ):
        raise NativeProfileSnapshotError("Profile identity mismatch")
    versions = (
        data["agent_definition_version"], data["model_profile_version"],
        data["tool_policy_version"], data["provider_version"],
    )
    if any(type(x) is not int or x < 1 for x in versions):
        raise NativeProfileSnapshotError("Profile revision invalid")
    if (
        data["provider_type"] != "openrouter" or type(data["provider_id"]) is not str
        or not UUID.fullmatch(data["provider_id"])
    ):
        raise NativeProfileSnapshotError("Native provider unavailable")
    model = data["model_id"]
    if (
        type(model) is not str or not 1 <= len(model) <= 128
        or any(ch not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-._/" for ch in model)
    ):
        raise NativeProfileSnapshotError("Native model invalid")
    prompt = data["system_prompt"]
    if type(prompt) is not str or not prompt.strip() or len(prompt) > 4096:
        raise NativeProfileSnapshotError("Native instructions invalid")
    tokens = data["model_max_tokens"]
    if tokens is not None and (type(tokens) is not int or not 1 <= tokens <= 16384):
        raise NativeProfileSnapshotError("Native output cap invalid")
    permissions = data["permissions"]
    if (
        type(permissions) is not dict or set(permissions) != _KINDS
        or any(type(items) is not list or len(items) > 32
               or any(type(value) is not str or not 1 <= len(value) <= 512
                      for value in items) for items in permissions.values())
        or any(permissions[kind] for kind in ("git", "shell", "network"))
    ):
        raise NativeProfileSnapshotError("Native tool policy unsupported")
    return NativeProfileSnapshot(
        binding=binding, model_id=model, system_prompt=prompt,
        model_max_tokens=tokens, permissions=permissions,
        definition_version=versions[0], model_version=versions[1],
        policy_version=versions[2], provider_id=data["provider_id"],
        provider_version=versions[3],
    )
