"""HTTP-level tests of the agent-management REST API using httpx's ASGI transport,
and validation of the generated OpenAPI schema.
"""

from __future__ import annotations

import httpx
import pytest

from agent_management.schemas import AgentInstanceResponse


async def client_for(app):
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


class TestProviderEndpoints:
    async def test_crud_and_problem_details(self, app):
        async with await client_for(app) as client:
            # create
            r = await client.post("/api/v1/providers", json={"name": "http-p", "type": "mock"})
            assert r.status_code == 201
            body = r.json()
            pid = body["id"]
            assert body["name"] == "http-p"
            # auth_config is never echoed
            assert "auth_config" not in body

            # list
            r = await client.get("/api/v1/providers")
            assert r.status_code == 200
            assert r.json()["total"] == 1

            # get + patch
            r = await client.patch(f"/api/v1/providers/{pid}", json={"is_active": False})
            assert r.status_code == 200
            assert r.json()["is_active"] is False

            # get missing -> 404 problem details
            r = await client.get("/api/v1/providers/nope")
            assert r.status_code == 404
            assert r.json()["type"] == "urn:agent-management:error:not-found"

            # delete -> 204
            r = await client.delete(f"/api/v1/providers/{pid}")
            assert r.status_code == 204

    async def test_duplicate_name_conflict(self, app):
        async with await client_for(app) as client:
            await client.post("/api/v1/providers", json={"name": "d", "type": "mock"})
            r = await client.post("/api/v1/providers", json={"name": "d", "type": "mock"})
            assert r.status_code == 409
            assert r.json()["type"] == "urn:agent-management:error:duplicate-key"

    async def test_validation_error(self, app):
        async with await client_for(app) as client:
            r = await client.post("/api/v1/providers", json={"name": "x", "type": "nope"})
            # the schema's field validator rejects the type -> FastAPI RequestValidationError (422)
            assert r.status_code == 422


class TestAgentEndpoints:
    async def test_full_lifecycle_over_http(self, app):
        async with await client_for(app) as client:
            # provider + model profile + tool policy + definition
            pr = await client.post("/api/v1/providers", json={"name": "http-agent", "type": "mock"})
            pid = pr.json()["id"]
            mpr = await client.post(
                "/api/v1/model-profiles",
                json={"provider_id": pid, "name": "default", "model_id": "mock-model"},
            )
            mp_id = mpr.json()["id"]
            tpr = await client.post(
                "/api/v1/tool-policies",
                json={"name": "http-policy", "permissions": {"shell": ["pytest"]}},
            )
            tp_id = tpr.json()["id"]
            dr = await client.post(
                "/api/v1/agents/definitions",
                json={
                    "name": "http-def",
                    "system_prompt": "help",
                    "default_model_profile_id": mp_id,
                    "default_tool_policy_id": tp_id,
                },
            )
            assert dr.status_code == 201
            def_id = dr.json()["id"]

            # instantiate
            ir = await client.post(
                "/api/v1/agents/instances",
                json={"agent_definition_id": def_id, "model_profile_id": mp_id},
            )
            assert ir.status_code == 201
            inst = AgentInstanceResponse(**ir.json())
            assert inst.status == "pending"

            # start lifecycle over HTTP
            sr = await client.post(f"/api/v1/agents/instances/{inst.id}/start")
            assert sr.status_code == 200
            assert sr.json()["status"] == "running"

            # completion records usage
            cr = await client.post(
                "/api/v1/completions",
                json={
                    "provider_id": pid,
                    "model_profile_id": mp_id,
                    "agent_instance_id": inst.id,
                    "messages": [{"role": "user", "content": "hi"}],
                },
            )
            assert cr.status_code == 200
            cbody = cr.json()
            assert cbody["total_tokens"] > 0
            assert cbody.get("usage_record_id") is not None

            # usage summary reflects it
            us = await client.get("/api/v1/usage/summary")
            assert us.json()["request_count"] == 1

            # complete lifecycle
            fr = await client.post(f"/api/v1/agents/instances/{inst.id}/complete")
            assert fr.json()["status"] == "completed"

            # duplicate definition name -> 409
            dup = await client.post(
                "/api/v1/agents/definitions",
                json={"name": "http-def", "default_model_profile_id": mp_id},
            )
            assert dup.status_code == 409


class TestOpenAPI:
    async def test_openapi_schema_validates(self, app):
        import json

        from openapi_spec_validator import validate

        spec = app.openapi()
        validate(spec)  # raises on invalid
        paths = spec["paths"]
        for expected in (
            "/api/v1/providers",
            "/api/v1/model-profiles",
            "/api/v1/tool-policies",
            "/api/v1/agents/definitions",
            "/api/v1/agents/instances",
            "/api/v1/agents/instances/{instance_id}/start",
            "/api/v1/usage/summary",
            "/api/v1/completions",
        ):
            assert expected in paths, f"missing path {expected}"

    async def test_openapi_serializes(self, app):
        # ensures the generated spec is JSON-serializable (no enums/bytes issues)
        import json

        json.dumps(app.openapi())