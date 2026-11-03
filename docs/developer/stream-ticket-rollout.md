# Stream-ticket opt-in rollout and verification (#209)

**Default:** disabled. No production traffic switches unless the release owner
explicitly enables both server and client, after independent security and QA
approval of the exact commit.

## Server

Set `ORCH_STREAM_TICKETS_ENABLED=1` and a durable **shared** SQLite path in
`ORCH_STREAM_TICKET_DATABASE` (mounted at the same path and shared by every
server worker under the **same trusted OS account**). The default path is for
local development only. The SQLite file is created with owner-only
permissions (`0600` on POSIX); startup refuses group/world-readable or
symlinked database paths. Provision an owner-controlled parent directory
(`0700` recommended). For existing operator-owned files, explicitly
`chmod 600` before enabling tickets. A shared network filesystem needs
separate validation of SQLite locking semantics. The ticket
endpoint is `POST /api/v1/workflows/runs/{run_id}/stream-tickets`, authenticates
with the existing `X-API-Key` header, accepts `{"transport":"sse"}` or
`{"transport":"websocket"}`, and replies with an opaque, max-30-second token
and `Cache-Control: no-store`. Issuance is limited to 60 tickets per
principal per 60-second window across workers using the same SQLite file;
over-budget calls return HTTP 429 with `Retry-After: 60`. This is a server-side
per-principal control, not a substitute for proxy/IP-level abuse prevention.

In enabled mode SSE/WS accept exactly one `stream_ticket` query parameter.
Any legacy `api_key` parameter, including empty or duplicated values, and
ambiguous duplicate tickets are rejected before stream authorization.
Other REST API requests retain their existing authorization.
One-time consumption is atomic via SQLite. The current product uses global
READ API-key roles, not per-run ACL. Run existence plus current READ permission
is enforced; do not describe this as tenant-scoped authorization.

## Browser

`RunEventStream` supports `streamTickets: true` with an optional standalone
`apiKey` / `fetchImpl` or an authenticated `ticketProvider`. On every WS
attempt, SSE fallback and reconnect, it requests a fresh token by POST and
places only that ephemeral token in the streaming URL.

The run monitor now requests tickets through the same
`ApiAdapter.issueStreamTicket()` used for REST requests: `HttpAdapter`
automatically reuses its configured `Authorization: Bearer` header, which the
orchestration server accepts as an API credential. The offline mock refuses
ticket issuance. No credential is embedded in the public frontend build.

A trusted runtime can now inject a credential provider without rebuilding or
replacing the client on short-lived token rotation:
`createApiClient({ tokenProvider: async () => getAuthenticatedSessionToken() })`.
The application does **not** provide `getAuthenticatedSessionToken()`: it is
a conceptual integration point that the host identity/session layer must
supply securely. The provider is consulted before every REST request,
including every new ticket request after stream reconnect. Missing/failed
providers fail locally with a sanitized 401, without a network request,
anonymous fallback, or fallback to an old credential. Never persist
credentials in URL parameters, localStorage, Vite variables or static
frontend assets. Use a trusted short-lived session/credential source instead.
The frontend test suite covers UI-to-HTTP-to-WS ticket authorization and
credential renewal on reconnect, but not a production identity provider.

The monitor only enables tickets when `VITE_STREAM_TICKETS_ENABLED=1` is set
at build time, together with the server flag. The default
`createApiClient()` does **not** provide an authenticated runtime session:
a trusted authentication integration must provision the HTTP client
(e.g. by passing a credential received through an approved session flow).
Without that integration the ticket endpoint returns 401, the stream
stops reconnecting, and the run monitor does not switch to unauthorized
snapshot polling or fall back to a long-lived URL credential.
Do not enable production ticket mode without verifying this provisioning
flow and browser integration tests. Never place long-lived keys in public
Vite environment variables or frontend bundles.

## Risk gates

- Independent QA, code review and Security PASS at the same head SHA.
- End-to-end browser/auth tests under enabled mode, as well as legacy
  compatibility checks with the flag disabled.
- Confirm shared store correctness across workers, reverse-proxy **entire
  query string** stripping/redaction, request/trace/error telemetry and
  rate limits on ticket issuance. The shared Uvicorn access-log filter strips
  the entire request query for both legacy and ticket-mode HTTP/WS targets;
  Uvicorn error-log request targets also have their query removed. This does
  **not** configure or prove protection in nginx, ingress, load balancers,
  third-party tracers or externally collected access logs: audit each separately.
- Explicit operational rollback: switch back to the previously approved
  deployment only after assessing legacy URL-key exposure; disabling the
  feature re-enables legacy stream URL semantics and is not a security-safe
  rollback by itself.
- API-key sets are read into worker memory at startup. Rotate keys by
  coordinating restart/reload of **all** workers; otherwise old workers can
  continue accepting revoked credentials on new handshakes.
- Ticket-protected SSE/WS streams now recheck current role and run access
  periodically during active connections (about every two seconds while
  polling normally). On a failed check SSE ends; WebSocket closes with
  policy code 1008. This is not instantaneous revocation: all workers need
  the updated key set and already-sent events cannot be recalled. Legacy
  streams retain existing semantics. Strict cross-worker instantaneous
  revocation needs a separately managed shared revocation signal.
- Verify all workers have synchronized wall clocks for strict 30-second
  ticket expiry. Verify reverse proxies and traces strip complete query
  strings and apply IP-level rate limits before production opt-in.
- Reproduce local backend acceptance with
  `cd services/orchestration-server && python -m pytest tests/test_stream_tickets.py tests/test_stream_ticket_issuer.py tests/test_stream_ticket_integration.py -q`.
  The suite includes independent-process replay and issuance-budget checks;
  it is not a substitute for staging validation with real proxies and users.

**Not production-approved.** The feature flag is an engineering integration
switch, not a security sign-off.
