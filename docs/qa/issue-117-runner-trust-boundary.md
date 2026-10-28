# #117 — Trusted QA signer ↔ untrusted test runner boundary

## Verified current path (2026-10-28)

`NativeQaController.attest` creates a detached verified Git checkout, then calls
`POST /api/v1/runs` for `tester`, `reviewer`, and `security`.
The `tester` gate in `secure-quality-gates` executes workspace commands via
a local subprocess. The same QG service owns signing/admin credentials. Cleaning
environment variables, killing subprocess groups, and restricting the QG
container **do not prevent** a malicious QA test from reading service files
accessible to the same UID. Signed QA must not be considered sandboxed.

## Required separation before integrating isolated_tester

1. **Runner owns execution, never secrets.** Independent ephemeral runner is
   started with no QA attestation/admin/provider credentials, no inherited
   QG mounts, no Docker socket in the QG signer, no network, separate UID and
   PID namespace, read-only content-addressed snapshot, bounded tmpfs and
   resource limits. A constrained Docker launcher must be controlled by a
   trusted external launcher with a limited interface, not by QG.
2. **Immutable handoff.** Controller verifies Git commit SHA and file list,
   sends only task/attempt/commit IDs and an allowlisted command identifier.
   The runner cannot choose workspace paths, image, flags, or a QA verdict.
   The launcher verifies digest and location of the source snapshot before
   mounting it read-only.
3. **Evidence channel.** Runner returns bounded test output and exit
   disposition. Trusted QG validates attempt, commit SHA, gate provenance and
   a fresh execution nonce before persisting evidence. Arbitrary runner-supplied
   `passed` booleans are never sufficient for attestation.
4. **Fail closed.** Absence of runner, mismatched SHA, failed snapshot check,
   timeout, crash, cleanup uncertainty, malformed evidence or missing nonce
   blocks the QA receipt and downstream SDLC transitions.
5. **Recovery.** Launcher identifies each container by unguessable run ID,
   cleans up on timeout, cancellation, controller restart and unexpected death,
   and records auditable status. Verify daemon-side cleanup with real Docker.
6. **Negative acceptance.** Test code attempts direct signing-file read,
   `/proc` traversal, inherited-FD access, host socket/API access,
   outbound connection, filesystem writes and timeout escape. Run with
   real secrets *replaced by disposable canaries*; no key bytes in CI logs.

## Integration order

- Keep `quality_gates.isolated_tester` opt-in and disconnected from signed
  QA until the separate-privilege launcher exists.
- Land a launcher with restrictive host-side permissions and negative
  integration tests; then wire controller → launcher → trusted evidence
  verifier behind a strict feature gate.
- Run complete Compose + signed QA E2E, independent security review, and only
  then consider closing #117 or the dependent #11.

## Scope of CI coverage today

`scripts/isolated_qa_docker_smoke.py` verifies a Docker command's
isolation and timeout cleanup, not a secure end-to-end signer boundary.
Static Compose assertions detect some privilege regressions but cannot
establish runtime isolation of an attacker-controlled process.


## No implicit registry access

The opt-in Docker launcher uses an operator-selected local image ID and
`--pull=never`. A missing local image must fail instead of triggering a
network registry lookup. This constraint applies to the launcher only and
does not permit it to run in the QA signing service.

## Guard against accidental use in a signer process

The opt-in Docker helper rejects invocation if known signing, admin or
provider-secret environment markers are present. This prevents an accidental
caller from combining QG credentials with Docker-daemon access. **It does not
establish an isolation boundary**: mounted secrets, open file descriptors,
unknown variables or host-level permissions may still be exposed. Only a
separate, no-secret launcher with validated data handoff can resolve #117.


## Docker CLI contract regression

The opt-in launcher contract test verifies the Docker CLI receives only the
fixed minimal parent environment and exactly one read-only source mount.
It rejects extra environment-file, volumes-from and privileged options in the
constructed invocation. This test is not evidence that QG secrets are isolated
while untrusted subprocesses run inside signed QA.
