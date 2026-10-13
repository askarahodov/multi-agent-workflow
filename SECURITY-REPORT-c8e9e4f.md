# SECURITY-REVERIFY Report

**Date:** 2026-10-12
**Reviewer:** sdlc-security (independent verification)
**Branch:** integration/mvp-v1
**Commit:** c8e9e4f
**Base:** origin/main@7830cc1
**Workspace:** /mnt/data/multi-agent-workflow (clean working tree, only untracked child-task artifacts)

---

## Executive Summary

**VERDICT: FAILED** — 3 blocking findings remain on the integration snapshot. The SECURITY-FIX task (t_524fef64) claimed to fix SEC-002 and SEC-004, but those fixes are **NOT present** on the integration/mvp-v1 branch. Additionally, quality-gates lacks authentication middleware entirely.

| Finding | Original Severity | Current Status | Blocking |
|---------|-------------------|----------------|----------|
| SEC-001: No auth on any API | CRITICAL | **PARTIAL** (3/4 services) | YES (quality-gates missing) |
| SEC-002: No TLS/SSL | CRITICAL | **NOT FIXED** | YES |
| SEC-003: Permissive default tool policy | HIGH | **FIXED** | NO |
| SEC-004: auth_config plaintext | HIGH | **NOT FIXED** | YES |
| quality-gates missing auth | — | **NEW** | YES |

---

## Detailed Findings

### SEC-001: Authentication/Authorization — PARTIAL FIX (BLOCKING)

**Affected Services:**
- ✅ orchestration-server — `AuthMiddleware` installed, all endpoints protected with role deps
- ✅ agent-management — `AuthMiddleware` installed, all endpoints protected
- ✅ runtime-hardening — `AuthMiddleware` installed, all endpoints protected
- ❌ **quality-gates** — **NO authentication middleware**, all endpoints open

**Evidence:**
- `orchestration-server/orchestration_server/api.py:115` — `app.add_middleware(AuthMiddleware)`
- `agent-management/agent_management/api.py:82` — `app.add_middleware(AuthMiddleware)`
- `runtime-hardening/runtime/api.py:462` — `app.add_middleware(AuthMiddleware)`
- `quality-gates/quality_gates/api.py` — **no AuthMiddleware import or installation**

**Impact:** quality-gates API (gate execution, release approval, evidence access) is completely unauthenticated. Any network caller can run gates, approve/reject releases, access evidence.

**Remediation:** Install `AuthMiddleware` in `quality-gates/quality_gates/api.py` and add role dependencies (`require_read`, `require_write`, `require_admin`) to all endpoints.

---

### SEC-002: TLS/SSL Enforcement — NOT FIXED (BLOCKING)

**Evidence:** No service has TLS configuration.

| Service | Config File | TLS Settings | Main.py SSL |
|---------|-------------|--------------|-------------|
| orchestration-server | `orchestration_server/config.py` | ❌ None | `uvicorn.run(..., host="0.0.0.0", port=8000)` |
| agent-management | `agent_management/config.py` | ❌ None | `uvicorn.run(..., host="0.0.0.0", port=8001)` |
| runtime-hardening | `runtime/config.py` | ❌ None | Factory pattern, no SSL |
| quality-gates | `quality_gates/config.py` | ❌ None | `uvicorn.run(app, host=args.host, port=args.port)` |

**Impact:** All API traffic (including provider API keys in `auth_config`, agent outputs, workspace data) transmitted in cleartext. Vulnerable to MITM, credential theft, data exfiltration.

**Remediation:**
1. Add `cert_file`, `key_file`, `ca_file` to all `Settings` classes
2. Configure uvicorn with `ssl_certfile`/`ssl_keyfile` in production entrypoints
3. Add HSTS header via middleware when TLS enabled

---

### SEC-003: Deny-by-default Tool Policy — FIXED (NON-BLOCKING)

**Evidence:** `agent-management/agent_management/tool_policy.py`
- `DEFAULT_PERMISSIVE_POLICY` → `DEVELOPMENT_ONLY_PERMISSIVE_POLICY` with security warning (lines 126-136)
- Runtime guard in `ToolPolicyEngine.allow()` (lines 86-92) blocks it unless `ALLOW_DEV_PERMISSIVE_POLICY=1`
- Secure default: empty allow-lists = deny all (lines 82-84, 95-98)

**Status:** VERIFIED FIXED. The permissive default is no longer usable without explicit opt-in.

---

### SEC-004: Provider API Keys Encrypted at Rest — NOT FIXED (BLOCKING)

