# Native agent → OrchestrationEngine: verified handoff (Issue #29)

**Проверяемый срез:** связка результата собственного native agent runner с существующим engine-owned Contract Gate. Это НЕ самостоятельно работающий scheduler и не live SDLC.

## Контракт вызова

```python
from orchestration_server.native_bridge import run_native_task_attempt

async def trusted_runner(task_id: str, attempt_id: str) -> str:
    # Implement in trusted native worker, not in LLM output:
    # 1. load task & role policy from control-plane
    # 2. create assigned workspace and durable tool ledger
    # 3. run agent_management.agent_loop.run_agent_loop(...)
    # 4. return AgentLoopResult.output
    return '{"summary":"verified artifact"}'

result = await run_native_task_attempt(
    engine, task_id=task_id, agent_id=agent_id, runner=trusted_runner,
)
```

1. `OrchestrationEngine.claim_task` atomically reserves the task and agent.
2. Trusted runner returns a plain JSON text. The bridge rejects Markdown fenced content, duplicate keys, NaN/Infinity, non-object values and oversized text.
3. **Only** `OrchestrationEngine.submit` checks the task's stored JSON Schema and changes task/run state to completed. Model output cannot set a raw task state.
4. Invalid native JSON and runner errors become `engine.fail_attempt` with a constant, redacted reason; the engine decides retry, failure and saga events. Unauthorized agent claims are rejected by engine.
5. Cancellation is propagated rather than falsely reported as success; `OrchestrationEngine.recover` owns interrupted attempts. The future worker must wire recovery into operational flow.

## Grenzen / ограничения

- The bridge intentionally depends only on a **trusted injected async runner**, not on the agent-management Python package. This avoids coupling independent deployed services and permits real SQLite engine tests without a paid LLM.
- The caller still must implement actual task/role permissions, workspace provisioning and sandbox lifetime; a string from the model is not a trusted tool request.
- Agent events and tool ledger must be stored in a separate durable execution journal. This bridge does not claim crash-safe coordination of two DBs or semantic exactly-once.
- The current native loop supports only filesystem tools. Git/shell/HTTPS (#20), native worker registration/polling (#11), quotas and live OpenRouter E2E remain separate acceptance gates.
- On any contract mismatch, the attempt is `verification_failed` rather than success. Engine retry policy remains authoritative.

## Проверка

```bash
cd orchestration-server
python -m pytest tests/test_native_bridge.py -q
```

Tests run against the actual SQLAlchemy SQLite engine and SagaEvents and cover valid JSON, a contract-invalid object, duplicate keys, nonfinite JSON, provider/runner errors, retries, cancellation and conflicting claims.
