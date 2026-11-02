# Security design: short-lived tickets for SSE and WebSocket streams

Status: **proposal — not implemented**. Tracking issue: #209. No production auth changes are authorized by this document.

## Threat and boundaries

Long-lived API keys must not appear in streaming URLs, browser history, reverse-proxy access logs or observability labels. Both SSE (EventSource) and WebSocket handshakes require browser-compatible authentication. Existing authentication, role-based authorization and access-log redaction must continue to operate during migration. Do not assume that URL query strings are secret even over TLS.

## Proposed protocol

1. A client sends an authenticated **POST** request to a stream-ticket endpoint, carrying the existing credential in the supported authorization header (not the URL). The endpoint checks the caller's authorization to read the specific run/session, validates origin where appropriate, rate-limits requests and issues a cryptographically unpredictable ticket.
2. A ticket is scoped to **one principal, one run/session, one stream protocol, one audience**, with a short expiry (proposed upper bound **30 seconds before first redemption**; configurable only downward without security review). Store only a digest of the ticket, never the raw value, in durable/shared storage. Prevent issuance for unauthorized runs.
3. The streaming handshake may present the ticket, since browser APIs constrain custom request headers. The gateway atomically consumes it, validates scope, expiry, run ownership/RBAC and protocol, and rejects replay. No fallback to long-lived API keys in stream URLs.
4. After the handshake, stream lifetime and revocation obey existing session/run authorization policy; explicitly define reconnect behavior: obtain a **fresh** ticket for every new connection. SSE `Last-Event-ID` must not bypass authorization or ticket redemption.
5. Ensure all proxies, framework access logs, traces, metrics and exception reports redact query strings (not just an `api_key` parameter). Set `Cache-Control: no-store` on ticket responses; avoid logging response bodies and ticket digests. The browser must not persist tickets in localStorage or URLs beyond the connection attempt.

## Failure behavior

- Missing, expired, wrong-run, wrong-principal, wrong-protocol, revoked or already consumed tickets: fail closed (401/403 as appropriate), with no secrets in error bodies.
- Ticket store unavailable: fail closed; do not bypass to existing API-key URL query auth.
- Multiple workers/processes: redemption must be atomic across workers (not a process-local set).
- Explicitly document stream reconnect, process restart and session revocation. Enforce origin validation for browser WebSockets where applicable.

## Implementation sequence and acceptance gates

1. Inventory current SSE and WS endpoints, auth middleware, proxy/logging paths and callers; identify any existing URL credentials before changing behavior.
2. Specify endpoint request/response schema, ticket store and atomic redemption semantics, expiry, bounded issuance, revocation and migration compatibility.
3. Implement server + frontend behind a default-off feature flag. Test with real browser EventSource/WebSocket clients and existing RBAC policies.
4. Include independent tests: positive stream/reconnect; wrong user/run/protocol; expired/replayed ticket; concurrent double redemption (one winner); revoked session; storage outage; redaction under nginx/proxy and all service entrypoints.
5. Run migration/compose and frontend E2E regression, then obtain independent TESTER, REVIEWER and SECURITY PASS on the exact SHA before enabling the feature.
6. Rollout separately from release or #195 merge; monitor 401/403 rates and reconnect failures, with an explicitly reviewed rollback that does not restore long-lived credentials in URLs.

## Non-goals

No modification to live API authentication, no credential rotation, no automatic enablement, no release/deployment and no changes to external Docker stacks in this design-only PR.

## Verified code inventory (main at 2df465c)

- Browser streaming client: `apps/frontend/src/api/runStream.ts`; both `runWebSocketUrl` and `runEventSourceUrl` currently add an `api_key` query parameter when an API key is supplied.
- Existing browser tests: `apps/frontend/src/api/runStream.test.ts`. Extend them to verify no long-lived credential enters either streaming URL and that each reconnect obtains a fresh scoped ticket.
- Trusted gateway access-log protection: `services/agent-management/agent_management/trusted_gateway_serve.py` documents filtering query-string `api_key` and Authorization values. This does **not** establish that every proxy or telemetry sink strips full query strings; verify end-to-end separately.
- Existing realtime/server checks: `services/orchestration-server/tests/test_realtime_events.py` and `services/runtime-hardening/tests/security/runtime/test_security_ws_auth.py` should be part of regression coverage.

