"""Explicit operator export of one trusted native profile snapshot.

Read-only and *not* a live resolver. The generated JSON never contains provider
credentials; only operator-owned deployment tooling may place it in a worker's
private read-only mount. Snapshot export is not authorization to execute tools.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path

from sqlalchemy import select

from .config import get_settings
from .db import build_engine, build_session_factory
from .models import AgentDefinition, ModelProfile, Provider, ToolPolicy
from .tool_policy import normalize_policy


class NativeProfileExportError(ValueError):
    """Sanitized fail-closed error with no profile data or secrets."""


async def export_native_profile(sf, agent_id: str, model_id: str, policy_id: str) -> dict:
    """Export one consistent DB statement, never a caller-provided configuration."""
    async with sf() as session:
        statement = (
            select(AgentDefinition, ModelProfile, ToolPolicy, Provider)
            .join(ModelProfile, AgentDefinition.default_model_profile_id == ModelProfile.id)
            .join(ToolPolicy, AgentDefinition.default_tool_policy_id == ToolPolicy.id)
            .join(Provider, ModelProfile.provider_id == Provider.id)
            .where(
                AgentDefinition.id == agent_id,
                ModelProfile.id == model_id,
                ToolPolicy.id == policy_id,
            )
        )
        result = (await session.execute(statement)).one_or_none()
        if result is None:
            raise NativeProfileExportError("Trusted profile references unavailable")
        definition, profile, policy, provider = result
        if not provider.is_active or provider.type != "openrouter":
            raise NativeProfileExportError("Native provider is unavailable or unsupported")
        prompt = definition.system_prompt
        if not isinstance(prompt, str) or not prompt.strip() or len(prompt) > 4096:
            raise NativeProfileExportError("Trusted agent instructions unavailable")
        model = profile.model_id
        if (
            not isinstance(model, str) or not model or len(model) > 128
            or any(c not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-._/" for c in model)
        ):
            raise NativeProfileExportError("Trusted model is invalid")
        try:
            permissions = normalize_policy(policy.permissions)
        except (ValueError, TypeError) as exc:
            raise NativeProfileExportError("Tool policy is invalid") from None
        # Native gateway exposes only file read/write. Never interpret other
        # policy grants as implemented capabilities.
        if any(permissions[kind] for kind in ("shell", "network", "git")):
            raise NativeProfileExportError("Native snapshot requires filesystem-only policy")
        if any(len(pattern) > 512 for kind in ("fs_read", "fs_write") for pattern in permissions[kind]):
            raise NativeProfileExportError("Tool policy pattern too large")
        configured = profile.parameters or {}
        if not isinstance(configured, dict):
            raise NativeProfileExportError("Model parameters invalid")
        output_tokens = configured.get("max_tokens")
        if output_tokens is not None and (type(output_tokens) is not int or not 1 <= output_tokens <= 16384):
            raise NativeProfileExportError("Model output limit invalid")
        if definition.budget_limit is not None:
            # The native leased worker does not yet reserve price across
            # workers. Prevent bypassing a monetary budget by exporting it.
            raise NativeProfileExportError("Native USD budget backend not available")
        return {
            "schema_version": 1,
            "agent_definition_id": definition.id,
            "agent_definition_version": definition.version,
            "model_profile_id": profile.id,
            "model_profile_version": profile.version,
            "tool_policy_id": policy.id,
            "tool_policy_version": policy.version,
            "provider_id": provider.id,
            "provider_version": provider.version,
            "provider_type": provider.type,
            "model_id": model,
            "system_prompt": prompt,
            "model_max_tokens": output_tokens,
            "permissions": permissions,
        }


def write_private_snapshot(path: str, data: dict) -> None:
    """Create a new 0600 file; never overwrite existing or follow a symlink."""
    location = Path(path)
    if not location.is_absolute() or any(p.is_symlink() for p in (location, *location.parents)):
        raise NativeProfileExportError("Snapshot output path must be private and absolute")
    payload = (json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n").encode()
    if len(payload) > 65536:
        raise NativeProfileExportError("Snapshot payload too large")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(location, flags, 0o600)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
    except BaseException:
        try:
            location.unlink()
        except OSError:
            pass
        raise


async def _export(args) -> None:
    engine = build_engine(get_settings().database_url)
    try:
        sf = build_session_factory(engine)
        snapshot = await export_native_profile(sf, args.agent_id, args.model_id, args.policy_id)
        write_private_snapshot(args.output, snapshot)
    finally:
        await engine.dispose()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Operator-only, offline trusted native profile export")
    parser.add_argument("--agent-id", required=True)
    parser.add_argument("--model-id", required=True)
    parser.add_argument("--policy-id", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args(argv)
    try:
        asyncio.run(_export(args))
    except (NativeProfileExportError, OSError, ValueError):
        parser.exit(2, "Native profile export failed: check trusted database and output path\n")
    print("Native profile snapshot exported (operator must mount it privately)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
