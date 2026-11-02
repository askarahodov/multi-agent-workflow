# Stream-ticket opt-in rollout and verification (#209)

**Default:** disabled. No production traffic switches unless the release owner
explicitly enables both server and client, after independent security and QA
approval of the exact commit.

## Server

Set `ORCH_STREAM_TICKETS_ENABLED=1` and a durable **shared** SQLite path in
`ORCH_STREAM_TICKET_DATABASE` (mounted at the same path and shared by every
server worker). The default path is for local development only. The ticket
endpoint is `POST /api/v1/workflows/runs/{run_id}/stream-tickets`, authenticates
with the existing `X-API-Key` header, accepts `{"transport":"sse"}` or
`{"transport":"websocket"}`, and replies with an opaque, max-30-second token
and `Cache-Control: no-store`.

In enabled mode SSE/WS accept `stream_ticket` only. Old API keys in stream URLs
are rejected; other REST API requests retain their existing authorization.
One-time consumption is atomic via SQLite. The current product uses global
READ API-key roles, not per-run ACL. Run existence plus current READ permission
is enforced; do not describe this as tenant-scoped authorization.

## Browser

`RunEventStream` supports `streamTickets: true` with an optional `apiKey`
and injected `fetchImpl`. Each WS attempt, SSE fallback and reconnect first
requests a fresh token using POST with the API key in a header, then places
only the ephemeral ticket in the streaming URL. The run monitor opts into this mode only when\n`VITE_STREAM_TICKETS_ENABLED=1` is set at frontend build time. Enable this\nonly together with the server flag, and provide authentication through a\ntrusted integration; the current run-monitor constructor does not inject a\nproduction API credential. Do not ship a long-lived API key
inside a public frontend build or Vite environment variable.

## Risk gates

- Independent QA, code review and Security PASS at the same head SHA.
- End-to-end browser/auth tests under enabled mode, as well as legacy
  compatibility checks with the flag disabled.
- Confirm shared store correctness across workers, reverse-proxy **entire
  query string** stripping/redaction, request/trace/error telemetry and
  rate limits on ticket issuance.
- Explicit operational rollback: switch back to the previously approved
  deployment only after assessing legacy URL-key exposure; disabling the
  feature re-enables legacy stream URL semantics and is not a security-safe
  rollback by itself.
- Active streams are not immediately closed when a key is revoked; revocation
  is checked at issuance and at every new handshake. Add forced stream
  termination if the deployment requires instantaneous revocation.

**Not production-approved.** The feature flag is an engineering integration
switch, not a security sign-off.