This inventory is a starting point, not proof that all server endpoints or log sinks have been audited. Identify their real handlers and authentication dependencies before implementation.

## Verified implementation integration points (2026-11-02)

The concrete server and browser code paths are:

| Concern | Current location | Required ticket change |
| --- | --- | --- |
| Browser WebSocket/SSE URLs | `apps/frontend/src/api/runStream.ts`: `runWebSocketUrl`, `runEventSourceUrl`, `RunEventStream` | Obtain a distinct ticket before **each** connection attempt, including SSE fallback and reconnect. Never place `apiKey` in the streaming URL when ticket mode is enabled. |
| WebSocket authorization | `services/orchestration-server/orchestration_server/api.py`: `_ws_read_authorized`, `stream_run_events_ws` | Validate and consume the run- and protocol-scoped ticket **before** `websocket.accept()`. Existing role resolution alone does not provide one-time replay protection. |
| SSE authorization | `packages/shared/auth_middleware.py`: `AuthMiddleware._extract_api_key` (GET-query fallback), and `api.py` SSE route | Ticket validation must be integrated before streaming response creation; the current GET fallback is not a ticket validator. Preserve header-based auth for other HTTP routes. |
| API key roles | `packages/shared/auth_middleware.py`: `resolve_api_key_roles`, `AuthContext` | Issue tickets only to authorized READ principals, using the same authorization semantics, with a stable binding between the issuer and redeemed ticket. |
| Log handling | `packages/shared/auth_middleware.py`: `_ApiKeyFilter` | Extend redaction to the new ticket parameter and verify full query sanitization at ingress/proxy. Do not log raw tickets or digests. |

### Proposed initial API contract (pending architecture/security review)

`POST /api/v1/workflows/runs/{run_id}/stream-tickets`, authenticated using the existing header-based API key mechanism and requiring READ authorization.

Request: `{"transport":"websocket"|"sse"}`. Response (200, `Cache-Control: no-store`): `{"ticket":"<opaque>","expires_in":30}`. The response must not contain an API key. Error responses: 401 for unauthenticated requests; 403 for insufficient run authorization; 404 if the run is not visible to the principal; 429 for rate limiting; 503 when the ticket store is unavailable. Existing API error conventions take precedence if they conflict with these suggested status codes.

The streaming handshake submits `stream_ticket=<opaque>` with its run path and existing `after` cursor. Redemption must atomically check digest, expiry, unconsumed state, run, principal/authorization policy and transport, then consume the ticket in one transaction. A second redemption or a redemption for the wrong run/transport fails even if concurrent. Never silently treat an invalid ticket as a legacy `api_key`.

**Migration gate:** default-off feature flag, no production activation in this phase; browser and backend must be enabled together. Define how authorization is rechecked on long-lived streams, how multi-process workers share ticket state and how ticket revocation works before implementing. The historical long-lived URL key fallback must not be the rollback strategy.

### Minimum acceptance tests tied to current code

1. POST without credentials / without READ permission / unknown or inaccessible run: rejected without exposing a ticket.
2. Ticket issued for WebSocket cannot open SSE and vice versa; a ticket for run A cannot read run B.
3. Expired, already redeemed and revoked tickets fail closed; simultaneous redemptions have exactly one winner.
4. Ticket storage outage yields a closed failure, never a fallback to a long-lived URL API key.
5. Browser WebSocket-first, SSE fallback and timed reconnect each obtain fresh credentials, retain `after` resume semantics and do not reveal secrets in errors.
6. Real access formatter, reverse proxy and error telemetry do not capture `stream_ticket` values, including encoded parameter names.
7. Existing header-authenticated REST requests and role boundaries retain their current behavior with ticket mode disabled.
