# Multi-Agent Autonomous Development Patterns & Best Practices

**Research Report for Multi-Agent Workflow Platform Setup**

---

## Executive Summary

This report synthesizes findings from academic literature, industry frameworks (MetaGPT, ChatDev, OpenDevin, SWE-agent, AutoGPT), and Hermes Agent's native kanban-orchestrator system to provide concrete recommendations for multi-agent autonomous development. Key patterns include: **kanban-based coordination with git worktree isolation**, **structured handoff protocols with idempotency keys**, **externalized state management**, **bounded retry with escalation**, and **artifact-age-based observability**.

---

## 1. Agent Coordination Patterns

### 1.1 Kanban-Based Coordination (Recommended for Multi-Agent Workflow Platform)

**Hermes Kanban** provides a durable, SQLite-backed task board with first-class support for multi-profile collaboration:

| Pattern | Description | Hermes Implementation |
|---------|-------------|----------------------|
| **Task Locking** | Exclusive locks with TTL (default 30 min) prevent concurrent work on same task | Dispatcher atomically claims tasks; worker PID tracked |
| **Git Worktree Isolation** | Each task gets isolated worktree + branch (`kanban/<task_id>`) | `workspace_kind: "worktree"` on task creation |
| **Dependency DAG** | Parent→child dependencies with circular validation | `--parent` flag on `kanban_create`; auto-promotion on completion |
| **Review Workflow** | Dedicated reviewer cards or same-card review lifecycle | `kanban_request_review` / `kanban_request_changes` / `kanban_complete` |
| **Circuit Breaker** | Auto-blocks after N consecutive spawn failures (default 2) | `kanban.failure_limit` config or per-task `max_retries` |

**Key Insight from ATC-Kanban (JSCOP):** "When you run multiple AI coding agents on a single project, they step on each other. Two agents edit the same file, branches conflict, and nobody knows who's working on what." Solution: **central coordinator with task locking + git worktree isolation**.

### 1.2 Message-Passing vs. Shared State

| Approach | Pros | Cons | Best For |
|----------|------|------|----------|
| **Choreography** (queue-based) | Decentralized, simple, easy to extend | Hard to reason about complex flows | Linear pipelines |
| **Orchestration** (central coordinator) | Explicit flow, branching logic visible | Central point of failure (must be durable) | Complex conditional routing |
| **Shared State (Blackboard)** | Low token cost, agents read only what they need | Requires CAS/locking for concurrent writes | High-concurrency, long-running workflows |

**Recommendation:** Hybrid — **kanban as durable orchestrator** + **shared state store (Redis/Postgres) for checkpointing** + **structured JSON handoffs** at task boundaries.

### 1.3 Industry Patterns Comparison

| Framework | Coordination Model | Communication | Key Innovation |
|-----------|-------------------|---------------|----------------|
| **MetaGPT** | Assembly line (SOP-driven) | Publish-subscribe + structured docs | Role specialization + executable feedback |
| **ChatDev** | Chat chain (waterfall) | Instructor-Assistant dialogue | Communicative dehallucination |
| **OpenDevin/OpenHands** | Event stream + Docker sandbox | Step function (state→action) | Runtime isolation + delegation metadata |
| **SWE-agent** | Single agent + LIVEPLAN monitor | Trajectory monitoring | Deterministic drift detection + corrective steering |
| **Hermes Kanban** | Durable board + dispatcher | Structured handoff (summary + metadata) | Profile-based workers, git worktrees, circuit breaker |

---

## 2. Task Decomposition Strategies

### 2.1 Hierarchical Decomposition (Hermes Swarm Pattern)

```bash
# Hermes kanban swarm creates:
# 1. Root/blackboard card (completed)
# 2. N parallel worker cards
# 3. Verifier card (gated on all workers)
# 4. Synthesizer card (gated on verifier)
hermes kanban swarm "Design multi-region failover plan" \
  --workers researcher,architect,sre \
  --verifier reviewer --synthesizer writer
```

### 2.2 Phase-Gated Lifecycle (Agentic AI Megaproject Template)