**Evidence:** 
- `agent-management/agent_management/crypto.py` — Envelope encryption implementation exists (AES-256-GCM, per-provider DEK, KEK from `AUTH_ENCRYPTION_KEY`)
- `agent-management/tests/test_encryption.py` — 15 regression tests written for expected behavior
- **BUT** `agent-management/agent_management/services.py` **does not use encryption:**

```python
# services.py line 140 — PLAINTEXT STORAGE
auth_config=data.get("auth_config") or {},

# services.py line 184 — PLAINTEXT UPDATE
_apply_patch(row, patch, allowed)  # includes auth_config

# services.py line 213 — PLAINTEXT READ (no decryption)
config: Dict[str, Any] = dict(provider.auth_config or {})
```

**Test Failures (3/15):**
```
FAILED test_create_provider_encrypts_auth_config
FAILED test_get_provider_returns_encrypted_not_plaintext  
FAILED test_update_provider_re_encrypts_auth_config
```
Error: `assert is_encrypted(provider.auth_config)` — stored value is plaintext dict, not envelope.

**Impact:** Database compromise exposes all LLM provider credentials (OpenRouter, Anthropic, HuggingFace API keys). Insider threat or backup leakage exposes secrets.

**Remediation:** Update `ProviderService` in `services.py` to:
1. Call `encrypt_auth_config()` in `create_provider()` and `update_provider()`
2. Call `decrypt_auth_config()` in `build_adapter()`
3. Ensure `ProviderResponse` schema continues to exclude `auth_config` (already correct)

---

## Security Checks Run

| Check | Command/Method | Result | Evidence |
|-------|----------------|--------|----------|
| Candidate identity verification | `git log`, `git status` | ✅ PASSED | Commit c8e9e4f, clean tree |
| Secret scan (changed files) | Regex scan of git diff 7830cc1..c8e9e4f | ✅ PASSED | No secrets in diff |
| Dependency scan | Diff of pyproject.toml files | ✅ PASSED | Only internal packages added |
| AuthZ inspection | Manual code review of all API routers | ⚠️ PARTIAL | 3/4 services protected |
| TLS inspection | Manual config + main.py review | ❌ FAILED | No TLS anywhere |
| Tool policy review | `tool_policy.py` inspection | ✅ PASSED | Deny-by-default enforced |
| Provider secret storage | `services.py` + `test_encryption.py` run | ❌ FAILED | 3 integration tests fail |
| SSRF guard review | `tools/registry/network.py` | ✅ PASSED | IP blocking, redirect re-check |
| Path traversal review | `tools/registry/filesystem.py` | ✅ PASSED | Canonicalization + scope check |
| Shell injection review | `tools/registry/shell.py` | ✅ PASSED | `shlex.split`, argv-only exec |

---

## Residual Risk

| Description | Severity | Reason | Recommended Action |
|-------------|----------|--------|-------------------|
| quality-gates missing auth | HIGH | New finding on this snapshot | Add AuthMiddleware before merge |
| Auth middleware dev bypass (`AUTH_ENABLED=false`) | MEDIUM | Defaults to full access in dev | Document: must be `true` in production |
| No CORS configuration | MEDIUM | Undefined browser behavior | Configure CORSMiddleware per service |
| No rate limiting on APIs | MEDIUM | DoS/credential stuffing risk | Add slowapi or similar before production |
| Frontend test failures (ResizeObserver) | LOW | jsdom limitation, not security | Fix test setup (add ResizeObserver polyfill) |
| Dependency scanner uses demo advisories | LOW | `DEFAULT_ADVISORIES` only | Integrate OSV/pip-audit in CI |

---

## Artifacts

- **SECURITY-REPORT-c8e9e4f.md** — This report
- **Candidate identity:** git commit c8e9e4f on branch integration/mvp-v1
- **Changed files:** 61 files in integration diff (see `git diff --name-only 7830cc1..c8e9e4f`)

---

## Next Steps

1. **BLOCKER:** Merge SEC-002 (TLS) and SEC-004 (auth_config encryption) fixes from t_524fef64 branch into integration/mvp-v1
2. **BLOCKER:** Add AuthMiddleware to quality-gates API
3. **BLOCKER:** Update ProviderService to use crypto.py encryption functions (fix 3 failing tests)
4. Re-run full test suite + security gate after fixes
5. Only then: verdict PASS → proceed to REWORK/RELEASE

---

**Do not merge until all blocking findings are resolved.**