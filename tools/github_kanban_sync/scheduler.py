"""Scheduler/daemon: run the sync automatically, without manual steps (Issue #192).

The poll is authoritative (see ``webhook.py`` for the optional accelerator), so the
autostart path is a small, bounded, controllable loop around the existing
``ingest`` + ``publish`` cycle:

* **incremental** — every cycle reuses the persisted cursors/ETags in the ledger,
  so a no-op poll is a cheap ``304`` and only new events are delivered;
* **backoff** — transient GitHub failures (5xx / transport) and exhausted
  rate-limit budgets are absorbed by an exponential backoff, never by spinning;
  a ``RateLimited`` reset is honoured (capped) instead of a blind retry;
* **bounded & stoppable** — ``run(max_iterations=...)`` / ``--once`` bound the
  loop, a pidfile makes a second daemon refuse to start, and ``SIGINT``/``SIGTERM``
  (or ``--stop``) shut it down cleanly. Nothing here is an unkillable process.

Every cycle writes a snapshot (so ``observability`` can report a real
``last_sync``/``lag``) and a compact ``scheduler`` state row (status, iteration,
consecutive failures, next run) so ``status``/``health`` answer "is it running and
is it healthy?" without reading the logs.
"""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import threading
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Optional

from .config import Settings
from .github import GitHubError, RateLimited, TransientError
from .store import Store

SCHEDULER_STATE_KEY = "scheduler:state"


def _iso(now: float) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now))


@dataclass(frozen=True)
class SchedulerConfig:
    """Tuning for the autostart loop (env-overridable, safe defaults)."""

    interval: float = 300.0          # seconds between successful cycles
    jitter: float = 0.0              # extra random 0..jitter seconds per cycle
    backoff_base: float = 5.0        # first backoff step after a failure
    backoff_cap: float = 900.0       # maximum backoff / rate-limit wait
    health_max_lag: float = 600.0    # lag above which a cycle logs unhealthy

    @classmethod
    def from_env(cls, **overrides: Any) -> "SchedulerConfig":
        def _num(name: str, default: float) -> float:
            raw = os.environ.get(name)
            if raw is None or raw == "":
                return default
            try:
                return float(raw)
            except ValueError:
                return default

        values = {
            "interval": _num("GKS_SYNC_INTERVAL", 300.0),
            "jitter": _num("GKS_SYNC_JITTER", 0.0),
            "backoff_base": _num("GKS_SYNC_BACKOFF_BASE", 5.0),
            "backoff_cap": _num("GKS_SYNC_BACKOFF_CAP", 900.0),
            "health_max_lag": _num("GKS_SYNC_HEALTH_MAX_LAG", 600.0),
        }
        values.update({k: v for k, v in overrides.items() if v is not None})
        return cls(**values)


class AlreadyRunning(RuntimeError):
    """Raised when a live daemon already owns the pidfile."""

    def __init__(self, pid: int, path: Path):
        super().__init__(f"another gks daemon is already running (pid {pid}, pidfile {path})")
        self.pid = pid
        self.path = path


def _process_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True  # exists but owned by another user
    return True


