# SECURITY-REPORT — SECURITY-REVERIFY-3 (SEC-001)

- **Task:** t_9f29cab3 (independent re-verification before release)
- **Repository:** /mnt/data/multi-agent-workflow
- **Branch:** integration/mvp-v1
- **Snapshot commit (verified):** `fd3aa3be60f2681c0ccec011742f5e4d322b8039` (REWORK-2, parent t_33037228)
- **Base compared against:** `ec2345e` (prior FAIL snapshot)
- **Working tree:** tracked files clean (`git diff HEAD` empty); only pre-existing untracked helper artifacts remain (SECURITY-REPORT-c8e9e4f.md, scan_secrets.py, security-gate-output.json, verify_final.py, orchestration-server/{check_openapi_match,validate_openapi}.py). None are part of the candidate.
- **Verdict:** **FAIL** — SEC-001 not fully closed: runtime-hardening exposes an **unauthenticated WebSocket** endpoint.

---

## 1. SEC-001 role-based authorization — HTTP routes (PASS)

`Depends(require_*)` per service (independent grep on the four `api.py`):

| service | `Depends(require_` | http route decorators | notes |
|---|---|---|---|
| agent-management/agent_management/api.py | 31 | 32 | +`/health` intentionally exempt |
| orchestration-server/orchestration_server/api.py | 27 | 27 | improved from 14, no degradation |
| quality-gates/quality_gates/api.py | 11 | 11 | `require_admin` dead import removed |
| runtime-hardening/runtime/api.py | 28 | 28 | HTTP routes only |

- **No dead `require_*` imports**: every imported `require_admin/write/read` has at least one `Depends(...)` use in all four files (verified per symbol).
- `/health` (agent-management, quality-gates) is the only ungated HTTP route and matches the middleware `exempt_paths` set — correct.

## 2. Live HTTP probes (real uvicorn servers, AUTH_ENABLED=true)

Servers: quality-gates on 127.0.0.1:18005, runtime-hardening on 127.0.0.1:18002.
Keys: admin=`admkey`, write=`wrikey`, read=`reakey`.

```
QUALITY-GATES
POST /api/v1/runs              no key:401  read:403  write:500*  admin:500*
POST /api/v1/tasks/t1/transition  no key:401  read:403  admin:500*
POST /api/v1/releases/rel-1/approve no key:401 read:403 admin:500*
GET  /api/v1/gates             no key:401  read:200
GET  /health                   no key:200   (exempt)
GET  /openapi.json             no key:200   (exempt)
GET  /docs                     no key:200   (exempt)

RUNTIME-HARDENING
POST   /agents                 no key:401  read:403  write:201
DELETE /agents/a1              no key:401  read:403  write:403  admin:202
GET    /agents                 no key:401  read:200
GET    /healthz/live           no key:200   (exempt)
GET    /metrics                no key:200   (exempt)
```
\* 500 = auth passed; handler fails because no pipeline/DB is bound in this probe. Not 401/403 → correct authorization decision.

**Acceptance contract met on all required HTTP endpoints: no key → 401, read key on write endpoint → 403, admin → passes.**

### Path-normalization / bypass attempts (quality-gates)
```
GET  /health/                          no key: 401   (not exempt — exact match)
GET  /health/../api/v1/gates           no key: 401   (not normalized into exempt)
POST /health/../api/v1/runs            no key: 401
POST /health/../api/v1/runs  read key: 404   (never authorized onto the write handler)
GET  /health%2f..%2fapi%2fv1%2fgates   no key: 401
```
No bypass. Exemption is exact set membership; `..`/encoded variants are not treated as exempt.

## 3. Executable auth tests (PASS)

| suite | result |
|---|---|
| quality-gates/tests/test_security_auth.py | 10 passed |
| orchestration-server/tests/test_security_auth.py | 10 passed |
| runtime-hardening/tests/security/runtime/test_security_auth.py | 11 passed |
| agent-management/tests/test_security_auth.py | 8 passed |

Orphaned-`.pyc` check: `runtime-hardening/tests/security/runtime/` contains only `test_security_auth.py` (tracked) plus its matching `__pycache__` — no `.pyc` without a `.py`. No `.pyc` is tracked anywhere (`git ls-files '*.pyc'` empty).

Full regression suites: quality-gates 55, runtime-hardening 128, orchestration-server 44, agent-management 71 — all green.

## 4. SEC-002 / SEC-003 / SEC-004 non-regression (PASS)

