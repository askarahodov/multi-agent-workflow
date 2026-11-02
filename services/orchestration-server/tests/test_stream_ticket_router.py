"""Contract tests for the opt-in (not mounted) ticket-issuance router."""
from fastapi import FastAPI
from fastapi.testclient import TestClient

from shared.auth_middleware import AuthContext, Role, require_read
from orchestration_server.stream_ticket_issuer import StreamTicketIssuer
from orchestration_server.stream_ticket_router import create_stream_ticket_router
from orchestration_server.stream_tickets import StreamTicketStore


def client_for(tmp_path, *, authorized=True, store=None):
    store = store or StreamTicketStore(tmp_path / "tickets.db")
    async def can_read_run(auth, run_id):
        return authorized and run_id == "run-1"
    issuer = StreamTicketIssuer(store, can_read_run=can_read_run)
    app = FastAPI()
    app.include_router(create_stream_ticket_router(issuer), prefix="/api/v1")
    app.dependency_overrides[require_read] = lambda: AuthContext(
        api_key="test-header-key", roles={Role.READ}, subject="alice"
    )
    return TestClient(app), store


def test_ticket_endpoint_uses_post_and_returns_no_storeable_response(tmp_path):
    client, store = client_for(tmp_path)
    url = "/api/v1/workflows/runs/run-1/stream-tickets"
    assert client.get(url).status_code == 405
    response = client.post(url, json={"transport": "sse"})
    assert response.status_code == 200
    assert response.headers.get("cache-control") == "no-store"
    assert response.json()["expires_in"] == 30
    assert store.redeem(
        response.json()["ticket"], principal="alice", run_id="run-1", transport="sse"
    )


def test_ticket_endpoint_does_not_expose_other_runs(tmp_path):
    client, _ = client_for(tmp_path)
    response = client.post(
        "/api/v1/workflows/runs/run-2/stream-tickets", json={"transport": "sse"}
    )
    assert response.status_code == 403
    assert response.headers["cache-control"] == "no-store"
    assert response.json() == {"detail": "Stream access denied"}


def test_ticket_endpoint_rejects_invalid_transport_and_extra_fields(tmp_path):
    client, _ = client_for(tmp_path)
    url = "/api/v1/workflows/runs/run-1/stream-tickets"
    assert client.post(url, json={"transport": "unknown"}).status_code == 422
    assert client.post(url, json={"transport": "sse", "api_key": "secret"}).status_code == 422


def test_ticket_endpoint_fails_closed_on_store_outage(tmp_path):
    class FailingStore:
        def issue(self, **kwargs):
            raise RuntimeError("db internal secret")
    client, _ = client_for(tmp_path, store=FailingStore())
    response = client.post(
        "/api/v1/workflows/runs/run-1/stream-tickets",
        json={"transport": "websocket"},
    )
    assert response.status_code == 503
    assert response.headers["cache-control"] == "no-store"
    assert "db internal secret" not in response.text


def test_ticket_endpoint_rate_limit_returns_no_store_and_retry_after(tmp_path):
    client, _ = client_for(tmp_path)
    url = "/api/v1/workflows/runs/run-1/stream-tickets"
    for _ in range(60):
        assert client.post(url, json={"transport": "sse"}).status_code == 200
    response = client.post(url, json={"transport": "sse"})
    assert response.status_code == 429
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["retry-after"] == "60"
    assert "ticket" not in response.json()
