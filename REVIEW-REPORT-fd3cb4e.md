# REVIEW-REPORT-fd3cb4e — Independent Code Review

- **Task:** t_e0105ed1 (REVIEW-VERIFY-2)
- **Reviewer:** sdlc-reviewer (independent; did not implement the changes)
- **Repository:** /mnt/data/multi-agent-workflow
- **Workspace:** dir @ /mnt/data/multi-agent-workflow
- **Branch:** integration/mvp-v1
- **Snapshot commit (HEAD, verified):** fd3cb4e7874e20434e03d2cc3a9167acbd64fe81
- **Review range:** c8e9e4f..fd3cb4e (7 commits)
- **Working tree:** tracked-clean; only pre-existing untracked helper artifacts present. No `M` entries. Guard PASS.
- **Verdict:** **APPROVED** — 0 blocking findings.

---

## 0. Guard / candidate identity

```
git branch --show-current   -> integration/mvp-v1        (expected: integration/mvp-v1)
git rev-parse HEAD          -> fd3cb4e7874e20434e03d2cc3a9167acbd64fe81 (expected: fd3cb4e...)
git status --short          -> only untracked (SECURITY-REPORT-*.md, scan_secrets.py,
                               security-gate-output.json, verify_final.py,
                               orchestration-server/{check_openapi_match,validate_openapi}.py)
```

Tracked files clean; tests were executed at HEAD fd3cb4e, so the reviewed candidate matches
the executed evidence. No source/test file was modified during review (read-only review).

Range (git log --oneline c8e9e4f..fd3cb4e):

```
fd3cb4e fix(security): authenticate WebSocket /agents/{id}/events (SEC-001)
fd3aa3b fix(security): enforce role-based authorization on quality-gates and runtime-hardening (SEC-001)
2b11cf4 docs(MVP-ROOT): record MVP-shell (src/mvp) as out-of-scope
ec2345e chore(C3): full backend+frontend pass + snapshot completeness
63a6bb8 feat(security): HSTS + HTTP->HTTPS enforcement (SEC-002, part 2)
ed39b97 feat(security): TLS config fields + uvicorn ssl wiring (SEC-002, part 1)
bac9f40 feat(security): envelope encryption for auth_config (SEC-004) + AuthMiddleware on quality-gates (SEC-001)
```

This range is the REWORK remediation for the blockers raised in SECURITY-REPORT-c8e9e4f.md
(SEC-001 quality-gates auth, SEC-002 TLS/HSTS, SEC-004 encryption wiring) plus the
SECURITY-REPORT-fd3aa3b.md WebSocket blocker.

## 1. What was verified (independently)

Actual diff of every changed file was read (`git diff c8e9e4f..fd3cb4e`), including
surrounding code and consumers. Test suites were re-executed from the workspace with the
root venv at HEAD, and a standalone probe was run against the real app builders.

### 1.1 Authorization correctness (SEC-001)

- All route decorators across the four services were enumerated and their `Depends(require_*)`
  read from the actual signatures:
  - orchestration-server: 27/27 HTTP routes gated (health -> read, writes -> write, /admin/recover -> admin).
  - agent-management: 31 route decorators gated; only `/health` ungated (exempt by design).
  - quality-gates: 11/11 routes gated (read on reads, write on runs/transition/releases, health read).
  - runtime-hardening: 28/28 HTTP routes gated (reads, writes, DELETE -> admin, healthz/metrics -> read).
- `require_admin`, `require_write`, `require_read` are all imported and used in each file they
  appear in; no dead imports observed for the reviewed symbols.
- Independent live-style probe (TestClient, AUTH_ENABLED=true) on the real quality-gates app:

```
QG /api/v1/gates        no key -> 401
QG /api/v1/gates        read   -> 200
QG POST /api/v1/runs    read   -> 403   (auth enforced before handler)
QG /health              no key -> 200   (exempt)
QG /health/ (trailing)  no key -> 401   (exact-match exempt; fails closed)
QG /openapi.json        no key -> 200   (exempt by design)
```

  Matches the accepted acceptance contract (no key -> 401, read on write -> 403, privileged -> passes).