| Phase | Entry Criteria | Exit Criteria | Agents |
|-------|----------------|---------------|--------|
| **Inception** | Raw idea | Signed PRD + ADRs | PM, Architect |
| **Elaboration** | Approved PRD | Design docs + Contracts | Architect, Engineer |
| **Construction** | Frozen design | Working code + Tests | Engineer, QA |
| **Transition** | All tests pass | Deployed + Monitored | DevOps, SRE |

**Key Principle:** "Stop agents from writing production code before requirements, architecture decisions, and quality gates exist."

### 2.3 Work Packets with File Ownership

```
Work Packet = {
  owned_files: ["src/auth/*.py"],
  forbidden_files: ["src/billing/*.py"],
  deliverables: ["auth/schema.sql", "auth/api.py"],
  acceptance_criteria: ["tests pass", "lint clean"]
}
```

**Prevents:** Two agents trampling each other's files. **Enables:** Parallel execution with bounded scope.

### 2.4 Decomposition Heuristics

1. **Single Responsibility:** Each task assignable to ONE specialist profile
2. **Independent Verification:** Each task has clear acceptance criteria
3. **Bounded Scope:** Task completable in <2 hours (prevents context overflow)
4. **Explicit Dependencies:** Parent→child links visible on board
5. **Traceability:** Requirement → Use Case → Design → Contract → Test

---

## 3. Conflict Prevention

### 3.1 Git Branch Strategies

| Strategy | Isolation Level | Merge Complexity | Use Case |
|----------|-----------------|------------------|----------|
| **Per-Task Worktree** (Hermes/PraisonAI) | Full (separate checkout) | Auto squash-merge on approval | Concurrent writers on same repo |
| **Per-Agent Branch** | Branch-level | Manual PR + review | Long-lived agent personas |
| **Shared Branch + File Locks** | File-level | Low (but conflicts possible) | Read-heavy, write-rare |

**Hermes Implementation:** `workspace_kind: "worktree"` creates `~/.hermes/kanban/worktrees/<task_id>` on branch `kanban/<task_id>`. On completion: `git merge --no-ff --no-commit` → follow-up commit. Conflicts → task blocked, worktree preserved.

### 3.2 File Ownership & Write Isolation

**Pattern: Shared Read, Isolated Write (LangGraph Reducer Pattern)**

```python
class CoordinationState(TypedDict):
    # Shared read: all agents see
    task: str
    config: dict
    # Isolated write with merge: append-only
    messages: Annotated[list[str], operator.add]
    artifacts: Annotated[list[dict], operator.add]
    # Owned keys: single writer per key
    draft: str          # writer owns
    review: str         # reviewer owns
    final: str          # publisher owns
```

**Three Conflict Scenarios:**
1. **Write-Write:** Two agents update same key → Version stamps / CAS
2. **Read-Write:** Agent acts on stale data → Version check before acting
3. **Semantic:** Contradictory outputs → Reconciliation step routes to decision-maker

---

## 4. State Management

### 4.1 Four State Classes (Agent State Management Patterns Spec)

| Class | Lifetime | Content | Latency Budget | Storage |
|-------|----------|---------|----------------|---------|
| **Short-term Context** | Current LLM call | Recent messages, tool results | <10 ms | In-process |
| **Working Scratchpad** | Single agent run | Plan, intermediate results | <50 ms | Redis / In-process |
| **Long-term Memory** | User/tenant lifetime | Preferences, episodic facts | <200 ms | Vector DB + SQL |
| **Durable Workflow State** | Workflow lifetime | Step status, signals, retries | <500 ms | Workflow engine (Temporal/LangGraph) |

### 4.2 Checkpoint Contract (LangGraph Standard)

Every checkpoint MUST contain:
- Unique monotonically increasing ID
- Thread/run identifier
- Serialized working scratchpad
- Current step pointer
- Error history + retry counters
- Timestamp + agent/model version

**Write checkpoints BEFORE external side effects** → enables crash-proof execution with idempotency keys.

### 4.3 Handoff Protocol (Minimal Viable)

