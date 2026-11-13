# Stream-ticket rollout and acceptance gate (#209)

**Status: opt-in only. Not approved for production.** The disposable Compose
Quality Gate exercises ticket-only event streaming, while the default project
configuration remains unchanged. This is not permission to expose the
authentication-disabled dev stack to the public Internet.

## What changes

The frontend issues a one-time capability through an authenticated
`POST /api/v1/workflows/runs/{run_id}/stream-tickets` request, then sends
only `stream_ticket` (not the long-lived API key) in the WebSocket/SSE URL.
The capability is bound to principal, run, transport and a maximum 30-second
lifetime; the store redeems it atomically. Browser reconnect, including
WebSocket-to-SSE fallback, must obtain **another** ticket rather than reuse
a consumed capability or fall back to an API key in the URL.

Both runtime flags must agree; a mismatched enablement is an outage, never a
reason to append long-lived credentials to a URL.

## Local-only opt-in (no provider charges)

From the repository root on a trusted host:

```sh
ORCH_STREAM_TICKETS_ENABLED=1 VITE_STREAM_TICKETS_ENABLED=1 \
  docker compose --project-directory . -f deploy/compose/dev/docker-compose.yml up --build -d
```

The stock local acceptance procedure remains valid with both flags OFF;
the ticket-only browser case is skipped unless explicitly selected. To test
the alternative protocol locally after starting the stack above:

```sh
cd apps/frontend
MAW_STREAM_TICKET_E2E=1 npx playwright test \
  --config compose.playwright.config.ts \
  --grep 'ticket-only SSE and WebSocket'
```

The CI Quality Gate runs its full default-off Chromium suite first, then
explicitly recreates the two stream services with both flags ON and executes
the ticket-only browser case. Setting only the test selector
without both Compose flags intentionally fails; it never downgrades auth.

The dev overlay writes a private ticket SQLite store under the orchestrator's
container `/tmp`, not the bind-mounted repository. It is disposable and cannot
be used as a multi-node shared ticket service. Do not copy that path to
production or add tickets/API keys to CI artifacts, screenshots or access logs.

For an explicit local return to the original dev setup, stop the stack and
recreate both services with **both flags off**, verifying no clients continue
using ticket-only mode. Do **not** use the legacy URL-key mode as a production
rollback. Production rollback must use an approved fail-closed/polling plan.

## Safe event-stream query bounds

SSE and WS use the same limits: `after` is a nonnegative signed-64-bit
journal cursor, `max_events` is 1–10000 when supplied,
`poll_interval` is greater than zero and at most 10 seconds, and
`idle_timeout` is greater than zero and at most 3600 seconds.
WebSocket additionally rejects duplicate stream-option fields and non-finite
numbers (`nan`, `inf`) **before redeeming the one-time ticket**;
the handshake closes with policy code `1008` and does not reveal a token.
A client may retry a rejected malformed connection with corrected bounds and
its unconsumed capability, subject to the normal 30-second expiry.
The SSE endpoint returns a validation response for an invalid cursor rather
than passing an out-of-range integer to SQLite.

The integration regression intentionally tries invalid bounds against
authenticated ticket-only WebSocket, checks `1008` and then proves that
the original ticket still opens a valid one-event stream. This is a
server-side boundary, not permission to relax proxy/query redaction.

## Acceptance required before production (all mandatory)

1. **TESTER:** real HTTP+Chromium: issuance, WS and SSE frames, stale cursor
   resume, transport fallback, fresh ticket on reconnect, expiry, consumed
   replay denial, cross-run/cross-transport denial and service restart.
2. **REVIEWER:** exact-head CI and browser tests, no bypass to query
   `api_key`, redaction for streamed worker errors and no misleading
   `stream connected` state after RBAC denial.
3. **SECURITY:** header-authenticated issuance with current run visibility;
   current authorization recheck on every handshake and active stream,
   session/key revocation, atomic multi-worker redemption, rate limiting,
   ticket entropy and disk ownership/0600/no-symlink guarantees.
4. **Operations:** durable shared ticket store if multiple workers/replicas
   are used; do not rely on one container's /tmp for HA. Audit all reverse
   proxies, APM, error trackers and access logs so neither
   `stream_ticket` nor `api_key` query values appear. Confirm TLS, no
   cache, security headers, safe rotation and storage recovery.
5. **Approval:** record independent TESTER/REVIEWER/SECURITY signoffs,
   operator-owned rollout and rollback with monitored canary. Never enable
   production as an incidental result of merging this PR.

## Automated evidence

`.github/workflows/quality-gate.yml` enables the two flags only for its
disposable Compose stack. `apps/frontend/e2e/compose-acceptance.spec.ts`
proves same-origin real HTTP issuance, rejection of legacy key URLs,
single-use SSE 200→403, WebSocket event delivery and transport binding.
Server tests in
`services/orchestration-server/tests/test_stream_ticket_integration.py`
cover the authenticated authorization and revocation gates. This combined
evidence is necessary but **not sufficient** for production authorization.

**Stop condition:** any 401/403/429/503 or store failure must not degrade to
long-lived API keys in stream URLs. Polling without credentials in URLs
can be used only when its existing authenticated REST pathway allows it.