### 1.2 shared/auth_middleware.py — single source of truth

- `resolve_api_key_roles()` is module-level and is now the only role-resolution path; the
  middleware's `_resolve_roles` delegates to it, and the WebSocket handshake calls the same
  function. Verified: an admin key maps to {admin,write,read}; write -> {write,read}; read -> {read};
  empty/unknown -> empty set (fail-closed). No empty-string key can match because env parsing
  filters empty entries.
- Exempt paths now receive a synthetic read-only `AuthContext`. Exemption is exact set
  membership (`request.url.path in self.exempt_paths`), independently probed: `/health/` and
  other variants are NOT exempt (401), so the synthetic READ role cannot be carried to another
  route (each HTTP request is independent) and cannot reach a write/admin handler.
- `AUTH_ENABLED` default remains `"true"` in code; the four service `conftest.py` set it to
  `"false"` only for test processes. This does not leak into product config or deployment
  defaults; quality-gates is the only conftest change in range.

### 1.3 shared/security_middleware.py — HSTS + HTTP->HTTPS ordering

- Starlette inserts each `add_middleware` at the front of the user-middleware list, so the last
  registered is outermost. The code registers TLSRedirect first, HSTS last -> HSTS wraps the
  redirect, so `call_next` returns the inner 301 and HSTS stamps the header on it. The code
  comment states exactly this and matches observed behavior.
- Independently confirmed on the real agent-management app (TLS enabled, plain HTTP):

```
AM http->https: 301  location=https://testserver/health  HSTS=max-age=31536000; includeSubDomains
```

- HSTS is only added when TLS is enabled (`tls_enabled`), and `ssl_config` is empty when off, so
  non-TLS dev runs are unaffected.

### 1.4 TLS wiring (SEC-002)

- All four `Settings` expose `cert_file`/`key_file`/`ca_file`, `tls_enabled`, `ssl_config`
  (env prefixes ORCH_ / AGENT_MGMT_ / AGENT_RUNTIME_ / QG_). All four entrypoints pass
  `**ssl_config` into uvicorn. Config unit tests pass for each service.

### 1.5 WebSocket authentication (SEC-001-WS remediation)

- `/agents/{agent_id}/events` validates the API key via the shared `resolve_api_key_roles`
  BEFORE `accept()`; the read-equivalent role mirrors `GET /agents/{id}`.
- Independent probe against the real runtime app:

```
WS no key            -> WebSocketDisconnect code 1008 (rejected before accept; no state streamed)
WS read key          -> connects; first frame = {'type':'error','detail':'agent not found'} (no agent created)
```

- `ping`/`pong` and the `AgentNotFound` -> error + close(1008) flow are preserved (author tests
  cover both and pass).
- Only one WebSocket endpoint exists across all services; it is now authenticated.

### 1.6 Envelope encryption (SEC-004)

- Create/update call `encrypt_auth_config`, read path (`build_adapter`) calls
  `decrypt_auth_config`; `ProviderResponse` still excludes `auth_config` (no secret echo).
- `decrypt_auth_config` tolerates legacy plaintext (no `v` key) so pre-existing rows still work.

### 1.7 Test evidence (re-executed at HEAD)

| Suite | Result |
|---|---|
| quality-gates (full) | 55 passed |
| orchestration-server (full) | 44 passed |
| agent-management (full) | 71 passed |
| runtime-hardening (full) | all passed (no failures) |
| runtime-hardening/tests/security | 18 passed |
| agent-management/tests/test_encryption.py | 15 passed |
| root test_hsts_middleware.py + test_tls_config.py | 18 passed |

The security suites drive auth explicitly (monkeypatched module attributes) rather than relying
on the AUTH_ENABLED=false test default, so the gates are genuinely exercised.