```python
@dataclass
class HandoffPayload:
    source_agent: str
    target_agent: str
    task_id: str
    work_product: dict[str, Any]      # {"result": ..., "status": ...}
    context: dict[str, Any]           # reasoning, constraints, decisions
    constraints: list[str]            # what was tried and failed
    timestamp: str
    attempt: int = 1
    max_attempts: int = 3
    idempotency_key: str = ""         # hash(trace_id + step)
    trace_id: str = ""                # propagates across all agents
    decision_provenance: dict         # model, prompt version, tool calls
    side_effect_manifest: list[str]   # external writes committed
    failure_mode_declaration: dict    # retryable vs escalate errors
```

**Six Required Fields in Every Production Contract** (isimplifyme.com):
1. Schema version (semver)
2. Idempotency key
3. Trace ID
4. Decision provenance
5. Side-effect manifest
6. Failure-mode declaration

### 4.4 Context Window Management

| Technique | When to Use | Token Savings |
|-----------|-------------|---------------|
| **Summarization at boundary** | Downstream needs reasoning fidelity | 60-80% |
| **Reference-by-ID (shared store)** | Downstream needs side-effect awareness | 90%+ |
| **Selective field passing (schema)** | Compliance audit required | 95%+ |

**Rule:** Pure context passing breaks beyond 4-5 agents or 4K+ tokens. Flush to event bus at hop 3-4.

---

## 5. Failure Recovery

### 5.1 Circuit Breaker & Retry (Hermes Kanban)

| Failure Type | Detection | Response |
|--------------|-----------|----------|
| **Spawn Failure** (missing creds, model 404) | Dispatcher catches RuntimeError | Retry up to `max_retries` (default 2), then `blocked` with `gave_up` |
| **Worker Crash** (OOM, segfault) | Dispatcher polls `kill(pid, 0)` | Release claim → task back to `ready` → fresh worker |
| **Task Timeout** | TTL expiry (default 30 min lock) | Auto-expire lock → reassign |

### 5.2 Bounded Retry Between Agents

```python
class BoundedRetry:
    max_attempts: int = 3
    current_attempt: int = 0
    feedback_history: list[str] = []
    
    def should_continue(self, feedback: str) -> RetryAction:
        self.current_attempt += 1
        self.feedback_history.append(feedback)
        if self.current_attempt >= self.max_attempts:
            return RetryAction.ESCALATE
        # Detect non-convergence: same feedback repeating
        if len(self.feedback_history) >= 2 and \
           self.feedback_history[-1] == self.feedback_history[-2]:
            return RetryAction.ESCALATE
        return RetryAction.RETRY
```

**Degradation Strategy:** On escalation → human review, not infinite loop.

### 5.3 Recovery Mechanisms (Production-Grade)

| Mechanism | Purpose | Implementation |
|-----------|---------|----------------|
| **Idempotency Keys** | Prevent duplicate work on retry | Hash(trace_id + step) per handoff |
| **Dead Letter Queues** | Capture exhausted retries | SQS/EventBridge DLQ for human review |
| **Compensating Transactions** | Undo partial side effects | Orchestrator holds inverse of each write |
| **Checkpoint Resume** | Restart from last success | Persist state after every step (Redis/Postgres) |

---

## 6. Monitoring & Observability

### 6.1 Artifact Age (Superior to Liveness)

**Definition:** Time since last verifiable forward-moving output.

```python
Artifact Age = T_current - T_last_valid_artifact

# Artifacts = data outputs, state transitions, tool successes, final answers
# NOT log lines or heartbeats
```

**Thresholds:**
- Warning: 30s (log, alert)
- Critical: 120s (inject context nudge)
- Kill: 300s (SIGKILL + restart)

### 6.2 Agent Health State Machine (Zylos Research)

```
IDLE → ACTIVE → (WAITING) → COMPLETED
                ↓
              STUCK (no progress > 3× expected duration)
                ↓
               ERROR
```

### 6.3 Key Metrics & Alerts

