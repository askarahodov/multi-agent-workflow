"""Unit + API tests for the FastAPI control plane and RuntimeService."""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

from runtime.api import AgentConflict, AgentNotFound, InvalidTransition, RuntimeService, create_app
from runtime.models import AgentState, ResourceQuotaConfig


@pytest.fixture
def service(settings: Any, quota_config: ResourceQuotaConfig) -> RuntimeService:
    return RuntimeService(settings=settings, quota_config=quota_config, manage_containers=False)


@pytest.fixture
def client(service: RuntimeService) -> TestClient:
    return TestClient(create_app(service))


SPEC: dict[str, Any] = {
    "id": "agent-one",
    "name": "one",
    "isolationTier": "gvisor-runsc",
    "image": "alpine:latest",
    "resourceClass": "untrusted",
    "workspace": {"baseImage": "alpine", "durable": True},
}


# --------------------------------------------------------------------------- #
# Service-level
# --------------------------------------------------------------------------- #
def test_service_create_and_get(service: RuntimeService) -> None:
    from runtime.models import AgentSpec

    agent = service.create_agent(AgentSpec.model_validate(SPEC))
    assert agent.state == AgentState.RUNNING
    assert agent.runtimeClass == "runsc"
    assert service.get_agent("agent-one").id == "agent-one"
    status = service.get_status("agent-one")
    assert status.workspace is not None


def test_service_duplicate_conflict(service: RuntimeService) -> None:
    from runtime.models import AgentSpec

    spec = AgentSpec.model_validate(SPEC)
    service.create_agent(spec)
    with pytest.raises(AgentConflict):
        service.create_agent(spec)


def test_service_unknown_agent(service: RuntimeService) -> None:
    with pytest.raises(AgentNotFound):
        service.get_agent("ghost")


def test_service_lifecycle_transitions(service: RuntimeService) -> None:
    from runtime.models import AgentSpec

    service.create_agent(AgentSpec.model_validate(SPEC))
    assert service.pause_agent("agent-one").state == AgentState.PAUSED
    assert service.resume_agent("agent-one").state == AgentState.RUNNING
    # resume when not paused is invalid
    with pytest.raises(InvalidTransition):
        service.resume_agent("agent-one")
    assert service.stop_agent("agent-one").state == AgentState.TERMINATED


def test_service_limits_and_usage(service: RuntimeService) -> None:
    from runtime.models import AgentSpec, ResourceLimitsDelta

    service.create_agent(AgentSpec.model_validate(SPEC))
    limits = service.get_limits("agent-one")
    assert limits.memory is not None and limits.memory.maxBytes is not None
    adjusted = service.adjust_limits("agent-one", ResourceLimitsDelta(pidsMaxDelta=10))
    assert adjusted.pids is not None
    usage = service.get_usage("agent-one")
    assert usage is not None
    pressure = service.get_pressure("agent-one")
    assert pressure is not None


def test_service_delete_cleans_up(service: RuntimeService) -> None:
    from runtime.models import AgentSpec

    service.create_agent(AgentSpec.model_validate(SPEC))
    service.delete_agent("agent-one", 0, force=True)
    with pytest.raises(AgentNotFound):
        service.get_agent("agent-one")
    assert not service.workspace_manager.workspace_path("agent-one").exists()


def test_service_rollback_on_cgroup_failure(
    service: RuntimeService, monkeypatch: pytest.MonkeyPatch
) -> None:
    from runtime.models import AgentSpec

    def boom(*_args: Any, **_kwargs: Any) -> None:
        raise RuntimeError("cgroup failure")

    monkeypatch.setattr(service.resource_manager, "apply_limits", boom)
    with pytest.raises(RuntimeError):
        service.create_agent(AgentSpec.model_validate(SPEC))
    # workspace created before rollback must be gone
    assert not service.workspace_manager.workspace_path("agent-one").exists()


# --------------------------------------------------------------------------- #
# HTTP-level
# --------------------------------------------------------------------------- #
def test_openapi_exposes_contract(client: TestClient) -> None:
    spec = client.get("/openapi.json").json()
    for path in ("/agents", "/agents/{agent_id}", "/agents/{agent_id}/pause", "/workspaces"):
        assert path in spec["paths"]


