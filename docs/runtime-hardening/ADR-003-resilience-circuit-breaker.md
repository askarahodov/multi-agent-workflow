# ADR-003: Resilience Patterns and Circuit Breaker Architecture

## Status
Accepted

## Context
Agent runtimes must degrade gracefully under resource pressure, dependency failures, and internal faults. The research (t_8aaf9df7) recommends Resilience4j patterns adapted to container runtimes, with a per-agent degradation ladder and bulkhead pools per resource class.

Key findings:
- Decorator order matters: **Bulkhead → TimeLimiter → RateLimiter → CircuitBreaker → Retry** (retries inside breaker; open breaker does not retry)
- Circuit breaker config: `slidingWindowSize ≥ 100`, `minimumNumberOfCalls ≥ 20`, `failureRateThreshold 50%`, `waitDurationInOpenState ≥ 30s`, `permittedNumberOfCallsInHalfOpenState ≥ 3`
- Retry storm amplification: 3 retries × 5 layers = 243× load amplification → token-bucket retry budget ≈10% of traffic, full jitter
- CB thrashing: tiny windows react to noise → use larger windows and multiple half-open successes
- Container-level degradation ladder: **FULL → THROTTLED (memory.high/cpu.max pressure) → READ_ONLY → PAUSED → TERMINATED**

## Decision
Implement a **two-layer resilience architecture**:

### Layer 1: Application-Level (Resilience4j-style)
For outbound dependencies (LLM APIs, tool services, databases):
- **Timeout (TimeLimiter)**: Per-endpoint SLA-based, `cancelRunningFuture: true`
- **Circuit Breaker**: Sliding window (≥100), min calls (≥20), 50% failure threshold, ≥30s open, ≥3 half-open successes
- **Bulkhead**: Semaphore-based `maxConcurrentCalls` per dependency (e.g., 25), small `maxWaitDuration`
- **Retry**: Max 3 attempts, exponential backoff ×2 + full jitter, **idempotent only**, ignore 4xx
- **Rate Limiter**: Token bucket per downstream quota
- **Fallback**: Stale cache / degraded response

Decorator order: **Bulkhead → TimeLimiter → RateLimiter → CircuitBreaker → Retry**

### Layer 2: Runtime-Level (Container/Agent)
For the agent sandbox itself, keyed on health/latency/resource pressure:
- **Per-agent circuit breaker** state machine: `CLOSED → OPEN → HALF_OPEN → CLOSED`
- **Bulkhead pools** per resource class: CPU, Memory, Disk I/O, Network (semaphore-based)
- **Degradation modes** (enforced by Resource Manager + Runtime API):
  1. **FULL**: Normal operation, all resources within soft limits
  2. **THROTTLED**: `memory.high` or `cpu.max` pressure detected → reduce `cpu.max`, apply `memory.high` throttle, reject new work
  3. **READ_ONLY**: Persistent pressure → `readOnlyRootFilesystem` enforced, no new executions, serve cached results only
  4. **PAUSED**: Critical pressure → `SIGSTOP` agent processes, retain state, stop scheduling
  5. **TERMINATED**: Unrecoverable → `SIGKILL` + cleanup, emit `terminated` event
- **Recovery coordinator**: Exponential backoff (base 2s, max 60s, jitter) with health-gate checks before promoting degradation mode

### State Transitions
```
FULL → (PSI high / memory.events{high} > 0 sustained) → THROTTLED
THROTTLED → (pressure clears for 2× backoff window) → FULL
THROTTLED → (pressure persists, memory.max approaching) → READ_ONLY
READ_ONLY → (pressure clears, resources freed) → THROTTLED → FULL
READ_ONLY → (OOM kill / unrecoverable) → PAUSED
PAUSED → (manual intervention / auto-recovery policy) → TERMINATED or THROTTLED
```

### Retry Budget (Cross-Layer)
- Global token-bucket retry budget: **10% of total request volume**
- Refill rate: 1 token per 10 requests
- Consumed on each retry attempt (both layers)
- When exhausted: fail fast, no retries

## Consequences
**Benefits:**
- Proven Resilience4j patterns at application layer
- Runtime-layer degradation aligns with cgroup v2 signals (PSI, memory.events)
- Bulkhead pools prevent single-agent resource monopolization
- Degradation ladder provides clear operational semantics and recovery paths
- Retry budget prevents cascade amplification

**Trade-offs:**
- Two-layer CB adds complexity; must coordinate state (e.g., runtime CB open should short-circuit app CB)
- `memory.high` throttling as THROTTLED trigger may cause false positives under burst → tune `memory.high` ≈ 80% and require sustained signal
- READ_ONLY mode requires application cooperation (idempotent reads, cached writes)

**Risks:**
- R11: Retry storm amplification → Critical. Mitigate: token-bucket budget 10%, full jitter, idempotent-only
- R12: CB thrashing from small windows → High. Mitigate: slidingWindowSize ≥ 100, minCalls ≥ 20, ≥30s open, ≥3 half-open
- R13: Orphaned workspaces from crashed degradation → High. Mitigate: reaper/finalizer, `--die-with-parent`, force-cleanup timeout