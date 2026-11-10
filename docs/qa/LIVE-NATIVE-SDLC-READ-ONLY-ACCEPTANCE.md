# Live native seven-stage SDLC — read-only operator evidence audit (#11 / #8 / #254)

**Gate status: NOT EXECUTED / NOT ACCEPTED.** This is a runbook and executable
read-only verifier, not proof of an OpenRouter run. All automated CI tests use
scripted models and disposable state; those results never count as paid live
provider, verified Git object, protected restart or release signoff.

## Operating authority and cost boundary

Do **not** launch provider calls unless all of the following are independently
established on the operator's protected environment:

- The operator has explicitly approved the specific live run and a numerical
  maximum spend **in USD**. A token cap is not a true monetary cap; the
  native worker currently does not atomically reserve USD across concurrent
  workers. Configure and independently verify a provider-side account/key
  spending cap and retain payment/usage evidence outside this repository.
- The OpenRouter key is stored only in a private root/worker-owned file outside
  the checkout (UID 10001, mode 0600). A different protected orchestration key
  and a different gateway key must be provisioned, plus both TLS CA files.
  Never send secrets in chat, CLI arguments, GitHub comments, screenshots,
  tracebacks, reports or environment dumps.
- Enforce finite dispatch limits and provider token/tool-call limits. For a
  first trial choose ONE session and ONE completed attempt; seven stages are
  subsequent separately monitored trials. Never use the autonomous dispatch
  overlay's larger default budgets for a first paid trial.
- The control and gateway run the opt-in authenticated, leased TLS deployment,
  not the dev Compose stack. The provider egress overlay must be permitted by a
  real operator-owned egress allowlist; a Docker bridge alone does not enforce
  OpenRouter-only outbound access.
- The expected published graph consists of exactly the seven ordered Agent →
  automatic Contract Gate pairs named research, architecture, implementation,
  tests, review, security, release-prep, with real contracts and trusted profile
  bindings. The worker and gateway cannot self-sign independent QA or the human
  release approval. The native snapshot-backed worker currently refuses Git
  grants, while the separate operator-pinned Git worker is the documented
  opt-in path for verified artifacts. Do not weaken that constraint just to
  make a demo pass.

## Independent preparation — no paid calls

On a machine with a protected checkout, Docker, Git and private credentials:

1. Run the documented native worker CLI preflight against the protected
   Compose overlay. Verify the separate orchestrator, gateway and provider
   secrets; lease, TLS and profile bindings; no provider requests are made.
2. Run the QA-controller and gateway private configuration preflights and
   verified repository/attempt-worktree checkout setup, using the dedicated
   read-only QA identity. Keep the worker isolated from both direct Git and QA
   signing credentials.
3. Confirm the backend denies missing contracts, mismatched profile bindings,
   unauthorized attempt lease, unsigned QA and unauthorized release approval.
4. Use the UI to create and publish a versioned seven-stage graph. Confirm
   preflight against the exact project/version and independently capture
   run/version/contract references in private operator records.
5. Only after provider-side hard spending cap and explicit operator permission
   run the finite native worker with tight session, completion, total-token,
   tool-call and poll limits. Observe actual OpenRouter tool requests in the
   operator's provider/account audit, plus the trusted gateway ledger and
   server attempts. Do not automatically replay a crashed attempt.
6. Process independent tester, reviewer and security QA with distinct service
   identities. An actual human operator must separately approve release;
   completion/worker-reported Git SHA cannot grant it.

## Read-only post-run check, no provider access

After the operator has completed the above and has a concrete protected
run ID and project ID, use the existing **native worker container**, which
already mounts a private orchestration read credential and trusted CA:

    python -m orchestration_server.native_live_acceptance \
      --run-id <OPERATOR_RUN_UUID> --project-id <OPERATOR_PROJECT_UUID>

This CLI loads only the native orchestration TLS/key configuration via
native_worker_bootstrap. It makes authenticated HTTPS **GET** requests only;
it never imports/constructs an OpenRouter provider, starts a worker, calls
tools, signs QA, approves release or spends tokens. It rejects plaintext HTTP,
untrusted TLS/proxies, malformed pagination, mismatched scopes or missing
records. Do not insert secrets in command-line arguments; IDs are not secrets.

The auditor checks the persisted published version's strictly executable
linear graph; all seven stage nodes and their contracts; exactly seven
server-owned completed tasks with matching original profile bindings and
dependency handoffs; a completed Contract Gate attempt per stage; worker-
reported Git artifact tied to the completed attempt; matching immutable
verified QA receipt with **three distinct signed gate-run IDs** per task; and
a separate operator-required approved release receipt. Any failure exits
non-zero and emits a static, redacted failure code without server payloads.

On success the machine-readable output is intentionally labelled
REVIEW_REQUIRED_EVIDENCE_PRESENT. Three fields remain explicitly
NOT_PROVEN_BY_READ_API: actual provider request, trusted Git object readback
and protected Compose/service restart. Even a successful audit **cannot**
prove those facts, payment/budget enforcement, Windows Docker Desktop support
or production deployment safety. Attach independent operator evidence for
these missing facts, plus human/security review and CI SHA.

Only then can a reviewer evaluate the parent issues (#11, #8, #254, #256);
the read-only audit never merges the PR, closes issues or authorizes deployment.

## Offline regression gate

    python -m pytest services/orchestration-server/tests/test_native_live_acceptance.py -q

Negative tests simulate foreign project, manual/unpublished run, wrong version,
malformed graph, missing/duplicate tasks, wrong dependency chain, unverifiable
Contract Gate, forged attempt/Git SHA, unsigned QA, reused gate-run identifiers,
missing operator approval, bad pagination and secret-bearing transport errors.
No network, Docker, OpenRouter key or provider calls are needed.
