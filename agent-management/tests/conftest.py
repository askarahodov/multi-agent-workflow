"""Shared pytest fixtures for the agent-management test suite.

Tests run against real (file-backed) SQLite databases so persistence, lifecycle and
token-accounting behaviour can be exercised end to end without any external
infrastructure. Each test file gets an isolated database URL under ``tmp_path``.
"""

from __future__ import annotations

import pytest_asyncio

from agent_management.db import build_engine, build_session_factory, create_all
from agent_management.services import AgentManagementService


class Harness:
    """An AgentManagementService bound to one SQLite database URL."""

    def __init__(self, url: str) -> None:
        self.url = url
        self.engine = None
        self.sf = None
        self.service = None

    async def start(self) -> "Harness":
        self.engine = build_engine(self.url)
        await create_all(self.engine)
        self.sf = build_session_factory(self.engine)
        self.service = AgentManagementService(self.sf)
        return self

    async def stop(self) -> None:
        if self.engine is not None:
            await self.engine.dispose()
            self.engine = None


@pytest_asyncio.fixture
async def harness(tmp_path):
    url = f"sqlite+aiosqlite:///{tmp_path / 'agent_mgmt.db'}"
    h = Harness(url)
    await h.start()
    yield h
    await h.stop()


@pytest_asyncio.fixture
async def app(harness):
    """FastAPI app wired to the harness service (for httpx ASGI tests)."""
    from agent_management.api import build_app

    app = build_app(lambda: harness.service)
    return app


async def seed_provider(h: Harness, *, name="openrouter-provider", type="mock"):
    return await h.service.providers.create_provider(
        {"name": name, "type": type, "auth_config": {}}
    )


async def seed_profile(h: Harness, provider_id, *, name="default", model_id="mock-model",
                       cost_in=0.0, cost_out=0.0, is_default=True):
    return await h.service.model_profiles.create(
        {
            "provider_id": provider_id,
            "name": name,
            "model_id": model_id,
            "cost_per_1k_input": cost_in,
            "cost_per_1k_output": cost_out,
            "is_default": is_default,
        }
    )


async def seed_policy(h: Harness, name="policy", permissions=None):
    return await h.service.tool_policies.create(
        {"name": name, "description": "test", "permissions": permissions or {}}
    )


async def seed_definition(h: Harness, *, name="def", model_profile_id=None,
                          tool_policy_id=None):
    return await h.service.agent_definitions.create(
        {
            "name": name,
            "description": "test def",
            "system_prompt": "You are a helper.",
            "default_model_profile_id": model_profile_id,
            "default_tool_policy_id": tool_policy_id,
        }
    )


async def make_running_instance(h: Harness, *, provider_id, model_profile_id=None,
                                tool_policy_id=None, definition=None):
    if definition is None:
        definition = await seed_definition(
            h, model_profile_id=model_profile_id, tool_policy_id=tool_policy_id
        )
    instance = await h.service.agent_instances.create(
        {
            "agent_definition_id": definition.id,
            "model_profile_id": model_profile_id,
            "tool_policy_id": tool_policy_id,
        }
    )
    await h.service.agent_instances.transition(instance.id, "running")
    return instance, definition