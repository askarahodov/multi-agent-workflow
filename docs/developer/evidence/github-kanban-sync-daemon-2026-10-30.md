# Evidence — autostart (scheduler/daemon) for github-kanban-sync (Issue #192), 2026-10-30

Task: `t_46fa19d5` — *автозапуск моста GitHub↔Kanban: scheduler/daemon (cursor/backoff)
или webhook; обмен без ручных шагов*.

**Mode chosen: scheduler/daemon (poll).** The host has no public ingress, so the
authoritative transport is the ETag/cursor poll; `webhook.py` stays an optional
accelerator (§5 runbook). The new `daemon` command drives the existing
`ingest` + `publish` cycle on an interval with exponential backoff, rate-limit-aware
sleeping, a single-writer pidfile and clean `SIGINT`/`SIGTERM` shutdown.

Base: `wt/t_02d18f3e` @ `b456e8d` (the parent integration candidate; PR #193).
All evidence below was produced from this worktree.

## 0. Test suites (CI gate emulation)

```
$ cd tools && python -m pytest tests -q
153 passed, 1 warning in 4.57s

$ cd tools && python -m pytest tests/test_gks_*.py -q
80 passed, 1 warning in 3.08s          # was 67 before this task (+13 scheduler tests)
```

`tools/tests/test_gks_scheduler.py` covers: one cycle ingest+publish with a real
snapshot (`last_sync`/`lag`), exponential backoff + cap, `RateLimited.reset`
honouring, stop-on-request, pidfile double-start guard, `daemon --stop` with
missing/stale pidfile, resilience to an uninitialised board, and the `scheduler`
block in `status`/`health`.

## 1. Demonstration **without any manual step** (hermetic)

`tools/github_kanban_sync/daemon_probe.py` starts a real `Scheduler` loop against a
fake GitHub transport and a throwaway board. While the daemon is *waiting between
cycles*, an external change is injected into **both** sides — a GitHub Issue revision
and a Kanban card event — and no `sync`/operator action is performed afterwards. The
running daemon picks both up on its next cycle.

```
$ GKS_REPO_ROOT=$PWD python3 tools/github_kanban_sync/daemon_probe.py
=== autostart demonstration (no manual sync call) ===
board comments before: 0
{"component": "gks.scheduler", "event": "daemon.start", "interval": 0.05, "max_iterations": 3, "pid": 699243, "ts": "2026-10-30T09:40:56Z"}
{"component": "gks.scheduler", "correlation_id": "cycle:1:5f044cc1", "event": "cycle.ok", "healthy": true, "iteration": 1, "new_events": 1, "next_in": 0.05, "pid": 699243, "published": 0, "ts": "2026-10-30T09:40:56Z"}
[inject] external change: GitHub issue updated + Kanban card event
{"component": "gks.scheduler", "correlation_id": "cycle:2:45f8615f", "event": "cycle.ok", "healthy": true, "iteration": 2, "new_events": 1, "next_in": 0.05, "pid": 699243, "published": 1, "ts": "2026-10-30T09:40:56Z"}
{"component": "gks.scheduler", "correlation_id": "cycle:3:2d3abff5", "event": "cycle.ok", "healthy": true, "iteration": 3, "new_events": 0, "next_in": 0.05, "pid": 699243, "published": 0, "ts": "2026-10-30T09:40:56Z"}
{"component": "gks.scheduler", "consecutive_failures": 0, "event": "daemon.stop", "iterations": 3, "pid": 699243, "ts": "2026-10-30T09:40:56Z"}
board ingest comments after: 2
  board comment id=1 marker=<!-- gks:v1 id=issue:192 event=askarahodov/multi-agent-workflow:issue:192:open:2026-10-30T10:00:00Z channel=ingest -->
  board comment id=2 marker=<!-- gks:v1 id=issue:192 event=askarahodov/multi-agent-workflow:issue:192:open:2026-10-30T10:05:00Z channel=ingest -->
github publish comments after: 1
  github comment starts: <!-- gks:v1 issue=192 channel=publish rev=1 -->
=== observability ===
{ "health": { "healthy": true, "lag_seconds": 0.735, "last_sync": "2026-10-30T09:40:56Z",
              "pending_events": 0, "errors": 0, "scheduler_status": "stopped", ... },
  "scheduler": { "status": "stopped", "iteration": 3, "consecutive_failures": 0, ... } }
RESULT: PASS (2 automatic GitHub->Kanban deliveries + 1 automatic Kanban->GitHub publish)
```

* cycle 1 delivered the initial Issue revision (GitHub → Kanban);
* the change injected during the wait was delivered **automatically** on cycle 2
  (`new_events: 1` + `published: 1` — the card event was published back to GitHub);
* cycle 3 is a clean no-op (`new_events: 0`).

## 2. Live loop against the real GitHub (incremental convergence)

Real repo + token (`gh auth token`), isolated throwaway home (real board untouched):

```
$ GKS_KANBAN_HOME=$(mktemp -d) python3 -m tools.github_kanban_sync.cli daemon --max-iterations 6 --interval 1
{"event": "cycle.ok", "iteration": 1, "new_events": 116, ...}
{"event": "cycle.ok", "iteration": 2, "new_events": 13,  ...}
{"event": "cycle.ok", "iteration": 3, "new_events": 0,   ...}
{"event": "cycle.ok", "iteration": 4, "new_events": 0,   ...}
{"event": "cycle.ok", "iteration": 5, "new_events": 0,   ...}
{"event": "cycle.ok", "iteration": 6, "new_events": 0,   ...}
{"event": "daemon.stop", "iterations": 6, "consecutive_failures": 0, ...}
```

The cursor/ETag advance: once the feed is caught up every cycle is a no-op
(`not_modified: true`, `new_events: 0`) — no re-delivery, no duplicate comments.

## 3. Live `daemon --once` + observability

```
$ GKS_KANBAN_HOME=$(mktemp -d) python3 -m tools.github_kanban_sync.cli daemon --once --interval 1
{"event": "cycle.ok", "iteration": 1, "new_events": 116, "healthy": true, ...}
{ "once": true, "result": { "issues": {"new_events": 16}, "pulls": {"new_events": 100},
                            "publish": {"error": "no such table: task_events"}, ... } }
$ ... daemon --once          # second, incremental cycle
{ "issues": {"new_events": 0, "not_modified": true}, "pulls": {"new_events": 0, "not_modified": true} }
$ ... health
{ "healthy": true, "last_sync": "2026-10-30T09:40:23Z", "lag_seconds": 0.293,
  "pending_events": 0, "errors": 0, "scheduler_status": null, ... }
```

Note: the throwaway home has an empty `kanban.db` (no `task_events` table), so the
publish step reports `no such table` — this is isolated (the cycle still records a
snapshot and `health` shows a real `last_sync`/`lag`), and does not occur against the
real board, which has the schema. Covered by `test_run_once_tolerates_uninitialised_board`.

## 4. Graceful shutdown on SIGTERM

```
$ GKS_KANBAN_HOME=$(mktemp -d) timeout --preserve-status -s TERM 9 \
      python3 -m tools.github_kanban_sync.cli daemon --interval 60
{"event": "cycle.ok", "iteration": 1, "new_events": 116, "next_in": 60.0, ...}
{"event": "daemon.signal", "signal": 15, ...}
{"event": "daemon.stop", "iterations": 1, "consecutive_failures": 0, ...}
# exit status 0 — the loop finished the current cycle, closed its connections and exited
```

## 5. Single-writer pidfile (no double start)

```
$ ... daemon --interval 60          # running, pidfile written
$ ... daemon --once                 # second start refused
{"error": "another gks daemon is already running (pid 700645, pidfile .../gks.pid)", "pid": 700645}
# rc = 24
```

`daemon --stop` reads the pidfile, sends SIGTERM, waits (`--stop-timeout`, default
10 s) and removes the pidfile; a stale pidfile (no such process) is reported as
`stale_pidfile` and cleaned up (unit-tested).

## 6. Environment note

On this host a process launched in the runtime's *background* mode has **no network
egress** (a plain `httpx` GET to `api.github.com` in that mode fails with
`ConnectTimeout`), so all live-GitHub evidence above was produced in the foreground.
This is a harness property, not a property of the tool; the daemon is intended to run
as a normal (foreground/systemd/cron) process where egress is available.
