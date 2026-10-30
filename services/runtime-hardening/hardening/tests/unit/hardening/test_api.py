"""Unit tests for the control-plane API (spec §2.1, §8)."""

from __future__ import annotations

from fastapi.testclient import TestClient

from runtime.hardening.api import RuntimeApp
from runtime.hardening.models import IsolationTier, WorkloadClass


class _FakeRuntime:
    """Replaces DockerRuntime in tests (no docker daemon needed)."""

    name = "runc"

    def __init__(self) -> None:
        self.started: list[str] = []
        self.stopped: list[str] = []

    def start(self, spec) -> str:
        self.started.append(spec.agent_id)
        return f"container-{spec.agent_id}"

    def stop(self, container_id: str, *, grace_seconds: int = 30) -> None:
        self.stopped.append(container_id)

    def pause(self, container_id: str) -> None:
        pass

    def resume(self, container_id: str) -> None:
        pass

    def status(self, container_id: str) -> str:
        return "running"

    def logs(self, container_id: str, tail: int = 200) -> str:
        return ""

    def inspect_hardening(self, container_id: str) -> dict:
        return {}


def _make_app() -> tuple[RuntimeApp, TestClient, _FakeRuntime]:
    app = RuntimeApp()
    fake = _FakeRuntime()
    app.runtime = fake  # type: ignore[assignment]
    # Use a tmp cgroup root so limits apply cleanly.
    import tempfile
    from pathlib import Path

    root = Path(tempfile.mkdtemp(prefix="test-cgroup-"))
    (root / "agent.slice").mkdir(parents=True, exist_ok=True)
    (root / "agent.slice" / "cgroup.subtree_control").write_text(
        "+cpu +memory +io +pids", encoding="utf-8"
    )
    app.resources.root = root
    return app, TestClient(app.app), fake


def test_health_probes() -> None:
    _, client, _ = _make_app()
    assert client.get("/healthz/live").status_code == 200
    assert client.get("/healthz/ready").status_code == 200
    assert client.get("/healthz/startup").status_code == 200


def test_metrics_endpoint() -> None:
    _, client, _ = _make_app()
    resp = client.get("/metrics")
    assert resp.status_code == 200
    assert "harbor_" in resp.text


def _spec(**overrides):
    base = {
        "name": "build-farm",
        "isolationTier": IsolationTier.BASELINE_RUNC.value,
        "image": "harbor/base",
        "resourceClass": "trusted",
        "labels": {"harbor.hardening/isolation": WorkloadClass.TRUSTED.value},
    }
    base.update(overrides)
    return base


def test_create_and_get_agent() -> None:
    _, client, fake = _make_app()
    resp = client.post("/agents", json=_spec())
    assert resp.status_code == 201, resp.text
    agent = resp.json()
    assert agent["state"] == "running"
    assert agent["runtimeClass"] == "runc"
    assert agent["containerId"].startswith("container-")
    got = client.get(f"/agents/{agent['id']}")
    assert got.status_code == 200
    assert got.json()["id"] == agent["id"]
    assert "a1" in fake.started or agent["id"] in fake.started


def test_admission_rejects_untrusted_on_runc() -> None:
    """AC-1 via API: untrusted workload requesting runc is rejected."""
    _, client, _ = _make_app()
    spec = _spec(
        isolationTier=IsolationTier.BASELINE_RUNC.value,
        labels={"harbor.hardening/isolation": WorkloadClass.UNTRUSTED.value},
    )
    resp = client.post("/agents", json=spec)
    assert resp.status_code == 422


def test_budget_conflict_returns_409() -> None:
    """AC-4: budget-exceeding child returns 409."""
    from runtime.hardening.models import BudgetLimits, MemoryLimits

    app, client, _ = _make_app()
    app.resources.parent_budget = BudgetLimits(memory=MemoryLimits(maxBytes=1, swapMaxBytes=1))
    resp = client.post(
        "/agents",
        json=_spec(resources={"memory": {"maxBytes": 1024, "swapMaxBytes": 1024}}),
    )
    assert resp.status_code == 409


def test_pause_resume_flow() -> None:
    _, client, _ = _make_app()
    agent = client.post("/agents", json=_spec()).json()
    assert client.post(f"/agents/{agent['id']}/pause").status_code == 202
    assert client.get(f"/agents/{agent['id']}").json()["state"] == "paused"
    assert client.post(f"/agents/{agent['id']}/resume").status_code == 202
    # Resume on a non-paused agent -> 409.
    assert client.post(f"/agents/{agent['id']}/resume").status_code == 409


def test_stop_and_delete() -> None:
    _, client, fake = _make_app()
    agent = client.post("/agents", json=_spec()).json()
    assert client.post(f"/agents/{agent['id']}/stop").status_code == 202
    assert client.delete(f"/agents/{agent['id']}").status_code == 202
    assert client.get(f"/agents/{agent['id']}").status_code == 404


def test_workspace_lifecycle() -> None:
    _, client, _ = _make_app()
    resp = client.post("/workspaces", json={"baseImage": "img", "scratchBytes": 1024})
    assert resp.status_code == 201, resp.text
    ws = resp.json()
    assert ws["state"] == "ready"
    snap = client.post(f"/workspaces/{ws['id']}/snapshot")
    assert snap.status_code == 202
    validate = client.post(f"/workspaces/{ws['id']}/validate")
    assert validate.status_code == 200
    assert validate.json()["valid"] is True
    assert client.delete(f"/workspaces/{ws['id']}").status_code == 202