class PidFile:
    """A single-writer pidfile: refuse a second daemon, make ``stop`` reliable."""

    def __init__(self, path: str | Path):
        self.path = Path(path)

    def read_pid(self) -> Optional[int]:
        try:
            raw = self.path.read_text().strip()
        except OSError:
            return None
        return int(raw) if raw.isdigit() else None

    def acquire(self) -> int:
        existing = self.read_pid()
        if existing is not None and _process_alive(existing):
            raise AlreadyRunning(existing, self.path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(str(os.getpid()))
        return os.getpid()

    def release(self) -> None:
        pid = self.read_pid()
        if pid is not None and pid != os.getpid():
            return  # not ours
        try:
            self.path.unlink()
        except FileNotFoundError:
            pass


def stop_daemon(path: str | Path, *, timeout: float = 10.0,
                sig: int = signal.SIGTERM) -> dict[str, Any]:
    """Signal the daemon named by ``path`` to stop and wait for it to exit."""
    pidfile = PidFile(path)
    pid = pidfile.read_pid()
    if pid is None:
        return {"stopped": False, "reason": "no_pidfile", "pidfile": str(path)}
    if not _process_alive(pid):
        try:
            pidfile.path.unlink()
        except FileNotFoundError:
            pass
        return {"stopped": False, "reason": "stale_pidfile", "pid": pid, "pidfile": str(path)}
    try:
        os.kill(pid, sig)
    except OSError as exc:  # pragma: no cover - race
        return {"stopped": False, "reason": f"signal_failed:{exc}", "pid": pid}
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not _process_alive(pid):
            pidfile.release()
            return {"stopped": True, "pid": pid, "pidfile": str(path)}
        time.sleep(0.1)
    return {"stopped": False, "reason": "timeout", "pid": pid, "pidfile": str(path)}


class Scheduler:
    """Drive ``ingest`` + ``publish`` on an interval with backoff and observability."""

    def __init__(
        self,
        settings: Settings,
        *,
        store: Store,
        board,
        gh,
        config: Optional[SchedulerConfig] = None,
        now: Callable[[], float] = time.time,
        sleep: Callable[[float], None] = time.sleep,
        log: Optional[Callable[[str], None]] = None,
        stop_event: Optional[threading.Event] = None,
        repo_root: Optional[str | Path] = None,
    ):
        self.settings = settings
        self.store = store
        self.board = board
        self.gh = gh
        self.config = config or SchedulerConfig()
        self._now = now
        self._sleep = sleep
        self._log_fn = log
        self._stop = stop_event or threading.Event()
        self.repo_root = str(repo_root) if repo_root else os.environ.get("GKS_REPO_ROOT", ".")
        self.iteration = 0
        self.consecutive_failures = 0
        self.started_at: Optional[float] = None
        self.last_cycle_at: Optional[float] = None
        self.next_run_at: Optional[float] = None
        self.last_result: Optional[dict[str, Any]] = None

    # -- control -----------------------------------------------------------
    def request_stop(self) -> None:
        self._stop.set()

    @property
    def stopped(self) -> bool:
        return self._stop.is_set()

    def log(self, event: str, **fields: Any) -> None:
        record = {
            "ts": _iso(self._now()),
            "component": "gks.scheduler",
            "event": event,
            "pid": os.getpid(),
            **fields,
        }
        line = json.dumps(record, sort_keys=True, ensure_ascii=False, default=str)
        (self._log_fn or (lambda s: print(s, flush=True)))(line)

    # -- one cycle ---------------------------------------------------------
    def run_once(self) -> dict[str, Any]:
        """Run a single full cycle: ingest Issues + PRs, then publish pending.

        GitHub transport errors (``RateLimited`` / ``TransientError`` /
        ``GitHubError``) propagate so :meth:`run` can back off; a snapshot is only
        recorded on success, so ``lag`` genuinely grows while the sync is down.
        """
        from .ingest import Ingestor
        from .publish import Publisher

        self.iteration += 1
        correlation_id = f"cycle:{self.iteration}:{uuid.uuid4().hex[:8]}"
        ingestor = Ingestor(self.store, self.gh, self.board, self.settings)
        publisher = Publisher(self.store, self.gh, self.board, self.settings)

        # GitHub transport errors propagate (the loop backs off); a board-side
        # failure (e.g. an as-yet-uninitialised kanban.db) must not discard a
        # successful ingest, so only the publish step is isolated.
        issues = ingestor.ingest_issues()
        pulls = ingestor.ingest_pulls()
        errors: list[str] = []
        try:
            published = publisher.publish_pending()
        except (RateLimited, TransientError, GitHubError):
            raise
        except Exception as exc:  # noqa: BLE001
            published = {"results": [], "error": str(exc)}
            errors.append(f"publish: {exc}")

        result: dict[str, Any] = {
            "iteration": self.iteration,
            "correlation_id": correlation_id,
            "issues": issues,
            "pulls": pulls,
            "publish": published,
            "errors": errors,
            "new_events": int(issues.get("new_events", 0)) + int(pulls.get("new_events", 0)),
            "published": sum(1 for r in published.get("results", [])
                             if r.get("status") in ("created", "updated")),
        }
        self.store.record_snapshot({
            "origin_main": self._origin_main(),
            "ci_state": "unknown",
            "open_prs": 0,
            "correlation_id": correlation_id,
        })
        self.last_cycle_at = self._now()
        self.last_result = result
        return result

    # -- the loop ----------------------------------------------------------
    def run(self, *, max_iterations: Optional[int] = None) -> dict[str, Any]:
        """Loop until stopped or ``max_iterations`` cycles have run."""
        self.started_at = self._now()
        self._write_state("running")
        self.log("daemon.start", interval=self.config.interval,
                 max_iterations=max_iterations)
        while not self._stop.is_set():
            if max_iterations is not None and self.iteration >= max_iterations:
                break
            delay = self._run_iteration()
            if self._stop.is_set():
                break
            self.next_run_at = self._now() + delay
            self._interruptible_sleep(delay)
        self.next_run_at = None
        self._write_state("stopped")
        self.log("daemon.stop", iterations=self.iteration,
                 consecutive_failures=self.consecutive_failures)
        return {"iterations": self.iteration,
                "consecutive_failures": self.consecutive_failures,
                "last_result": self.last_result}

    def _run_iteration(self) -> float:
        try:
            result = self.run_once()
        except RateLimited as exc:
            return self._on_failure("cycle.rate_limited", exc,
                                    lambda: self._rate_limit_wait(exc),
                                    extra={"reset": exc.reset})
        except TransientError as exc:
            return self._on_failure("cycle.transient_error", exc, self._backoff)
        except GitHubError as exc:
            return self._on_failure("cycle.github_error", exc, self._backoff)
        except Exception as exc:  # noqa: BLE001 - a cycle must never kill the daemon
            return self._on_failure("cycle.error", exc, self._backoff)

        self.consecutive_failures = 0
        delay = self._base_delay()
        self._write_state("running")
        self.log("cycle.ok", iteration=result["iteration"],
                 correlation_id=result["correlation_id"],
                 new_events=result["new_events"], published=result["published"],
                 next_in=round(delay, 3), healthy=self._healthy())
        return delay

    def _on_failure(self, event: str, exc: BaseException,
                    wait: "float | Callable[[], float]",
                    extra: Optional[dict[str, Any]] = None) -> float:
        self.consecutive_failures += 1
        # ``wait`` is resolved AFTER the failure counter is bumped so an
        # exponential backoff starts at ``backoff_base`` (not one step behind).
        resolved = float(wait() if callable(wait) else wait)
        wait = max(0.0, min(resolved, self.config.backoff_cap))
        self.store.record_delivery(
            f"scheduler:{self.iteration}", "scheduler", "retry",
            detail=f"{type(exc).__name__}: {exc}", correlation_id=f"scheduler:{self.iteration}",
        )
        self._write_state("degraded")
        fields = {"iteration": self.iteration, "error": f"{type(exc).__name__}: {exc}",
                  "consecutive_failures": self.consecutive_failures,
                  "backoff_seconds": round(wait, 3)}
        if extra:
            fields.update(extra)
        self.log(event, **fields)
        return wait

    # -- helpers -----------------------------------------------------------
    def _base_delay(self) -> float:
        delay = max(0.0, self.config.interval)
        if self.config.jitter > 0:
            import random

            delay += random.uniform(0, self.config.jitter)
        return delay

    def _backoff(self) -> float:
        step = max(0, self.consecutive_failures - 1)
        return min(self.config.backoff_base * (2 ** step), self.config.backoff_cap)

    def _rate_limit_wait(self, exc: RateLimited) -> float:
        if exc.reset:
            wait = exc.reset - self._now()
            if wait > 0:
                return min(wait, self.config.backoff_cap)
        return self._backoff()

    def _healthy(self) -> bool:
        from .observability import health

        try:
            return bool(health(self.store, max_lag=self.config.health_max_lag)["healthy"])
        except Exception:  # noqa: BLE001
            return False

    def _interruptible_sleep(self, seconds: float) -> None:
        """Sleep in short slices so a stop request is honoured promptly."""
        if seconds <= 0:
            return
        slice_seconds = 0.5
        remaining = seconds
        while remaining > 0 and not self._stop.is_set():
            self._sleep(min(slice_seconds, remaining))
            remaining -= slice_seconds

    def _origin_main(self) -> Optional[str]:
        try:
            proc = subprocess.run(
                ["git", "-C", self.repo_root, "rev-parse", "origin/main"],
                capture_output=True, text=True, timeout=10,
            )
        except (OSError, subprocess.SubprocessError):
            return None
        return proc.stdout.strip() or None if proc.returncode == 0 else None

    def _write_state(self, status: str) -> None:
        state = {
            "status": status,
            "pid": os.getpid(),
            "started_at": _iso(self.started_at) if self.started_at else None,
            "iteration": self.iteration,
            "consecutive_failures": self.consecutive_failures,
            "last_cycle_at": _iso(self.last_cycle_at) if self.last_cycle_at else None,
            "next_run_at": _iso(self.next_run_at) if self.next_run_at else None,
            "interval_seconds": self.config.interval,
        }
        try:
            self.store.set_meta(SCHEDULER_STATE_KEY, state)
        except Exception:  # noqa: BLE001 - state is best-effort, never fatal
            pass


def _install_signal_handlers(scheduler: Scheduler) -> None:  # pragma: no cover
    def _handler(signum: int, _frame: Any) -> None:
        scheduler.log("daemon.signal", signal=int(signum))
        scheduler.request_stop()

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            signal.signal(sig, _handler)
        except (ValueError, OSError):  # non-main thread
            pass


def serve(
    settings: Settings,
    *,
    store: Store,
    board,
    gh,
    config: Optional[SchedulerConfig] = None,
    pidfile: Optional[str | Path] = None,
    once: bool = False,
    max_iterations: Optional[int] = None,
    log: Optional[Callable[[str], None]] = None,
) -> dict[str, Any]:
    """Convenience entry point used by the CLI: pidfile + signals + loop."""
    pf = PidFile(pidfile) if pidfile else None
    if pf is not None:
        pf.acquire()
    scheduler = Scheduler(settings, store=store, board=board, gh=gh,
                          config=config, log=log)
    if not once:
        _install_signal_handlers(scheduler)
    try:
        if once:
            result = scheduler.run_once()
            scheduler.log("cycle.ok", iteration=result["iteration"],
                          correlation_id=result["correlation_id"],
                          new_events=result["new_events"], published=result["published"],
                          healthy=scheduler._healthy())
            return {"once": True, "result": result}
        return scheduler.run(max_iterations=max_iterations)
    finally:
        if pf is not None:
            pf.release()


if __name__ == "__main__":  # pragma: no cover
    sys.exit(0)
