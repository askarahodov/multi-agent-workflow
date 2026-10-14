# Native agent E2E — offline cross-service acceptance (#31)

This suite is the first runnable product-owned integration of **both** Python
subsystems, not a mocked OrchestrationEngine:

1. Real SQLite OrchestrationEngine claims a task against a stored JSON Schema.
2. A deterministic fake provider streams a tool call and token usage.
3. Real `run_agent_loop` routes it through `NativeFilesystemDispatcher`.
4. `ScopedFilesystemExecutor` writes a file into the assigned task workspace.
5. `SqliteToolLedger` durably marks the call ID as performed.
6. The model returns JSON; `native_bridge.run_native_task_attempt` submits it.
7. Only OrchestrationEngine verifies Contract Gate and marks task/run completed.

Negative cases prove that a denied tool is not executed, incomplete token
accounting stops I/O, invalid final JSON cannot pass the contract, and a
restarted dispatcher with the same ledger cannot repeat a completed tool ID.

## Run without Hermes or provider credentials

From the repository root, Python 3.12+:

```bash
python -m pip install -e ./shared
python -m pip install -e ./agent-management -e ./orchestration-server
python -m pip install 'pytest>=8' 'pytest-asyncio>=0.23'
python -m pytest tests/native_agent_e2e -q
```

The dedicated GitHub Actions workflow `native-agent-e2e.yml` runs this
test suite for PRs and main. Test workspaces and SQLite files use pytest
`tmp_path`; no host worktrees, Hermes state, Docker socket or remote API.

**Not proved:** background task scheduler, container isolation against hostile
code, native Git/shell/HTTPS tool safety, streaming from a live OpenRouter key,
cross-DB atomic distributed transaction, recovery of orphaned CLAIMED tool
states, or unattended software delivery. These remain blockers for #11 and #20.
