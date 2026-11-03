# Pilot readiness: evidence-based acceptance (#11, #8)

**Pilot scope:** one operator on a trusted local machine, non-public services, controlled project. This document is not a production security approval. Never commit API keys, tokens, provider responses with secrets, or private workspace contents.

## Run the existing technical gates

From a clean checkout, with Docker Compose, Git and Python available:

```sh
python -m pytest tests/test_pilot_readiness.py -q
python scripts/check_native_qa_compose.py
python scripts/check_native_qa_compose.py --live-sdlc
```

The Compose checks evaluate resolved configuration **without starting containers**. Run the native cross-service CI suite and protected Compose boot/restart smoke as documented in `.github/workflows/native-agent-e2e.yml`. Record the workflow URL, exact commit SHA and build/run IDs. A green CI is necessary but not sufficient.

## Live acceptance procedure (operator approved; potential paid OpenRouter call)

1. Provision the documented private key files, QA signing keys and dedicated operator approval secret outside Git. Use the protected Compose overlays including autonomous dispatch, QA dispatch, trusted Git runtime, OpenRouter provider egress, and release approval. Configure a real QA test command; reject the deliberate default failure command. Restrict all published ports and external network access.
2. Record clean `docker compose config`, build, container health, authenticated API responses and browser UI evidence. Confirm no Hermes or other agent CLI in PATH or HOME.
3. In the **real browser UI**, create a project/workflow and start a development run; record its durable ID, events and initial task states. Do not substitute direct DB mutation or a mocked UI.
4. With explicitly approved OpenRouter credentials and budget, verify a real provider request and a native tool invocation in an isolated workspace. Save redacted tool and provider evidence; verify a Git commit via the trusted orchestration verifier. A scripted/offline provider **does not** satisfy this item.
5. Submit a deliberately invalid completion to prove Contract Gate rejection, then verify a valid Git-bound submission and next-stage transition. Record HTTP response codes and immutable evidence.
6. Run independent QA under separate credentials; verify test output, gate receipt, and separation from worker identity. Obtain operator approval only through the dedicated release-approval boundary; verify it is not issued implicitly by QA or worker.
7. Restart the stack and verify run/task states, artifacts, event journal and UI persist. Exercise worker interruption, retry and recovery without duplicate acceptance.
8. Have an independent security reviewer verify proxy/query-string redaction, key rotation and revocation, network/volume isolation, restrictions around privileged Docker in the local-only profile, and a rollback plan. Do not enable SSE/WS ticket rollout merely because CI is green.

## Evidence schema and decision

Create a **private redacted** JSON report (not committed to Git) with `schema_version: 1`, a full 40-character `commit_sha`, and a `checks` object. Every entry has `status: PASS|FAIL|BLOCKED`, an `evidence` string (HTTPS link without URL userinfo, query parameters or fragments, or a path relative to the private evidence root). Signed evidence URLs containing credentials must remain in a private evidence store and must not appear in this JSON inventory. `live_openrouter_tool_call`, `independent_qa` and `security_signoff` also require a named `reviewer`.

**For every PASS in the full CLI gate**, export a redacted, locally retained evidence artifact, and include a `sha256` field containing its exact lowercase 64-hex SHA-256 digest. The CLI now checks the existence, safe relative path, size and content hash of each local artifact and refuses symlinks/hardlinks/traversal and mismatches. Artifacts are **not** committed to the repository. Remote HTTPS references remain valid for planning (`--check-structure-only`) but cannot be hashed by the offline CLI and are **not accepted as integrity-verified PASS evidence**. Save a locally exported, reviewed, redacted copy for the full gate.

For the full byte-integrity check, **run the verifier on Linux/WSL or another POSIX host** with `dir_fd`, `O_DIRECTORY`, `O_NOFOLLOW` and `O_NONBLOCK`. It opens the entire path via pinned directory descriptors, refuses symlink swaps and opens files non-blockingly to reject raced FIFOs. On unsupported platforms (including native Windows Python), the full gate **fails closed** rather than claiming race-safe file verification; Windows CMD users can invoke the Linux verifier via WSL, Docker or their secure Linux test host. The structure-only check remains cross-platform. Ensure the evidence root is a private, operator-owned directory with no other writer during the audit.

Required check IDs: `clean_compose`, `browser_project_run`, `live_openrouter_tool_call`, `git_commit_verified`, `contract_gate_negative`, `independent_qa`, `release_approval`, `restart_persistence`, `no_external_agent_cli`, `security_signoff`.

```sh
# Inspect the shape before collecting evidence; no claim of acceptance
python scripts/check_pilot_readiness.py /private/pilot/report.json --check-structure-only
# All PASS checks must be backed by real redacted files below this absolute directory
python scripts/check_pilot_readiness.py /private/pilot/report.json --artifact-root /private/pilot/artifacts
```

Example entry (the file `browser_project_run.json` lives in the **private** root;
replace the digest with `sha256sum browser_project_run.json` output on the
actual byte content, never with a placeholder):

```json
{
  "status": "PASS",
  "evidence": "browser_project_run.json",
  "sha256": "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
}
```

A missing item, FAIL/BLOCKED, missing `--artifact-root`, missing/unhashed
artifact, oversized or altered file exits non-zero. A reviewer must validate
the **contents** and their binding to the exact Git SHA, live run ID, provider
request, stage transitions, Git verifier, QA signer and operator approval.
SHA-256 verifies only the retained bytes; it **does not authenticate the
producer, make a mock call live, or replace independent review**.
The verifier prints only fixed check IDs and diagnostic categories on failure:
malformed untrusted statuses, path strings and artifact contents are never
echoed into terminal or CI output. Operators must separately inspect the
**private** source material under an approved redaction process.
`--check-structure-only` deliberately does not verify artifact bytes.
Successful full-gate output explicitly says `LIVE AUTHENTICITY AND INDEPENDENT
APPROVAL NOT VERIFIED`.

The report may describe a real pilot only after the authorized live provider
run, independent review and every required check PASS. Without those facts
the decision is **BLOCKED**, regardless of whether files and hashes match.

Do not mark issues #11/#8 complete on this inventory alone. Keep the first pilot local/trusted until Issue #3's Docker host-access risk receives an appropriate deployment-specific decision.
