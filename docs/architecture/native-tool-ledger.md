# Durable claim ledger for native tool calls (Issue #27)

**Scope:** at-most-once reservation of a tool-call ID in a trusted task scope,
including after the Python process restarts. This is not exactly-once execution
and is not a substitute for distributed transaction coordination, sandboxing or
the orchestration Contract Gate.

## Design

The **trusted control plane** supplies both an absolute path to a private
SQLite database and a stable scope identifier, e.g. `run-123/task-456`. Neither
is derived from a model response. The ledger is stored outside the assigned
workspace and must be protected by OS ownership/permissions (`0600`).
The database stores only `scope`, `call_id`, a safe tool name and `state`.

```text
CLAIMED       ← atomic SQLite insert BEFORE any tool I/O
    ├─ success ──→ SUCCEEDED
    └─ denial  ──→ DENIED
```

A repeated `(scope, call_id)` returns `DUPLICATE_CALL` regardless of whether
the original claim is `CLAIMED`, `SUCCEEDED` or `DENIED`. An interruption
between claim and outcome leaves an ambiguous `CLAIMED`. It must be
**reconciled by the orchestrator**, not replayed automatically.

### Trusted use

```python
from agent_management.scoped_fs import ScopedFilesystemExecutor
from agent_management.native_tool_dispatch import NativeFilesystemDispatcher
from agent_management.tool_ledger import SqliteToolLedger

fs = ScopedFilesystemExecutor(
    "/srv/workspaces/task-456",
    {"fs_write": ["/srv/workspaces/task-456/out/**"]},
)
ledger = SqliteToolLedger("/var/lib/multi-agent/ledger/tool-claims.sqlite3")
dispatcher = NativeFilesystemDispatcher(
    fs, ledger=ledger, execution_scope="run-123/task-456",
)
```

With no ledger, the dispatcher retains previous **in-memory only** duplicate
protection for offline tests. Production worker integration MUST explicitly
supply the ledger. Ledger failures are fail-closed before tool execution.
If updating `SUCCEEDED` fails after a write, the prior durable `CLAIMED`
survives and blocks replay by another dispatcher.

## Threat model / limitations

- The DB path and its parent are **trusted infrastructure**: an untrusted agent
  must not be allowed to rename, write, hardlink, remount or replace them.
  SQLite path-to-handle race safety relies on this invariant.
- A restarted model can issue a **new tool_call_id** for the same logical action;
  this ledger does not detect semantic duplicates with new IDs.
- Filesystem writes are atomic per file, not across multiple files or Git
  commits. A crash cannot prove whether a side effect was made without
  domain-specific reconciliation and a durable workflow journal.
- Shell/Git/HTTP remain disabled in the current dispatcher. Do not interpret
  this ledger as approval to run unsandboxed AI-generated commands.
- Store and protect the SQLite DB outside workspace; `CLAIMED` entries and
  recovery policy must be surfaced in the future native worker UI and journal.

## Reproduce

```bash
cd agent-management
python -m pytest tests/test_tool_ledger.py tests/test_native_tool_dispatch.py -q
```

Tests cover file writes across two independent dispatcher instances, SQLite
reopening, at-most-once across concurrent connections, interrupted `CLAIMED`
replay prevention, ledger down before I/O, failed finalize after I/O, private
DB permissions and redaction. All existing backend/CI checks must remain green.