---

## 2. Non-blocking findings / notes

1. **KEK development fallback has no production guard** (`agent-management/agent_management/crypto.py:53-73`).
   When `AUTH_ENCRYPTION_KEY` is unset, `_get_kek()` derives the KEK from a hard-coded salt/info
   baked into source. Since the env var is unset by default, the SEC-004 control is effectively
   plaintext-equivalent until an operator sets it, and there is no refuse-to-start check. This is
   documented as dev-only, but a production fail-open. Recommended: refuse to start (or log a hard
   warning and disable encryption-dependent endpoints) when a production environment indicator is
   set and `AUTH_ENCRYPTION_KEY` is absent.
2. **`quality-gates` release approve/reject use `require_write`, not `require_admin`**
   (`quality_gates/api.py`). Approving/rejecting a release is a governance, effectively
   irreversible action; `write` is defensible but is the weakest role that still permits it, and it
   is inconsistent with runtime-hardening where destructive `DELETE` requires admin. No approved
   spec mandates admin here (integration-audit docs define no role matrix), so this is an
   observation, not a violation. Consider `require_admin` for release approval.
3. **WebSocket API key travels in the query string** (`?api_key=`) — it can be captured in reverse-proxy
   access logs, browser history and `Referer`. The code comments the browser-header constraint, but
   prefer the `Sec-WebSocket-Protocol` subprotocol carrier or a short-lived signed ticket in production.
4. **`TLSRedirectMiddleware.trust_proxy=True` by default** honors client-supplied `X-Forwarded-Proto`
   and skips the redirect when it equals `https`. Redirection is not itself a security control (HSTS
   is), so impact is low, but a spoofable header on a directly-exposed service is worth a conditional.
5. **Module docstring of `crypto.py` (lines 12-19) does not match the implementation:** it documents a
   `"tag"` field and a `"nonce"` for the DEK, while the code stores `"dek_nonce"` and no separate tag
   (AESGCM appends the tag to the ciphertext). Documentation only.
6. **Root-level `test_hsts_middleware.py` / `test_tls_config.py` sit outside every per-service suite**
   (no root pytest config / CI manifest), so they only run when invoked explicitly from the repo root.
   They pass, but the HSTS-on-301 and TLS-config coverage is not picked up by the per-service test runs.
   One assertion is also loose: `assert resp.status_code in (200, 404)` for orchestration health.
7. **WS test asserts close code 1008 via TestClient.** A real uvicorn server rejects a
   close-before-accept handshake with HTTP 403, so the wire behavior differs from the asserted code;
   the connection is still rejected (no bypass). Test-fidelity nit only.
8. **`src/mvp/**` is committed as orphaned WIP** and deliberately excluded from vitest/tsc collection
   (tracked by t_452ee514). Documented and non-functional; noted so it is not mistaken for integrated code.

## 3. Residual risk

- No CORS configuration and no rate limiting on the APIs (pre-existing, out of this range).
- `/metrics`, `/openapi.json`, `/docs`, `/redoc` remain reachable without credentials by design
  (endpoint inventory + operational metrics disclosure). Low.
- Legacy-migration edge case: `decrypt_auth_config` treats any dict lacking key `v` as plaintext; a
  legacy plaintext config that happens to contain a top-level `"v"` key would raise on decrypt. Low
  likelihood for provider `auth_config` shapes.

## 4. Conclusion

The reviewed range correctly closes the SEC-001 / SEC-002 / SEC-004 blockers for this snapshot:
authorization is enforced (and independently probed) on every HTTP route and the previously open
WebSocket, TLS/HSTS wiring is correct and verified on the 301 path, and envelope encryption is
actually used on provider write/read with no secret echo. Full test suites and the dedicated
security suites pass at HEAD. No blocking defect was found; the items in section 2 are hardening,
consistency and documentation improvements that do not defeat any control.

**VERDICT: APPROVED (0 blocking findings).**
