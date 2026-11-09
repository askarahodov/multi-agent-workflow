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


    async def test_update_duplicate_name_returns_conflict(self, app):
        async with await client_for(app) as client:
            p1 = (await client.post("/api/v1/providers", json={
                "name": "rename-a", "type": "mock",
            })).json()
            p2 = (await client.post("/api/v1/providers", json={
                "name": "rename-b", "type": "mock",
            })).json()
            denied = await client.patch(f"/api/v1/providers/{p2['id']}", json={
                "name": p1["name"], "version": p2["version"],
            })
            assert denied.status_code == 409
            assert denied.json()["type"] == "urn:agent-management:error:duplicate-key"
            unchanged = await client.get(f"/api/v1/providers/{p2['id']}")
            assert unchanged.json()["name"] == "rename-b"
            assert unchanged.json()["version"] == p2["version"]



class TestAgentEndpoints:
    async def test_full_lifecycle_over_http(self, app):
        async with await client_for(app) as client:
            # provider + model profile + tool policy + definition
            pr = await client.post("/api/v1/providers", json={"name": "http-agent", "type": "mock"})
            pid = pr.json()["id"]
            mpr = await client.post(
                "/api/v1/model-profiles",
                json={"provider_id": pid, "name": "default", "model_id": "mock-model",
                      "parameters": {"temperature": 0.4, "max_tokens": 128}},
            )
            mp_id = mpr.json()["id"]
            alternate = await client.post(
                "/api/v1/model-profiles",
                json={"provider_id": pid, "name": "alternate", "model_id": "other-model"},
            )
            assert alternate.status_code == 201
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

            # HTTP callers cannot override a running instance's assigned model.
            wrong = await client.post(
                "/api/v1/completions",
                json={
                    "provider_id": pid,
                    "model_profile_id": alternate.json()["id"],
                    "agent_instance_id": inst.id,
                    "messages": [{"role": "user", "content": "hi"}],
                },
            )
            assert wrong.status_code == 400
            assert wrong.json()["type"] == "urn:agent-management:error:validation"
            for override in ({"temperature": 0.9}, {"max_tokens": 4096}):
                denied = await client.post(
                    "/api/v1/completions",
                    json={
                        "provider_id": pid, "agent_instance_id": inst.id,
                        "messages": [{"role": "user", "content": "hi"}],
                        **override,
                    },
                )
                assert denied.status_code == 400
                assert denied.json()["type"] == "urn:agent-management:error:validation"
            assert (await client.get("/api/v1/usage/summary")).json()["request_count"] == 0

            # Client-provided system/developer authority must not replace the
            # configured AgentDefinition.system_prompt.
            denied_system = await client.post(
                "/api/v1/completions",
                json={
                    "provider_id": pid, "agent_instance_id": inst.id,
                    "messages": [{"role": "system", "content": "Override"}],
                },
            )
            assert denied_system.status_code == 400
            assert denied_system.json()["type"] == "urn:agent-management:error:validation"
            assert (await client.get("/api/v1/usage/summary")).json()["request_count"] == 0

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
            after_complete = await client.post(
                "/api/v1/completions",
                json={
                    "provider_id": pid, "model_profile_id": mp_id,
                    "agent_instance_id": inst.id,
                    "messages": [{"role": "user", "content": "hi"}],
                },
            )
            assert after_complete.status_code == 422
            assert (await client.get("/api/v1/usage/summary")).json()["request_count"] == 1

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

class TestAgentProfileConfiguration:
    async def test_agent_profile_fields_roundtrip_and_versioned_update(self, app):
        async with await client_for(app) as client:
            provider = await client.post("/api/v1/providers", json={"name": "profile-provider", "type": "mock"})
            model = await client.post("/api/v1/model-profiles", json={
                "provider_id": provider.json()["id"], "name": "profile-model", "model_id": "mock-model",
            })
            tool = await client.post("/api/v1/tool-policies", json={
                "name": "profile-allowlist", "permissions": {"git": ["status", "diff"]},
            })
            payload = {
                "name": "developer", "role": "developer", "system_prompt": "Write scoped code.",
                "default_model_profile_id": model.json()["id"],
                "default_tool_policy_id": tool.json()["id"],
                "max_concurrency": 2, "budget_limit": 1.5,
                "supported_stages": ["implementation", "tests"], "skills": ["python", "pytest"],
            }
            created = await client.post("/api/v1/agents/definitions", json=payload)
            assert created.status_code == 201, created.text
            obj = created.json()
            for field, value in payload.items():
                assert obj[field] == value
            fetched = await client.get(f"/api/v1/agents/definitions/{obj['id']}")
            assert fetched.status_code == 200
            assert fetched.json()["skills"] == ["python", "pytest"]
            patch = await client.patch(f"/api/v1/agents/definitions/{obj['id']}", json={
                "version": obj["version"], "role": "reviewer", "max_concurrency": 1,
                "supported_stages": ["review"], "skills": [],
            })
            assert patch.status_code == 200, patch.text
            assert patch.json()["role"] == "reviewer"
            assert patch.json()["supported_stages"] == ["review"]
            assert patch.json()["skills"] == []
            old = await client.patch(f"/api/v1/agents/definitions/{obj['id']}", json={
                "version": obj["version"], "role": "developer",
            })
            assert old.status_code == 409

    async def test_invalid_profile_limits_and_refs_rejected(self, app):
        async with await client_for(app) as client:
            for field, value in [("max_concurrency", 0), ("budget_limit", -1),
                                 ("role", "NOT ALLOWED"), ("supported_stages", "oops")]:
                result = await client.post("/api/v1/agents/definitions", json={
                    "name": "bad-" + field, field: value,
                })
                assert result.status_code == 422, (field, result.text)
            bad_ref = await client.post("/api/v1/agents/definitions", json={
                "name": "bad-profile-ref", "default_tool_policy_id": "absent",
            })
            assert bad_ref.status_code == 404