def test_workspace_restore_checksum_422() -> None:
    app, client, _ = _make_app()
    ws = client.post("/workspaces", json={"baseImage": "img"}).json()
    snap = client.post(f"/workspaces/{ws['id']}/snapshot").json()
    # Mutate the workspace after snapshot.
    path = app.workspaces.workspace_path(ws["id"])
    (path / "scratch" / "mutate.txt").write_text("x", encoding="utf-8")
    resp = client.post(f"/workspaces/{ws['id']}/restore", json={"snapshotId": snap["id"]})
    assert resp.status_code == 422


def test_status_endpoint() -> None:
    _, client, _ = _make_app()
    agent = client.post("/agents", json=_spec()).json()
    resp = client.get(f"/agents/{agent['id']}/status")
    assert resp.status_code == 200
    assert resp.json()["circuitBreaker"] == "closed"
    assert resp.json()["degradationMode"] == "full"


def test_resource_endpoints() -> None:
    """GET/PUT/PATCH limits, usage, pressure (Resources tag)."""
    _, client, _ = _make_app()
    agent = client.post("/agents", json=_spec()).json()
    aid = agent["id"]

    limits = {
        "cpu": {"quotaMicros": 100_000, "periodMicros": 100_000},
        "memory": {"maxBytes": 2048, "swapMaxBytes": 2048},
        "pids": {"max": 128},
    }
    put = client.put(f"/agents/{aid}/limits", json=limits)
    assert put.status_code == 200, put.text
    assert put.json()["cpu"]["quotaMicros"] == 100_000
    assert put.json()["memory"]["swapMaxBytes"] == 2048

    patch = client.patch(
        f"/agents/{aid}/limits", json={"cpuQuotaMicrosDelta": 50_000, "pidsMaxDelta": 64}
    )
    assert patch.status_code == 200
    assert patch.json()["cpu"]["quotaMicros"] == 150_000

    get = client.get(f"/agents/{aid}/limits")
    assert get.status_code == 200

    usage = client.get(f"/agents/{aid}/usage")
    assert usage.status_code == 200
    assert usage.json()["pids"]["current"] >= 0

    pressure = client.get(f"/agents/{aid}/pressure")
    assert pressure.status_code == 200

    metrics = client.get(f"/agents/{aid}/metrics")
    assert metrics.status_code == 200
    assert "harbor_" in metrics.text


def test_agent_logs_endpoint() -> None:
    _, client, _ = _make_app()
    agent = client.post("/agents", json=_spec()).json()
    resp = client.get(f"/agents/{agent['id']}/logs", params={"tail": 10})
    assert resp.status_code == 200
    assert resp.text == ""


def test_agent_health_and_not_found() -> None:
    _, client, _ = _make_app()
    agent = client.post("/agents", json=_spec()).json()
    assert client.get(f"/agents/{agent['id']}/health").status_code == 200
    assert client.get("/agents/missing").status_code == 404
    assert client.get("/agents/missing/usage").status_code == 404
    assert client.delete("/workspaces/missing").status_code == 404


def test_create_agent_server_generated_id() -> None:
    _, client, _ = _make_app()
    spec = _spec()
    spec.pop("id", None)
    resp = client.post("/agents", json=spec)
    assert resp.status_code == 201
    assert resp.json()["id"].startswith("agent-")


def test_duplicate_agent_id_409() -> None:
    _, client, _ = _make_app()
    spec = _spec()
    spec["id"] = "dup-agent-1"
    assert client.post("/agents", json=spec).status_code == 201
    assert client.post("/agents", json=spec).status_code == 409


def test_workspace_list_and_promote() -> None:
    app, client, _ = _make_app()
    ws = client.post("/workspaces", json={"durable": True}).json()
    scratch = app.workspaces.workspace_path(ws["id"]) / "scratch"
    (scratch / ".artifacts").mkdir(parents=True, exist_ok=True)
    (scratch / ".artifacts" / "out.txt").write_text("data", encoding="utf-8")
    resp = client.post(f"/workspaces/{ws['id']}/promote", json={"paths": [".artifacts/out.txt"]})
    assert resp.status_code == 200
    assert resp.json()["promoted"][0]["checksum"]
    listing = client.get("/workspaces")
    assert listing.status_code == 200
    assert listing.json()["items"]


def test_workspace_snapshot_restore_ok() -> None:
    _, client, _ = _make_app()
    ws = client.post("/workspaces", json={"baseImage": "img"}).json()
    snap = client.post(f"/workspaces/{ws['id']}/snapshot").json()
    resp = client.post(f"/workspaces/{ws['id']}/restore", json={"snapshotId": snap["id"]})
    assert resp.status_code == 200
    assert resp.json()["state"] == "ready"


def test_problem_details_for_404() -> None:
    _, client, _ = _make_app()
    resp = client.get("/agents/ghost")
    assert resp.status_code == 404
    assert resp.headers["content-type"].startswith("application/problem+json")
