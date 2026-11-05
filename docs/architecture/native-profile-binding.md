# Native profile-bound execution: leased OpenRouter worker

Published workflow tasks contain three UUID references: `agent_definition_id`, `model_profile_id`, and `tool_policy_id`. They are **provenance, not permissions**. A trusted worker must be explicitly bound to one approved triple before it can claim tasks from a published graph. The approved provider model, private keys, system prompt, gateway tool grants and hard token/tool-call limits still come from the operator's private deployment configuration, not the task JSON.

Set **all three** on the trusted worker deployment (replace example IDs with real persisted IDs):

```sh
MAW_NATIVE_PROFILE_AGENT_ID=11111111-1111-4111-8111-111111111111
MAW_NATIVE_PROFILE_MODEL_ID=22222222-2222-4222-8222-222222222222
MAW_NATIVE_PROFILE_POLICY_ID=33333333-3333-4333-8333-333333333333
```

Before deployment, independently confirm that the pinned OpenRouter model, prompt, workspace, provider credentials and gateway tool restrictions correspond to those DB records. Missing/partial/invalid settings fail local preflight. A published task without a matching local binding is refused **before atomic claim**, with no model or tool I/O. A differently bound worker skips foreign profiles so a correctly bound worker can claim. After successful claim the worker re-fetches authoritative task metadata: if identity/profile changed, it fails closed for operator reconciliation (never auto-retries unknown side effects). Legacy non-published tasks remain available only to legacy unbound workers.

**Not yet dynamic configuration:** this enforces a trusted ID match, not the database's latest settings. The operator must ensure a deployed worker's provider/model/permissions and hard limits actually match its pinned profile. Per-profile price/concurrency accounting, version-pinned capability snapshots and independent QA/live provider acceptance remain open under #11. Do not present pinned IDs as proof of model/permission/budget enforcement.
