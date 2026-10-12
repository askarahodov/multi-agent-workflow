# ADR-015: Management API Authentication and Authorization

**Status:** Proposed
**Date:** 2026-10-12
**Author:** sdlc-architect (task t_8cf664ab)
**Related:** GAP-ANALYSIS.md (G7), PRD §18, ADR-101 (Gateway), ADR-102 (ownership), ADR-103 (tool policy), ADR-014 (integration)

---

## 1. Context and Problem

GAP-ANALYSIS.md identifies **G7: No auth layer on management APIs; no SSRF guard; secret-storage not deeply audited**.

Current state: All three backend FastAPI apps (`orchestration-server`, `agent-management`, `runtime-hardening`) and `quality-gates` expose **open routes** — no authentication, no authorization.

PRD §18 requires:
- No keys in source, no secrets in logs
- Protect management API incl. network
- No direct DB from UI
- Restrict paths, prevent symlink bypass, limit shell/network
- Validate tool inputs, control git, SSRF check, isolate dangerous exec, audit privileged ops

PRD §19 v1 assumption: **"trusted admin / local mode"** — but this is a deployment assumption, not a code assumption. The code must support auth before any public exposure.

---

## 2. Requirements

| Req | Description |
|-----|-------------|
| R1 | Authentication on all management API endpoints (except health) |
| R2 | Authorization: at minimum, **admin** vs **agent** vs **service** roles |
| R3 | Token-based (JWT) with short expiry, refresh mechanism |
| R4 | Gateway terminates auth (ADR-101) — services trust gateway headers |
| R5 | Service-to-service auth for inter-service calls (ADR-014) |
| R6 | Secret storage isolated from config (ADR-103, PRD §12.3) |
| R7 | Audit log for all privileged operations |

---

## 3. Architectural Decision

### 3.1 Auth Architecture: Gateway-Terminated JWT

```
┌─────────────┐     JWT (HS256/RS256)      ┌─────────────┐
│   Client    │ ─────────────────────────▶ │ API Gateway │
│ (UI, CLI,   │                            │  (nginx)    │
│  Agent)     │                            │             │
└─────────────┘                            └──────┬──────┘
                                                   │
                                    X-User-ID, X-Roles, X-Request-ID
                                                   │
                    ┌──────────────────────────────┼──────────────────────────────┐
                    │                              │                              │
              ┌─────▼─────┐                  ┌─────▼─────┐                  ┌─────▼─────┐
              │Orchestrat.│                  │Agent Mgmt │                  │  Runtime  │
              │  Server   │                  │           │                  │ Hardening │
              └───────────┘                  └───────────┘                  └───────────┘
                    │                              │                              │
                    └──────────────────────────────┼──────────────────────────────┘
                                                   │
                                            Service-to-Service
                                            (mTLS or shared secret)
```

### 3.2 Authentication Flows

#### 3.2.1 Human / UI Login (Session)

1. UI calls `POST /api/v1/auth/login` → Gateway → Auth Service (new minimal service or Orchestrator)
2. Validate credentials → issue **access JWT** (15 min) + **refresh token** (httpOnly cookie, 7 days)
3. Subsequent requests: `Authorization: Bearer <access>` → Gateway validates → forwards headers

#### 3.2.2 Agent / Service Authentication (Machine)

- **Agent Runtime** (ADR-011): Uses **service account JWT** issued at `AgentInstance` creation
- **Inter-service** (ADR-014): **mTLS** (cert per service) OR **shared secret** (simpler for v1)
- **CLI / CI**: Personal access token (PAT) → exchanged for JWT

#### 3.2.3 Token Format (JWT Claims)

```json
{
  "sub": "user:123" | "agent:abc" | "service:orchestrator",
  "roles": ["admin"] | ["agent"] | ["service"],
  "project_id": "uuid" | null,
  "permissions": ["tasks:write", "agents:read", ...],
  "iat": 1234567890,
  "exp": 1234567890,
  "jti": "unique-token-id"
}
```

### 3.3 Authorization Model (Minimal v1)

| Role | Scope | Permissions |
|------|-------|-------------|
| `admin` | Global | All endpoints |
| `project_admin` | Project | All project-scoped endpoints |
| `agent` | Task-scoped | `/tasks/{id}/submit`, `/artifacts`, `/memory` (own scope) |
| `service` | Internal | Inter-service endpoints (`/internal/*`) |

**Policy Enforcement:** At Gateway (nginx `auth_request` to auth service) OR in each service via middleware. **Decision: Gateway terminates, services trust headers.** Simpler, consistent.

### 3.4 Gateway Auth Implementation (nginx + auth_request)

