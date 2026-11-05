# Agent definitions / profiles (developer & operator UI)

`Профили агентов` is an explicit Settings-adjacent screen. It creates and edits a server-owned `agent_definitions` record via versioned agent-management REST, and can create a bounded allowlist `tool_policies` record (empty permissions are deny-all). Model references point to existing `model-profiles`. Its role, stages, skills, max_concurrency and budget_limit fields were present in the SQL model but were not previously exposed by the public API. The new API uses the existing DB columns, storing stages/skills as JSON strings for backward compatibility.

**Security boundary:** these records describe a logical agent. They are not a live registered native worker, and they **do not enforce** LLM expenditure or worker concurrency just by existing. The UI labels them metadata until the execution control-plane applies limits. No provider calls, secret storage or automatic invocation occur. Tool actions must still be authorised by the runtime/gateway and independent QA uses separate credentials. Changes carry optimistic versioning and must not be treated as hot mutation of running attempts.

Remaining for full #254: backend-enforced runtime budgets, live profile→task/worker stage matching, project-scoped profiles, profile archival and independent QA proof. Do not claim #254 closed on CRUD alone.