REWORK-2 did not touch their implementation files.
- SEC-002 (TLS/HSTS): `shared/security_middleware.py` intact; `test_hsts_middleware.py`+`test_tls_config.py` → 18 passed.
- SEC-003 (deny-by-default tool policy): intact; `agent-management/tests/test_tool_policy.py` → 10 passed.
- SEC-004 (auth_config envelope encryption): `agent_management/crypto.py` + services intact; crypto/auth selection → 23 passed.

## 5. Secret & dependency scan (PASS)

- Secret-pattern scan over the 10 changed files: only benign key-handling identifiers (`X-API-Key`, `ADMIN_API_KEYS`, hash-of-key helper). No embedded credentials/tokens/keys.
- No dependency manifests changed (`pyproject.toml`/`uv.lock`/`package-lock.json` untouched by REWORK-2) → no new supply-chain surface.

## 6. Snapshot completeness (PASS)

`git cat-file -e HEAD^{commit}` OK; `git ls-tree -r HEAD` = 258 entries; working tree tracked-clean.

---

## BLOCKING FINDING

### SEC-001-WS (medium, blocking) — unauthenticated WebSocket on runtime-hardening

- **File:** `runtime-hardening/runtime/api.py` (lines ~692–716), root cause `shared/auth_middleware.py:50` (`AuthMiddleware(BaseHTTPMiddleware)` — HTTP-only).
- **Evidence (live, AUTH_ENABLED=true):**
  ```
  $ python probe_ws.py  (websockets.connect ws://127.0.0.1:18002/agents/a1/events, no API key)
  WS CONNECTED WITHOUT API KEY (unauthenticated access)
  first frame: {"type":"error","detail":"agent not found"}
  ```
  With a valid agent id the endpoint streams `{"type":"state","agentId","state","degradationMode"}`.
- **Impact:** `GET /agents/{id}` requires `require_read`, but its WebSocket twin `/agents/{agent_id}/events` requires nothing. Unauthenticated clients can enumerate agent ids and read agent lifecycle state / degradation mode. Violates threat-model trust boundary #5 (Control Plane ↔ Data Plane API authentication) and the S1 mitigation ("API auth"). Trivial to exploit (no creds, network reach only). Confidentiality impact low–medium; also enables cheap socket accumulation.
- **Note:** pre-existing (present unchanged at `ec2345e` and earlier; never assessed in prior SECURITY reports). It is not a REWORK-2 regression, but SEC-001's requirement ("authorization on all API routes") is not met while it stands.
- **Remediation:** authenticate the WebSocket handshake (validate API key from header/query/subprotocol before `accept()`, enforce `require_read`-equivalent role) or move the event stream behind an authenticated HTTP/SSE endpoint.

## Non-blocking findings / notes

### SEC-001-EXEMPT (low, non-blocking) — synthetic READ context on exempt paths
REWORK-2 added, for the 8 exact `exempt_paths` (`/health`, `/healthz/{live,ready,startup}`, `/metrics`, `/docs`, `/openapi.json`, `/redoc`), an injected `AuthContext(roles={READ})` so health/metrics endpoints carrying `Depends(require_read)` resolve instead of 500-ing. Judgment:
1. **Acceptable.** The synthetic role is confined to requests whose path exactly equals a read-only endpoint; each HTTP request is independent, so the role cannot be carried to another route, and every write/admin route still enforces its own gate. It grants no more than the pre-existing "exempt from 401" behaviour and prevents a 500 regression.
2. **Exact match confirmed independently** (not on trust): `request.url.path in self.exempt_paths` is set membership; live probes above show `/health/`, `/health/../api/v1/gates`, encoded variants all → 401, none reached an exempt branch or a write handler.
3. `/metrics`, `/openapi.json`, `/docs`, `/redoc` are reachable without credentials → endpoint-inventory + operational-metric disclosure. Severity **low**; non-blocking. Recommended hardening (not required to pass): disable `docs`/`openapi.json`/`redoc` in production, or expose `/metrics` behind auth / on a separate port.

### SEC-001-HEALTH (informational)
`/health` in agent-management and quality-gates remains unauthenticated by design (exempt path). Acceptable for liveness.

---

## Verdict

**FAIL.** SEC-002/003/004 remain green and all HTTP role-authorization acceptance criteria are met (grep counts, live 401/403/pass probes, executable tests, no dead imports, no path bypass, clean secret/dependency/snapshot checks). However SEC-001 is not fully closed: `runtime-hardening` exposes an **unauthenticated WebSocket** `/agents/{agent_id}/events`. Per gate policy a confirmed medium broken-access-control finding is blocking → the finding returns to **REWORK**, not RELEASE.
