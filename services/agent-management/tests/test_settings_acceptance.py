"""Issue #7 acceptance: SQLite restart, encrypted secrets and bound agent profile."""
from __future__ import annotations

import httpx
import pytest

from agent_management.api import build_app
from agent_management.crypto import decrypt_auth_config, is_encrypted
from agent_management.models import Provider
from conftest import Harness


@pytest.mark.asyncio
async def test_settings_survive_service_restart_without_secret_exposure(tmp_path):
    url = f"sqlite+aiosqlite:///{tmp_path / 'persisted-settings.db'}"
    first = await Harness(url).start()
    secret = "sk-persistence-canary-do-not-leak"
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=build_app(lambda: first.service)),
            base_url="http://test",
        ) as client:
            created = await client.post("/api/v1/providers", json={
                "name": "restart-openrouter", "type": "openrouter",
                "auth_config": {"api_key": secret},
            })
            assert created.status_code == 201
            provider_id = created.json()["id"]
            assert secret not in created.text and "auth_config" not in created.text

            model = await client.post("/api/v1/model-profiles", json={
                "provider_id": provider_id, "name": "assigned-model",
                "model_id": "openai/gpt-4o-mini", "is_default": True,
            })
            assert model.status_code == 201
            model_id = model.json()["id"]
            agent = await client.post("/api/v1/agents/definitions", json={
                "name": "restart-agent", "default_model_profile_id": model_id,
            })
            assert agent.status_code == 201
            agent_id = agent.json()["id"]

            rotated = await client.patch(f"/api/v1/providers/{provider_id}", json={
                "auth_config": {"api_key": "sk-rotated-canary"},
                "version": created.json()["version"],
            })
            assert rotated.status_code == 200
            assert "sk-rotated-canary" not in rotated.text
    finally:
        await first.stop()

    second = await Harness(url).start()
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=build_app(lambda: second.service)),
            base_url="http://test",
        ) as client:
            for method, path in [
                ("GET", "/api/v1/providers"),
                ("GET", f"/api/v1/providers/{provider_id}"),
            ]:
                response = await client.request(method, path)
                assert response.status_code == 200
                assert secret not in response.text
                assert "sk-rotated-canary" not in response.text
                assert "auth_config" not in response.text

            model_response = await client.get(f"/api/v1/model-profiles/{model_id}")
            assert model_response.status_code == 200
            assert model_response.json()["model_id"] == "openai/gpt-4o-mini"
            agent_response = await client.get(f"/api/v1/agents/definitions/{agent_id}")
            assert agent_response.status_code == 200
            assert agent_response.json()["default_model_profile_id"] == model_id

            provider = await second.service.providers.get_provider(provider_id)
            assert is_encrypted(provider.auth_config)
            assert decrypt_auth_config(provider.auth_config)["api_key"] == "sk-rotated-canary"
    finally:
        await second.stop()
