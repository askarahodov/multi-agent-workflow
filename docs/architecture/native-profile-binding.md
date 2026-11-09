# Native profile-bound execution: leased OpenRouter worker

Published workflow tasks contain three UUID references: `agent_definition_id`, `model_profile_id`, and `tool_policy_id`. They are **provenance, not permissions**. A trusted worker must be explicitly bound to one approved triple before it can claim tasks from a published graph. The approved provider model, private keys, system prompt, gateway tool grants and hard token/tool-call limits still come from the operator's private deployment configuration, not the task JSON.

Set **all three** on the trusted worker deployment (replace example IDs with real persisted IDs):

```sh
MAW_NATIVE_PROFILE_AGENT_ID=11111111-1111-4111-8111-111111111111
MAW_NATIVE_PROFILE_MODEL_ID=22222222-2222-4222-8222-222222222222
MAW_NATIVE_PROFILE_POLICY_ID=33333333-3333-4333-8333-333333333333
```

For **actual profile-bound native dispatch**, the trusted runner now requires an operator-exported, private DB snapshot in addition to those three UUIDs. A UUID-only worker configuration fails local preflight; it can no longer execute a published profile simply by claiming its identifiers.

Export a snapshot only from a trusted Agent Management database after reviewing the records. The exporter reads AgentDefinition, ModelProfile, ToolPolicy and Provider in one consistent SQL statement, never exports provider secrets, rejects disabled/non-OpenRouter providers, non-filesystem grants and profiles with a USD budget (the leased native runner has no shared monetary ledger).

```sh
AGENT_MGMT_DATABASE_URL="sqlite+aiosqlite:////private/agent-management.db" \\
  python -m agent_management.native_profile_snapshot \\
  --agent-id "$MAW_NATIVE_PROFILE_AGENT_ID" \\
  --model-id "$MAW_NATIVE_PROFILE_MODEL_ID" \\
  --policy-id "$MAW_NATIVE_PROFILE_POLICY_ID" \\
  --output /private/approved-native-profile.json
```

The output is a new (not overwritten) 0600 private file. An operator must copy/mount it as a read-only regular file owned by native-worker UID **10001** at `/run/maw-profile/approved.json`. Use `deploy/compose/secure/compose.native-profile-snapshot.yml` alongside the existing secure-control and worker overlays. The matching operator-provided `MAW_OPENROUTER_MODEL` and `MAW_NATIVE_WORKER_TRUSTED_PROMPT` **must exactly match** the exported DB model and system prompt. The gateway's trusted absolute workspace root is `/srv/maw/workspace`; its existing src-read/out-write and durable lease/ledger restrictions remain in force.

The worker checks exact identities and immutable revision-bearing fields in this snapshot at boot. It clamps each streaming output to the stored ModelProfile max_tokens (if set) and filters the model's advertised `read_file` / `write_file` tool schemas; every tool call is checked against the exported ToolPolicy on the trusted absolute workspace path **before** any gateway I/O. The gateway independently re-enforces its own narrower static path policy. Neither tasks, prompts nor LLM tool arguments can replace the snapshot. No provider call happens during export or local preflight.

Before deployment, independently confirm that the pinned OpenRouter model, prompt, workspace, provider credentials and gateway tool restrictions correspond to those DB records. Missing/partial/invalid settings fail local preflight. A published task without a matching local binding is refused **before atomic claim**, with no model or tool I/O. A differently bound worker skips foreign profiles so a correctly bound worker can claim. After successful claim the worker re-fetches authoritative task metadata: if identity/profile changed, it fails closed for operator reconciliation (never auto-retries unknown side effects). If identity/profile is still valid, the worker executes the **post-claim task snapshot**, not the earlier paginated listing. That includes the authoritative task instructions and other runner-visible metadata; the list response is scheduling advice only. A failed re-fetch or mismatched profile never invokes provider/tools. Legacy non-published tasks remain available only to legacy unbound workers.

**Deployment checkpoint, not a live resolver:** the private snapshot enforces exported model, instructions, output and file-tool policy at worker runtime, but a later DB update cannot revoke an already exported snapshot. Operator must stop/re-export/restart when a provider, definition, model or policy revision changes, and reconcile any in-flight leases. The gateway's filesystem check remains authoritative; this snapshot cannot grant new gateway privileges. Profiles with USD budgets cannot be exported; supported models still need real token/cost acceptance. An authenticated live cross-process resolver, cross-worker dollar/concurrency accounting, role/stage/project eligibility, and independent QA/live provider/Compose tests remain open under #254 and #11. Do not present this offline deployment checkpoint as those guarantees. Do not present pinned IDs as proof of model/permission/budget enforcement.

The server also reserves `_workflow_version_id`, `_workflow_definition_id`, `workflow_node_id` and `workflow_agent_reference`: the ordinary `POST /workflows/runs` API rejects client-supplied use of these execution-provenance fields. Only the internal trusted published-version route can pass the engine's `published_graph=True` flag after recompiling an immutable stored snapshot. A user cannot self-label an ad hoc task as a published profile-bound job to bypass the guard.