| Metric | Warning | Critical | Action |
|--------|---------|----------|--------|
| **Task Completion Rate** | <95% | <90% | Rollback deployment |
| **P95 Response Time** | >2s | >5s | Review model/tool latency |
| **Cost per Success** | >$0.03 | >$0.05 | Investigate loop/over-tooling |
| **Tool Error Rate** | >3% | >5% | Check integration health |
| **Context Utilization** | >80% | >95% | Trigger compaction/pause |
| **Token Loop Rate** | >5× baseline | — | Flag for review |
| **Stuck Agent** | >3× expected duration | — | Alert + auto-restart attempt |
| **Fleet Error Rate** | >5% over 5min | — | Notify on-call |

### 6.4 Trajectory Scoring (Future AGI / LIVEPLAN)

- **Deterministic monitor** examines trajectory signals (no LLM)
- **Detects:** Oscillations, plan violations, context poisoning, off-task drift
- **Advisor LLM** only invoked when monitor fires → corrective next-step advice
- **Results:** Up to 15.2% resolution rate improvement on SWE-bench

---

## 7. Concrete Recommendations for Multi-Agent Workflow Platform

### 7.1 Immediate Setup (Week 1)

1. **Enable Hermes Kanban with Worktree Isolation**
   ```yaml
   # config.yaml
   kanban:
     dispatch_in_gateway: true
     failure_limit: 2
   auxiliary:
     kanban_decomposer:
       model: "claude-3-5-sonnet"
   ```

2. **Define 19 Specialist Profiles** (matching current tmux setup):
   - `backend-dev`, `frontend-dev`, `qa-dev`, `devops`, `architect`
   - `researcher`, `writer`, `reviewer`, `security-auditor`, `data-engineer`
   - `mobile-dev`, `ml-engineer`, `sre`, `tech-writer`, `product-manager`
   - `release-manager`, `performance-engineer`, `ux-designer`

3. **Create Base Board Structure:**
   ```bash
   hermes kanban init
   # Create swimlanes: backend, frontend, infra, qa, docs, research
   ```

### 7.2 Workflow Patterns to Implement

| Pattern | Hermes Implementation | When to Use |
|---------|----------------------|-------------|
| **Feature Pipeline** | Schema → API → Tests (parent deps) | Sequential dependencies |
| **Fleet Farming** | Parallel tasks, same assignee pool | Independent bulk work (translations, tests) |
| **Role Pipeline + Review** | Implement → Review → Changes → Re-review | Quality-critical code |
| **Circuit Breaker** | `max_retries: 3` on flaky tasks | External deploys, API calls |

### 7.3 State & Handoff Standards

1. **Mandatory `kanban_complete` metadata:**
   ```json
   {
     "changed_files": ["src/auth/login.py"],
     "decisions": ["JWT with 15min access, 7day refresh"],
     "tests_run": 12,
     "test_results": "all_passed",
     "constraints_discovered": ["legacy bcrypt config incompatible"]
   }
   ```

2. **Structured handoff schema** (enforce via `kanban_request_review`):
   - Trace ID propagation across all tasks
   - Idempotency key on every handoff
   - Decision provenance (model, prompt version, tool calls)

### 7.4 Observability Stack

1. **Dashboard:** `hermes dashboard` (Kanban view + lane grouping)
2. **Artifact Age Monitoring:** Custom monitor checking `kanban_heartbeat` timestamps
3. **Trajectory Scoring:** Integrate LIVEPLAN-style deterministic monitor
4. **Alerting:** Telegram/Slack webhook on `gave_up`, `blocked`, `stalled` events
   ```bash
   hermes kanban notify-subscribe <task> --platform telegram --chat-id <id>
   ```

### 7.5 Conflict Prevention Rules

| Rule | Enforcement |
|------|-------------|
| **One writer per file** | Work packets with `owned_files` / `forbidden_files` |
| **Worktree per concurrent task** | `workspace_kind: "worktree"` default for all tasks |
| **No direct main-branch commits** | All merges via kanban review → squash-merge |
| **ADR for architectural decisions** | `docs/adr/` with immutable IDs, reversal conditions |

### 7.6 Failure Recovery Playbook

