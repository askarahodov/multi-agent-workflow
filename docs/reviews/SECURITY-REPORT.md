# SECURITY-REPORT.md

## Security Review of MVP v1 Implementation

**Date:** 2026-10-12
**Reviewer:** sdlc-security
**Branch:** wt/t_db1ca632
**Base Commit:** 208d316 (from parent task t_b0269195)

---

## Executive Summary

This security review covers the MVP v1 implementation across three core services:
- **orchestration-server** - Platform-owned orchestration with durable execution
- **agent-management** - Agent definitions, instances, provider abstraction, tool policies
- **runtime-hardening** - Hardened container runtime for agent sandboxing
- **quality-gates** - Automated quality gate pipeline (tester, reviewer, security, release-prep)

**Overall Verdict:** **FAIL** - Critical security findings require remediation before merge.

---

## Findings

### SEC-001: CRITICAL - No Authentication/Authorization on Any API

**Severity:** critical  
**Category:** Authentication and Authorization  
**Files Affected:**
- `services/orchestration-server/orchestration_server/api.py`
- `services/agent-management/agent_management/api.py`
- `services/runtime-hardening/runtime/api.py`
- `services/quality-gates/quality_gates/api.py`

**Evidence:** All REST endpoints across all four services are publicly accessible with no authentication, authorization, or token validation. The `AuthenticationError` class exists in `orchestration_server/errors.py` but is never raised or enforced.

**Impact:** Any network caller can:
- Create/delete projects, workspaces, contracts, agents, workflows
- Execute arbitrary agent tasks and control workflow execution
- Register/manage LLM providers with API keys (stored in `auth_config`)
- Create tool policies with permissive permissions
- Spawn containers with arbitrary images and resource limits
- Access agent logs, metrics, and workspace contents
- Trigger release candidates and approve/reject them

**Remediation:** Implement authentication middleware (JWT/OAuth2/mTLS) on all services. At minimum:
1. Add FastAPI dependency for token validation on all mutating endpoints
2. Implement role-based access control (admin, operator, agent)
3. Enforce agent identity verification for task claim/submit/fail/block
4. Protect provider `auth_config` (LLM API keys) with encryption at rest
5. Document the authentication scheme in ADR

**Blocking:** YES

---

### SEC-002: CRITICAL - No TLS/SSL Enforcement

**Severity:** critical  
**Category:** Insecure Defaults  
**Files Affected:** All service configurations

**Evidence:** No service configures TLS. All `uvicorn` apps run on plain HTTP. `Settings` classes have no TLS cert/key paths. No HSTS, no secure cookie flags (not applicable but indicative).

**Impact:** All API traffic (including provider API keys in `auth_config`, agent outputs, workspace data) is transmitted in cleartext. Vulnerable to MITM, credential theft, and data exfiltration.

**Remediation:**
1. Add TLS configuration to all `Settings` classes (cert_file, key_file, ca_file)
2. Configure `uvicorn` with `--ssl-certfile`/`--ssl-keyfile` in production
3. Enforce HTTPS-only in production deployments
4. Add HSTS headers via middleware

**Blocking:** YES

---

### SEC-003: HIGH - Permissive Default Tool Policy

**Severity:** high  
**Category:** Insecure Defaults  
**File:** `services/agent-management/agent_management/tool_policy.py:106-112`

**Evidence:** `DEFAULT_PERMISSIVE_POLICY` grants `"**"` (all paths) for `fs_read`/`fs_write`, `"*"` for `git`/`shell`/`network`. This policy is exported and could be used as a default when no explicit policy is configured.

**Impact:** If an agent instance is created without an explicit tool policy and falls back to this default, it gains full filesystem read/write, arbitrary shell command execution, git operations, and unrestricted network access.

**Remediation:**
1. Remove `DEFAULT_PERMISSIVE_POLICY` or rename to `DANGEROUS_PERMISSIVE_POLICY` with explicit warning
2. Make the secure default `deny-all` (empty lists for all kinds)
3. Require explicit tool policy assignment for every agent instance
4. Add validation that rejects agent creation without a tool policy

**Blocking:** YES

---