def test_http_create_get_list_delete(client: TestClient) -> None:
    created = client.post("/agents", json=SPEC)
    assert created.status_code == 201
    assert created.json()["state"] == "running"

    assert client.get("/agents/agent-one").status_code == 200
    listing = client.get("/agents", params={"state": "running"}).json()
    assert listing["items"][0]["id"] == "agent-one"

    # duplicate
    assert client.post("/agents", json=SPEC).status_code == 409
    # not found
    assert client.get("/agents/missing").status_code == 404

    deleted = client.request(
        "DELETE", "/agents/agent-one", params={"graceSeconds": 0, "force": True}
    )
    assert deleted.status_code == 202


def test_http_http_validation_rejects_bad_spec(client: TestClient) -> None:
    assert client.post("/agents", json={"name": "x"}).status_code == 422


def test_http_lifecycle_verbs(client: TestClient) -> None:
    client.post("/agents", json=SPEC)
    assert client.post("/agents/agent-one/pause").status_code == 202
    assert client.post("/agents/agent-one/pause").status_code == 409  # already paused
    assert client.post("/agents/agent-one/resume").status_code == 202
    assert client.post("/agents/agent-one/resume").status_code == 409
    assert client.post("/agents/agent-one/stop").status_code == 202


def test_http_status_metrics_health_logs(client: TestClient) -> None:
    client.post("/agents", json=SPEC)
    status = client.get("/agents/agent-one/status")
    assert status.status_code == 200
    assert status.json()["agent"]["id"] == "agent-one"

    metrics = client.get("/agents/agent-one/metrics")
    assert metrics.status_code == 200
    assert "agent_runtime_agents_total" in metrics.text

    health = client.get("/agents/agent-one/health")
    assert health.status_code == 200
    assert health.json()["readiness"] == "pass"

    logs = client.get("/agents/agent-one/logs")
    assert logs.status_code == 200


def test_http_limits_usage_pressure(client: TestClient) -> None:
    client.post("/agents", json=SPEC)
    limits = client.get("/agents/agent-one/limits")
    assert limits.status_code == 200
    put = client.put("/agents/agent-one/limits", json={"pids": {"max": 42}})
    assert put.status_code == 200 and put.json()["pids"]["max"] == 42
    patch = client.patch("/agents/agent-one/limits", json={"memoryMaxBytesDelta": 1024})
    assert patch.status_code == 200
    assert client.get("/agents/agent-one/usage").status_code == 200
    assert client.get("/agents/agent-one/pressure").status_code == 200


def test_http_workspace_endpoints(client: TestClient) -> None:
    created = client.post(
        "/workspaces", json={"id": "ws-http", "baseImage": "alpine", "durable": True}
    )
    assert created.status_code == 201
    assert client.get("/workspaces/ws-http").status_code == 200
    assert client.get("/workspaces").json()["items"][0]["id"] == "ws-http"

    snap = client.post("/workspaces/ws-http/snapshot")
    assert snap.status_code == 202
    snap_id = snap.json()["id"]

    assert (
        client.post("/workspaces/ws-http/restore", json={"snapshotId": snap_id}).status_code == 200
    )
    assert client.post("/workspaces/ws-http/restore", json={}).status_code == 422

    # write an artifact in the scratch overlay, then promote it
    svc: RuntimeService = client.app.state.service
    (svc.workspace_manager.scratch_path("ws-http") / ".artifacts" / "r.txt").write_text(
        "x", encoding="utf-8"
    )
    promoted = client.post("/workspaces/ws-http/promote", json={"paths": [".artifacts/r.txt"]})
    assert promoted.status_code == 200
    assert promoted.json()["promoted"][0]["path"] == ".artifacts/r.txt"

    valid = client.post("/workspaces/ws-http/validate")
    assert valid.status_code == 200 and valid.json()["valid"] is True

    assert (
        client.request(
            "DELETE", "/workspaces/ws-http", params={"graceSeconds": 0, "force": True}
        ).status_code
        == 202
    )
    assert client.get("/workspaces/ws-http").status_code == 404


def test_http_probe_endpoints(client: TestClient) -> None:
    assert client.get("/healthz/live").status_code == 200
    assert client.get("/healthz/ready").status_code == 200
    assert client.get("/healthz/startup").status_code == 200
    assert "agent_runtime" in client.get("/metrics").text


def test_websocket_events(client: TestClient) -> None:
    client.post("/agents", json=SPEC)
    with client.websocket_connect("/agents/agent-one/events") as ws:
        first = ws.receive_json()
        assert first["type"] == "state"
        ws.send_text("ping")
        assert ws.receive_json()["type"] == "pong"


def test_websocket_unknown_agent(client: TestClient) -> None:
    with client.websocket_connect("/agents/ghost/events") as ws:
        assert ws.receive_json()["type"] == "error"