| Scenario | Detection | Recovery |
|----------|-----------|----------|
| Worker OOM | Dispatcher PID check fails | Auto-retry with chunked strategy (see tutorial) |
| Missing credentials | Spawn fails with `RuntimeError` | Circuit breaker → `blocked` → human adds creds → `unblock` |
| Merge conflict | Git merge fails on complete | Task blocked, worktree preserved, conflicted files listed |
| Stalled agent | Artifact Age > 120s | Context nudge → if persists, kill + restart from checkpoint |
| Infinite review loop | BoundedRetry hits max_attempts | Escalate to human with full feedback history |

---

## 8. Advanced Patterns for Future Evolution

### 8.1 Multi-Agent Economies (MetaGPT Outlook)
- Agents as service providers with costs
- Supply/demand credit assignment (EOM)
- Dynamic SOP adaptation based on project history

### 8.2 Evolving Orchestration (ChatDev 2.0)
- Learnable central orchestrator (RL-optimized)
- Dynamic agent activation/sequencing
- Puppeteer-style coordination

### 8.3 Self-Improving Constraints (MetaGPT Appendix A)
- Agents review past feedback → update constraint prompts
- Long-term memory inherits lessons across projects
- Future: optimize communication protocols, not just role constraints

---

## 9. References & Sources

### Academic Papers
1. **MetaGPT** (Hong et al., 2023) — arXiv:2308.00352
2. **ChatDev** (Qian et al., 2023) — arXiv:2307.07924
3. **Agentic Systems Patterns** (Turitto, 2024) — gturitto.github.io
4. **Agentic AI in SDLC** (2026) — arXiv:2604.26275
5. **ParallelPilot** (2026) — arXiv:2609.33113
6. **ResonAct** (2026) — arXiv:2609.34701
7. **LIVEPLAN** (2026) — arXiv:2608.06701
8. **Effective Async Strategies** (2026) — arXiv:2603.21489

### Industry Frameworks
- **ATC-Kanban** (JSCOP) — Git worktree isolation + MCP
- **Kandev** (kdlbs) — Multi-provider, worktrees, sub-tasks
- **Kagan** (OpenCode plugin) — Supervised tasks with intake/review gates
- **Agentic AI Megaproject Template** — Phase gates, work packets, ADRs
- **Cognition/Devin** — Smart friend pattern, manager coordination
- **Future AGI Gateway** — Per-task traces, trajectory scoring

### Hermes Native
- **Kanban Overview** — https://hermes-agent.nousresearch.com/docs/user-guide/features/kanban
- **Kanban Tutorial** — https://hermes-agent.nousresearch.com/docs/user-guide/features/kanban-tutorial
- **Background Systems** — `hermes-agent` skill references/background-systems.md

---

## Appendix: Quick-Start Commands for Multi-Agent Workflow Platform

```bash
# 1. Initialize kanban board
hermes kanban init

# 2. Create specialist profiles (repeat for all 19)
hermes profile create backend-dev --model claude-3-5-sonnet --tools "terminal,file,git,web"
hermes profile create frontend-dev --model claude-3-5-sonnet --tools "terminal,file,git,web,browser"
# ... etc

# 3. Create first feature pipeline
SCHEMA=$(hermes kanban create "Design auth schema" \
  --assignee backend-dev --tenant multi-agent-workflow --priority 10 \
  --body "User/session/token schema for Multi-Agent Workflow Platform" --json | jq -r .id)

API=$(hermes kanban create "Implement auth API" \
  --assignee backend-dev --tenant multi-agent-workflow --priority 10 \
  --parent $SCHEMA --body "POST /register, /login, /refresh, /logout" --json | jq -r .id)

hermes kanban create "Write auth integration tests" \
  --assignee qa-dev --tenant multi-agent-workflow --priority 10 \
  --parent $API --body "Happy path, wrong password, expired token, concurrent refresh"

# 4. Start gateway (runs dispatcher)
hermes gateway start

# 5. Monitor
hermes dashboard  # http://127.0.0.1:9119
hermes kanban watch --kinds completed,gave_up,timed_out
```

---

*Report generated: 2026-10-09 | Researcher: sdlc-researcher | Task: t_ca94c155*