```nginx
# nginx.conf
location /api/v1/ {
    auth_request /_auth;
    auth_request_set $user_id $upstream_http_x_user_id;
    auth_request_set $roles $upstream_http_x_roles;
    auth_request_set $project_id $upstream_http_x_project_id;
    proxy_set_header X-User-ID $user_id;
    proxy_set_header X-Roles $roles;
    proxy_set_header X-Project-ID $project_id;
    proxy_pass http://backend;
}

location /_auth {
    internal;
    proxy_pass http://auth-service:8080/validate;
    proxy_pass_request_body off;
    proxy_set_header Content-Length "";
    proxy_set_header X-Original-URI $request_uri;
    proxy_set_header X-Original-Method $request_method;
}
```

**Auth Service** (minimal, can be part of Orchestrator):
- `POST /validate` — validates JWT, returns 200 + headers or 401
- `POST /login` — issues tokens
- `POST /refresh` — rotates access token
- `POST /pat` — creates personal access tokens

### 3.5 Service-to-Service Auth (ADR-014 Integration)

**Option A: mTLS (recommended for production)**
- Each service has cert/key signed by local CA
- nginx upstream `proxy_ssl_certificate` / `proxy_ssl_certificate_key`
- Services verify peer cert

**Option B: Shared Secret (v1 pragmatic)**
- `SERVICE_AUTH_SECRET` env var shared across services
- Inter-service calls include `Authorization: Service <hmac(timestamp + path + body)>`
- Receiving service verifies HMAC + timestamp skew (< 5 min)

**Decision:** **Option B for v1** (single host, no cert management). Document mTLS as post-v1.

### 3.6 Secret Storage (PRD §12.3, ADR-103)

| Secret Type | Storage | Access |
|-------------|---------|--------|
| JWT signing key | File (`/etc/hermes/jwt.key`), 600, root-only | Auth service reads at startup |
| Provider API keys | `agent_management` `Provider.auth_config` (encrypted at rest) | Agent Mgmt decrypts at runtime |
| Database passwords | `.env` (not in git), file perms 600 | Each service reads own |
| Service auth secret | `.env` shared | All services read |
| Encryption keys | `age` / `sops` encrypted file | Decrypted at deploy |

**Rule:** No secret in `metadata`, `summary`, comments, artifacts, logs (enforced by Quality Gates security scan).

### 3.7 SSRF Guard (PRD §18, ADR-012)

Implemented at **Tool Registry** (`http_request` tool) + **Gateway egress**:

- **Tool level:** Block private IPs, localhost, link-local, metadata endpoints (169.254.169.254)
- **Gateway level:** `deny` all egress except allow-listed domains (config per project)
- **Container level (Runtime Hardening):** nftables egress rules per container cgroup (ADR-103)

---

## 4. Consequences

**Positive:**
- Auth at Gateway = single point, consistent across all services
- Services don't need auth logic (trust headers) — simpler
- JWT short expiry + refresh = limited blast radius
- Service-to-service auth prevents spoofed internal calls
- Secret storage isolated, auditable via security gate

**Negative:**
- New **Auth Service** component (minimal but real)
- nginx config complexity (auth_request, header passing)
- mTLS deferred — shared secret is weaker (mitigated: single host)
- Token revocation not implemented (short expiry mitigates)

**Migration Path:**
1. Add Auth Service + JWT issuance (login/refresh)
2. Configure nginx `auth_request` + header forwarding
3. Update all services to read `X-User-ID` / `X-Roles` headers
4. Add service-to-service HMAC for inter-service calls
5. Enable Gateway SSRF egress allow-list
6. Audit secret storage (security gate)

---

## 5. Rejected Alternatives

| Option | Rejection Reason |
|--------|------------------|
| Auth in each service (middleware) | Duplicated logic; inconsistent; harder to rotate keys |
| OAuth2 / OIDC provider (Keycloak, etc.) | Heavy for v1; JWT + simple auth service sufficient |
| API Key only (no JWT) | No expiry, no roles, no refresh — insufficient for agents |
| mTLS for everything (v1) | Cert management overhead; single host = shared secret OK |
| No auth (trust local mode only) | Violates PRD §18; cannot expose even locally without risk |

---

## 6. Verification

- Auth Service: login → access+refresh → refresh rotates → expiry rejects
- Gateway: valid JWT → 200 + headers; invalid → 401; missing → 401
- Services: read `X-User-ID`/`X-Roles`; reject if missing (defense in depth)
- Inter-service: HMAC valid → 200; invalid/timestamp skew → 401
- SSRF: `http_request` tool blocks private IPs; Gateway egress blocks non-allow-listed
- Secrets: Security gate scans for keys in source/logs/artifacts → PASS
- Audit: All privileged ops (agent create, task submit, gate approve) logged with user_id

---

## 7. Open Questions

1. **Auth Service location:** Separate module or part of `orchestration-server`? Lean toward separate `auth-service` (single responsibility) but can start embedded.
2. **Project-scoped tokens:** JWT carries `project_id`; Gateway enforces project isolation on `/projects/{id}/*` routes?
3. **Agent token lifecycle:** Tied to `AgentInstance` — revoke on instance termination?
4. **Rate limiting:** At Gateway (nginx `limit_req`) per user/IP?

---

*Recorded as part of GAP-ANALYSIS.md response (task t_8cf664ab).*