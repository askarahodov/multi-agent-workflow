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