### SEC-004: HIGH - Provider API Keys Stored in Plaintext

**Severity:** high  
**Category:** Data Leakage  
**Files:**
- `services/agent-management/agent_management/models.py:57` (`auth_config: Mapped[dict | None] = mapped_column(JSON, nullable=True)`)
- `services/agent-management/agent_management/schemas.py:23,39` (`auth_config: Optional[Dict[str, Any]]`)

**Evidence:** Provider `auth_config` (containing LLM API keys, bearer tokens, etc.) is stored as plaintext JSON in the database. The schema comment states "Secret material in `Provider.auth_config` is never echoed back in responses" but there is no encryption at rest.

**Impact:** Database compromise exposes all LLM provider credentials. Insider threat or backup leakage exposes secrets.

**Remediation:**
1. Encrypt `auth_config` at rest using envelope encryption (DEK per provider, KEK from KMS/env)
2. Decrypt only when building adapter config in `ProviderService.build_adapter()`
3. Ensure `auth_config` is never logged or included in API responses (verify current behavior)
4. Add key rotation capability

**Blocking:** YES

---

### SEC-005: MEDIUM - No CORS Configuration

**Severity:** medium  
**Category:** Insecure Defaults  
**Files:** All FastAPI app factories (`api.py` in each service)

**Evidence:** No `CORSMiddleware` is added to any FastAPI application. Default FastAPI behavior allows all origins for browser-originated requests if not configured.

**Impact:** If a browser-based frontend is deployed on a different origin, it may be blocked (secure) or allowed (if wildcard added later without review). Current state is undefined.

**Remediation:** Explicitly configure `CORSMiddleware` with:
- `allow_origins`: explicit list of trusted frontend origins
- `allow_credentials`: false (unless using cookie auth)
- `allow_methods`: explicit list
- `allow_headers`: explicit list

**Blocking:** NO (but must be addressed before frontend integration)

---

### SEC-006: MEDIUM - No Rate Limiting on Public APIs

**Severity:** medium  
**Category:** Insecure Defaults  
**Files:** All API entry points

**Evidence:** No rate limiting middleware (e.g., `slowapi`, custom token bucket) is applied to any endpoint. Provider-level `rate_limits` config exists but is only used for outbound LLM calls, not inbound API protection.

**Impact:** DoS via request flooding, credential stuffing on auth endpoints (when added), resource exhaustion.

**Remediation:** Add rate limiting middleware per service:
- Stricter limits on mutating endpoints (POST/PUT/DELETE)
- Per-client (IP/API key) quotas
- Burst allowance with sustained rate caps

**Blocking:** NO (but recommended before production)

---

### SEC-007: MEDIUM - Secret Scanner False Positives in Test Fixtures

**Severity:** medium  
**Category:** Hardcoded Secrets (False Positive)  
**Files:**
- `services/quality-gates/tests/test_security.py`
- `services/quality-gates/tests/test_pipeline.py`
- `services/quality-gates/tests/conftest.py`

**Evidence:** Security gate reports 5 secret hits:
- 3× `AKIA...` (AWS access key pattern) in test files
- 2× `ghp_...` (GitHub PAT pattern) in test files

**Analysis:** These are **intentional test fixtures** using redacted placeholders (`«redacted:AKIA…»`, `FAKE_AWS_KEY = "AKIA" + "0123456789ABCDEF"` assembled at runtime). The test suite deliberately exercises the secret detector. No real secrets are committed.

**Remediation:** 
1. Add test fixture files to `SKIP_FILES` in `security.py` OR
2. Use a `.qg-secrets-ignore` file pattern OR
3. Accept as known test fixtures and document in SECURITY-REPORT

**Blocking:** NO (confirmed false positive)

---

### SEC-008: LOW - Dependency Scanner Uses Demo Advisory List Only

**Severity:** low  
**Category:** Dependency and Supply-Chain Risk  
**File:** `services/quality-gates/quality_gates/gates/security.py:38-44`

**Evidence:** `DEFAULT_ADVISORIES` contains only two dummy entries (`example-vuln-lib`, `legacy-dep`). Real vulnerability scanning requires integration with external advisory feed (OSV, GitHub Advisory, PyPI).

