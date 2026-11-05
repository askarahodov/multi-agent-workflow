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
separate validation of SQLite locking semantics. **Keep this file mounted and
private for the entire service lifetime.** On POSIX the file must belong to
its service UID, not merely have mode 0600. Each running server pins the
SQLite file device/inode at initialization and refuses a different file at
the same path (even when the replacement is another private, valid database).
This prevents silent replay-state and issuance-quota resets after replacement.
Restore the original file/inode under operator control; deliberate database
replacement requires a coordinated stop/restart, ticket expiry and security
review. These checks do not eliminate every filesystem path-swap race during
an individual SQLite open: keep parent directories inaccessible to untrusted
writers and do not use mutable/untrusted shared mounts. Each operation rechecks that the
existing database remains a regular, owner-only file and opens it in SQLite
read/write **without create** mode. If an operator removes/unmounts it,
downgrades its permissions, revokes traversal permission on a parent directory,
or substitutes a symlink, issuance and redemption fail closed: ticket issuance/SSE return sanitized HTTP 503 and WebSocket closes
with code 1011. The service must not silently create a new database under the
process umask; restore the original private store and investigate the incident
before restarting. Neither that 503 nor a client reconnect permits falling
back to legacy `api_key` URL credentials. The ticket
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

The stream first attempts WebSocket. If the browser reports a failed
**asynchronous upgrade before `onopen`** (as commonly happens when a proxy
blocks WS), it switches to SSE rather than repeatedly attempting the refused
upgrade. That fallback requests its **own** short-lived SSE ticket; the WS
ticket is never reused across transports. After an SSE connection fails, the
client closes EventSource before its browser-managed auto-reconnect can replay
a consumed ticket, then obtains a new SSE ticket and resumes from the last
valid event ID. A normal established WebSocket that later disconnects still
retries WebSocket; explicitly starting the monitor again resets transport
preference. All retries have a finite budget, and missing/denied credentials
stop ticket acquisition without falling back to legacy URL keys. Stale,
duplicate, out-of-order, cross-run and non-integer event IDs are rejected
before publication to the UI; only positive safe integer IDs advance the
resume cursor. The frontend's transport-injected regression suite covers
these behaviors, but not proxy/ingress behavior on an operator's staging host.

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
  For the attached Uvicorn log filter, exception tracebacks (including cached
  `exc_text`) and Python `stack_info` are also query-stripped before formatter
  append, because redacting only `record.msg` leaves an exception-side leak.
  This remains application-logger protection, not proxy/tracer certification.
  Embedded targets in traceback source expressions and `url=https://...` error
  fields are stripped as well (not only whitespace-leading URL tokens).
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
  The suite includes independent-process replay, issuance-budget checks
  and a real HTTP/SSE/WS outage regression verifying that a missing ticket
  database is never recreated. It is not a substitute for staging validation
  with real proxies and users.

**Not production-approved.** The feature flag is an engineering integration
switch, not a security sign-off.
