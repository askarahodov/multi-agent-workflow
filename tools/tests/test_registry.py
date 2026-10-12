"""Tests for the registry core: registration, validation, policy, timeouts,
retries, audit log, and the default tool set (ADR-012 verification)."""

from __future__ import annotations

import asyncio

import pytest

from tools.registry import (
    ExecutionContext,
    ToolCategory,
    ToolExecutionError,
    ToolNotFoundError,
    ToolResult,
    ToolSpec,
    ToolStatus,
    build_default_registry,
)


def test_build_default_registry_exposes_mvp_tools():
    registry = build_default_registry()
    expected = {
        "fs_read",
        "fs_write",
        "fs_list",
        "fs_search",
        "shell_exec",
        "git_read",
        "git_write",
        "http_request",
        "spawn_agent",
    }
    assert expected <= set(registry.names())


def test_unknown_tool_resolves_to_error_result():
    registry = build_default_registry()
    ctx = ExecutionContext(run_id="r", agent_instance_id="a")
    result = asyncio.run(registry.execute("nope", {}, ctx))
    assert result.status == ToolStatus.ERROR
    assert "Unknown tool" in (result.error or "")


def test_param_schema_is_enforced(workspace):
    from tools.registry import canonical_path

    with pytest.raises(ToolNotFoundError):
        build_default_registry().get_or_raise("missing")

    spec = ToolSpec(
        name="demo",
        category=ToolCategory.FILESYSTEM,
        description="demo",
        params_schema={"type": "object", "properties": {"x": {"type": "integer"}}, "required": ["x"]},
        handler=lambda params, ctx: ToolResult.success({"ok": True}),
    )
    registry = build_default_registry()
    registry.register(spec)
    ctx = ExecutionContext(run_id="r", agent_instance_id="a")
    result = asyncio.run(registry.execute("demo", {"x": "not-int"}, ctx))
    assert result.status == ToolStatus.ERROR
    assert "invalid params" in (result.error or "")


async def test_fs_write_then_read(workspace, ctx):
    registry = build_default_registry()
    policy = {"fs_read": [str(workspace.resolve()) + "/**"], "fs_write": [str(workspace.resolve()) + "/**"]}

    w = await registry.execute("fs_write", {"path": str(workspace / "a.txt"), "content": "hello"}, ctx, policy_permissions=policy)
    assert w.status == ToolStatus.SUCCESS

    r = await registry.execute("fs_read", {"path": str(workspace / "a.txt")}, ctx, policy_permissions=policy)
    assert r.status == ToolStatus.SUCCESS
    assert r.data["content"] == "hello"


async def test_fs_write_outside_workspace_is_denied(workspace, ctx, tmp_path):
    registry = build_default_registry()
    outside = tmp_path / ".." / "outside.txt"
    policy = {"fs_write": [str(workspace.resolve()) + "/**"]}
    result = await registry.execute("fs_write", {"path": str(outside), "content": "x"}, ctx, policy_permissions=policy)
    assert result.status == ToolStatus.DENIED


async def test_fs_write_denied_when_policy_has_no_fs_write_grant(workspace, ctx):
    registry = build_default_registry()
    policy = {"fs_read": [str(workspace.resolve()) + "/**"]}  # no fs_write grant
    result = await registry.execute("fs_write", {"path": str(workspace / "x.txt"), "content": "x"}, ctx, policy_permissions=policy)
    assert result.status == ToolStatus.DENIED or result.status == ToolStatus.ERROR


async def test_shell_denied_for_non_whitelisted_command(ctx):
    registry = build_default_registry()
    policy = {"shell": ["ls", "python"]}
    result = await registry.execute("shell_exec", {"command": "python -c 'print(1)'"}, ctx, policy_permissions=policy)
    assert result.status == ToolStatus.SUCCESS
    denied = await registry.execute("shell_exec", {"command": "rm -rf /"}, ctx, policy_permissions=policy)
    assert denied.status == ToolStatus.DENIED


async def test_timeout_produces_timeout_status(ctx):
    registry = build_default_registry()

    async def hang(_params, _ctx):
        await asyncio.sleep(5)
        return {"ok": True}

    spec = ToolSpec(
        name="hang",
        category=ToolCategory.FILESYSTEM,
        description="hangs",
        params_schema={"type": "object"},
        default_timeout_ms=100,
        handler=hang,
    )
    registry.register(spec)
    result = await registry.execute("hang", {}, ctx, policy_permissions=None)
    assert result.status == ToolStatus.TIMEOUT


async def test_retry_retries_transient_tool_failures(ctx):
    registry = build_default_registry()
    calls = {"n": 0}

    async def flaky(_params, _ctx):
        calls["n"] += 1
        if calls["n"] < 3:
            raise ToolExecutionError("transient failure")
        return {"ok": True}

    spec = ToolSpec(
        name="flaky",
        category=ToolCategory.FILESYSTEM,
        description="flaky",
        params_schema={"type": "object"},
        max_retries=3,
        default_timeout_ms=5000,
        handler=flaky,
    )
    registry.register(spec)
    result = await registry.execute("flaky", {}, ctx)
    assert result.status == ToolStatus.SUCCESS
    assert calls["n"] == 3


def test_audit_log_records_calls(ctx):
    registry = build_default_registry()
    asyncio.run(registry.execute("fs_list", {"path": "."}, ctx))
    log = registry.recent_calls()
    assert any(entry["tool"] == "fs_list" for entry in log)
    assert all(entry["params_hash"] for entry in log)


def test_result_schema_validation_marks_error(ctx):
    registry = build_default_registry()

    def bad(_params, _ctx):
        return {"unexpected": True}

    spec = ToolSpec(
        name="badschema",
        category=ToolCategory.FILESYSTEM,
        description="bad result",
        params_schema={"type": "object"},
        result_schema={"type": "object", "properties": {"need": {"type": "string"}}, "required": ["need"]},
        handler=bad,
    )
    registry.register(spec)
    result = asyncio.run(registry.execute("badschema", {}, ctx))
    assert result.status == ToolStatus.ERROR
    assert "invalid result" in (result.error or "")