**Impact:** No real vulnerable dependency detection in current configuration.

**Remediation:** Integrate with `pip-audit`, `safety`, or OSV API via `context["advisories"]` injection in CI pipeline.

**Blocking:** NO (but limits effectiveness of security gate)

---

### SEC-009: LOW - No Input Validation on Shell/Git/Network Tool Policies

**Severity:** low  
**Category:** Unsafe Execution  
**File:** `services/agent-management/agent_management/tool_policy.py`

**Evidence:** Tool policy patterns use `fnmatch` for shell commands, git subcommands, and network URLs. No validation that shell commands are from an allowlist of safe binaries, no argument validation, no URL scheme restriction (could allow `file://`, `ssh://`, `gopher://`).

**Impact:** If a policy allows `shell: ["python"]`, an agent could execute `python -c "import os; os.system('rm -rf /')"`. Network patterns like `https://api.example.com/**` don't prevent SSRF to internal metadata services.

**Remediation:**
1. For shell: validate command basename against allowlist, reject shell metacharacters
2. For network: enforce `https://` only, block private IP ranges (RFC1918), block metadata IPs (169.254.169.254)
3. For git: restrict to read-only subcommands by default

**Blocking:** NO (defense-in-depth; tool policy enforcement is a runtime boundary)

---

## Checks Run

| Check | Command | Result | Evidence |
|-------|---------|--------|----------|
| Secret scan | `python run_security_scan.py` (quality-gates security gate) | **FAILED** | 5 potential secrets detected (all test fixtures - false positives) |
| Dependency scan | `python run_security_scan.py` (quality-gates security gate) | **PASSED** | No known-vulnerable dependencies detected (demo advisory list only) |
| AuthZ inspection | Manual code review of all API routers | **FAILED** | Zero authentication/authorization on any endpoint |
| TLS inspection | Manual config review | **FAILED** | No TLS settings in any Settings class |
| Tool policy review | Manual review of `tool_policy.py` | **FAILED** | Permissive default policy exported |
| Provider secret storage | Manual review of models/schemas | **FAILED** | `auth_config` stored as plaintext JSON |

---

## Residual Risk

| Description | Severity | Reason | Recommended Action |
|-------------|----------|--------|-------------------|
| No real vulnerability feed for dependency scanning | low | Demo advisory list only | Integrate OSV/pip-audit in CI before production |
| No rate limiting on APIs | medium | Not implemented | Add slowapi or similar before production |
| No CORS policy defined | medium | Default FastAPI behavior undefined | Explicitly configure CORSMiddleware |
| Tool policy shell/network validation gaps | low | fnmatch-only pattern matching | Harden pattern matching in follow-up |
| Secret scanner noise from test fixtures | medium | Test fixtures trigger patterns | Add test fixture paths to skip list |

---

## Verdict

**Status: FAILED**

### Blocking Findings (must fix before merge):
1. **SEC-001** - No authentication/authorization on any API
2. **SEC-002** - No TLS/SSL enforcement
3. **SEC-003** - Permissive default tool policy
4. **SEC-004** - Provider API keys stored in plaintext

### Non-Blocking (address before production):
- SEC-005: CORS configuration
- SEC-006: Rate limiting
- SEC-008: Real vulnerability feed integration
- SEC-009: Tool policy input validation hardening

### Accepted with Justification:
- **SEC-007** - Secret scanner hits in test fixtures are intentional test data (redacted placeholders assembled at runtime). The security gate correctly detects them; this validates the detector works. No real secrets are committed.

---

## Next Steps

1. **ARCHITECT decision required:** Authentication/authorization architecture (JWT? mTLS? API keys? OIDC?) - this is an architectural security decision per Section 12 of security gate policy.
2. Implement authentication middleware across all four services.
3. Add TLS configuration to all Settings classes.
4. Remove/rename `DEFAULT_PERMISSIVE_POLICY` and enforce explicit tool policy assignment.
5. Encrypt `Provider.auth_config` at rest.
6. Re-run security gate after fixes to verify PASS.

**Do not merge until blocking findings are resolved.**