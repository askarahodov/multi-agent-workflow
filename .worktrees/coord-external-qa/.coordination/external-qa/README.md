# Independent QA Review Channel — External ChatGPT

## Purpose
This coordination channel connects the local AI Multi Agent Workflow project (`askarahodov/multi-agent-workflow`) with an independent external QA reviewer (ChatGPT) operating outside the Hermes agent runtime.

## Rules
- `requests.md` — Local coordinator (`@orchestrator`) writes review requests.
- `responses.md` — Independent ChatGPT reviewer writes findings. DO NOT MODIFY by local coordinator.
- Service branch: `coord/external-qa` (separate worktree `.worktrees/coord-external-qa`).
- No automatic merge with `main`. No forced push. No paid model switch without owner approval.
- All QA findings (QA-01 through QA-05) must reference existing Kanban tasks (`t_2eaa57b1` and assigned tasks).
- Architecture audit (`t_005a92be`) is passed for independent review without being declared complete.
- Dispatcher fix (`t_0d1f5d1a`) must not close QA-01 by configuration change alone.
- No duplicate GitHub tasks.
- No API keys or secrets in this directory.

## Checkpoints
1. Architectural review of `t_005a92be` (independent QA handoff)
2. Dispatcher rate-limit suppression verification (mock provider, no real quota)
3. Kanban inventory and dependency audit (QA-05)
4. Security gate and CI review (QA-03 / QA-04)
5. Provider API error classification (QA-02)
6. Final independent acceptance before main branch merge
