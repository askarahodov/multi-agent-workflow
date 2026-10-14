# Native agent execution loop — bounded filesystem-only proof of concept

**Status:** first stage of [Issue #21](https://github.com/askarahodov/multi-agent-workflow/issues/21), on the dependency path to [#9](https://github.com/askarahodov/multi-agent-workflow/issues/9) and [#11](https://github.com/askarahodov/multi-agent-workflow/issues/11). **Not** production-ready autonomous SDLC.

## Implemented data flow

```text
Trusted orchestration caller → run_agent_loop(provider, dispatcher, messages, limits)
 → OpenRouter-compatible stream (text_delta / tool_call / usage / done)
 → validate complete stream, usage, budget, output/tool limits
 → NativeFilesystemDispatcher (only read_file / write_file)
 → policy + scoped workspace filesystem execution
 → role=tool result → next provider turn
 → final model answer (still UNVERIFIED)
```

The module has **no task-complete API** and cannot bypass OrchestrationEngine/Contract Gate. Tool calls are deferred until the complete provider turn and accounting are received. A streamed tool event with truncated response, missing/invalid usage, budget overrun or invalid finish reason never starts filesystem work.

### Caller responsibilities

Only the **trusted control plane** may choose system/task messages, per-task workspace root, tool permissions, max turns, tokens, timeout and tool call count. Provider-supplied data does not expand tool permissions. The LLM is not allowed to call generic shell, Git, network or arbitrary Python; these tools are explicitly rejected by the current dispatcher.

```python
from agent_management.agent_loop import run_agent_loop
from agent_management.native_tool_dispatch import NativeFilesystemDispatcher
from agent_management.scoped_fs import ScopedFilesystemExecutor

fs = ScopedFilesystemExecutor(
    "/srv/workspaces/task-123",
    {"fs_read": ["/srv/workspaces/task-123/src/**"],
     "fs_write": ["/srv/workspaces/task-123/out/**"]},
)
result = await run_agent_loop(
    trusted_provider, NativeFilesystemDispatcher(fs),
    [{"role": "user", "content": "Inspect src/README.md and write a report"}],
    max_turns=4, max_total_tokens=4096, max_tool_calls=8, timeout_seconds=60,
)
# result.output is unverified; only the orchestrator may submit and run Contract Gate.
```

### Hard limitations and next gates

- **No durable journal or restart-safe idempotency.** Tool IDs are deduplicated inside one dispatcher instance only. Crashes during writes and retries with a new instance need a persistent execution ledger.
- **No independent sandbox:** Linux scoped filesystem hardening is not a containerized trust boundary. Workspaces must be provisioned without host secrets or privileged mounts. Windows fails closed for file tools.
- **No real Git/shell/HTTP execution:** [#20](https://github.com/askarahodov/multi-agent-workflow/issues/20) remains open. Real agent development cannot commit code or fetch external context using this initial slice.
- **No durable cost accounting:** usage is mandatory and checked conservatively per provider turn, but pricing/cost and provider reliability are not evaluated here.
- **No Contract Gate integration or task assignment:** [#11](https://github.com/askarahodov/multi-agent-workflow/issues/11) remains open. Final text is explicitly `unverified` in the trace and must pass the orchestration service's own contract.
- **No online acceptance without keys:** tests use a deterministic fake provider, not a live OpenRouter API.
- **Timeout limitations:** the async deadline cancels a cooperative network stream, not a synchronous filesystem syscall; file size is separately bounded by the scoped executor.

## Reproduce

```bash
cd agent-management
python -m pytest tests/test_scoped_fs.py tests/test_native_tool_dispatch.py tests/test_agent_loop.py -q
```

Tests cover LLM→read/write→LLM, correct tool-result messages, token/turn/tool count limits, missing accounting, truncation, malformed terminal reason, unauthorized tools, output size, replay and deadline. Full GitHub CI and Quality Gate are required for merge.
