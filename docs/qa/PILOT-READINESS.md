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

Create a **private redacted** JSON report (not committed to Git) with `schema_version: 1`, a full 40-character `commit_sha`, and a `checks` object. Every entry has `status: PASS|FAIL|BLOCKED`, an `evidence` string (HTTPS link or repository-relative artifact path). `live_openrouter_tool_call`, `independent_qa` and `security_signoff` also require a named `reviewer`.

Required check IDs: `clean_compose`, `browser_project_run`, `live_openrouter_tool_call`, `git_commit_verified`, `contract_gate_negative`, `independent_qa`, `release_approval`, `restart_persistence`, `no_external_agent_cli`, `security_signoff`.

```sh
python scripts/check_pilot_readiness.py /path/to/redacted-pilot-report.json
```

A missing item or FAIL/BLOCKED exits non-zero. `--check-structure-only` is for preparing the inventory, **not pilot approval**. The script checks report structure and potential secret leakage; it **does not verify evidence content or identities**. Independent reviewers must inspect links, artifacts and underlying systems. Pilot acceptance requires that review **and** all checks PASS; absent an authorized live provider run the decision is **BLOCKED**.

Do not mark issues #11/#8 complete on this inventory alone. Keep the first pilot local/trusted until Issue #3's Docker host-access risk receives an appropriate deployment-specific decision.
