"""Tests for the autostart scheduler/daemon (Issue #192 §autostart).

Covers: one cycle ingests + publishes and records a snapshot (so ``last_sync``/
``lag`` become real), the loop backs off on transient/rate-limit failures, the
loop stops on request, and the pidfile guards against a double start.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

from tools.github_kanban_sync import cli, links, observability
from tools.github_kanban_sync.config import Settings
from tools.github_kanban_sync.scheduler import (
    AlreadyRunning,
    PidFile,
    Scheduler,
    SchedulerConfig,
    stop_daemon,
)
from tools.github_kanban_sync.store import Store
from tools.tests._gks_helpers import add_task, board, client_with, json_response, make_kanban_db

REPO = "askarahodov/multi-agent-workflow"


def _settings(tmp_path, db):
    return Settings(repo=REPO, board="me", coord_db=tmp_path / "coord.db", kanban_db=db)


def _issue_handler(issues, *, pulls=None, comments=None, posted=None):
    """A MockTransport handler serving the issues/pulls/comments feeds."""

    def handler(request):
        path = request.url.path
        if path.endswith("/comments"):
            if request.method == "POST":
                if posted is not None:
                    posted.append(json.loads(request.content.decode()))
                return json_response({"id": 111})
            return json_response(comments or [])
        if path.endswith("/pulls"):
            return json_response(pulls or [])
        if path.endswith("/issues"):
            return json_response(issues)
        return json_response({})

    return handler


def test_run_once_ingests_and_records_snapshot(tmp_path):
    db = make_kanban_db(tmp_path)
    add_task(db, "t_dev")
    settings = _settings(tmp_path, db)
    store = Store(settings.coord_db)
    links.bind(store, REPO, 192, "me", "t_dev")
    kb = board(db)
    issue = {"number": 192, "state": "open", "title": "x",
             "updated_at": "2026-10-30T11:00:00Z", "html_url": "https://example/192"}
    gh = client_with(_issue_handler([issue]))
    sched = Scheduler(settings, store=store, board=kb, gh=gh,
                      config=SchedulerConfig(interval=1.0), log=lambda _s: None)

    result = sched.run_once()

    assert result["new_events"] == 1
    assert len(kb.ingest_comments("t_dev")) == 1
    snapshot = store.last_snapshot()
    assert snapshot is not None and snapshot["taken_at"]
    assert observability.health(store, max_lag=10_000)["last_sync"] == snapshot["taken_at"]
    store.close()
    kb.close()


def test_run_once_publishes_board_change(tmp_path):
    db = make_kanban_db(tmp_path)
    add_task(db, "t_dev")
    settings = _settings(tmp_path, db)
    store = Store(settings.coord_db)
    links.bind(store, REPO, 192, "me", "t_dev")
    kb = board(db)
    # a real, externally-meaningful board change (author is NOT the sync itself)
    kb.record_event("t_dev", "status_changed", {"status": "done", "author": "sdlc-developer"})
    posted: list[dict] = []
    gh = client_with(_issue_handler([], comments=[], posted=posted))
    sched = Scheduler(settings, store=store, board=kb, gh=gh,
                      config=SchedulerConfig(interval=1.0), log=lambda _s: None)

    result = sched.run_once()

    assert result["published"] == 1
    assert posted and posted[0]["body"].startswith("<!-- gks:v1 issue=192 channel=publish")
    store.close()
    kb.close()


def test_run_once_tolerates_uninitialised_board(tmp_path):
    """A board without the sync-relevant tables must not discard a good ingest."""
    db = tmp_path / "empty.db"  # exists but has no schema (fresh home)
    db.write_text("")
    settings = _settings(tmp_path, db)
    store = Store(settings.coord_db)
    kb = board(db)
    issue = {"number": 192, "state": "open", "updated_at": "2026-10-30T11:00:00Z"}
    gh = client_with(_issue_handler([issue]))
    sched = Scheduler(settings, store=store, board=kb, gh=gh,
                      config=SchedulerConfig(interval=1.0), log=lambda _s: None)

    result = sched.run_once()

    assert result["errors"] and result["errors"][0].startswith("publish:")
    assert store.last_snapshot() is not None  # snapshot still recorded
    store.close()
    kb.close()


def test_backoff_schedule_is_exponential_and_capped():
    settings = Settings(coord_db=Path(":memory:"), kanban_db=Path(":memory:"))
    sched = Scheduler(settings, store=Store(":memory:"), board=None, gh=None,
                      config=SchedulerConfig(backoff_base=1.0, backoff_cap=5.0))
    waits = []
    for failures in range(1, 6):
        sched.consecutive_failures = failures
        waits.append(sched._backoff())
    assert waits == [1.0, 2.0, 4.0, 5.0, 5.0]


def test_rate_limit_wait_honours_reset_capped():
    settings = Settings(coord_db=Path(":memory:"), kanban_db=Path(":memory:"))
    sched = Scheduler(settings, store=Store(":memory:"), board=None, gh=None,
                      config=SchedulerConfig(backoff_cap=100.0), now=lambda: 1000.0)
    from tools.github_kanban_sync.github import RateLimited

    assert sched._rate_limit_wait(RateLimited("x", reset=1005)) == 5.0
    # a reset far in the future is capped, never an unbounded sleep
    assert sched._rate_limit_wait(RateLimited("x", reset=10**9)) == 100.0
    # a missing/past reset falls back to the backoff schedule
    sched.consecutive_failures = 1
    assert sched._rate_limit_wait(RateLimited("x", reset=None)) == sched.config.backoff_base


def test_loop_backs_off_on_transient_error(tmp_path):
    db = make_kanban_db(tmp_path)
    add_task(db, "t_dev")
    settings = _settings(tmp_path, db)
    store = Store(settings.coord_db)
    kb = board(db)
    gh = client_with(lambda r: json_response({"message": "boom"}, status=500))
    slept: list[float] = []
    sched = Scheduler(settings, store=store, board=kb, gh=gh,
                      config=SchedulerConfig(interval=0.01, backoff_base=1.0, backoff_cap=100.0),
                      sleep=slept.append, log=lambda _s: None)

    outcome = sched.run(max_iterations=3)

    assert outcome["iterations"] == 3
    assert sched.consecutive_failures == 3
    assert round(sum(slept), 3) == 7.0  # 1 + 2 + 4
    retries = [d for d in store.delivery_journal(20) if d["channel"] == "scheduler"]
    assert len(retries) == 3 and all(d["status"] == "retry" for d in retries)
    # a failing sync must NOT record a snapshot, so lag keeps growing
    assert store.last_snapshot() is None
    store.close()
    kb.close()


def test_loop_respects_rate_limit_reset(tmp_path):
    db = make_kanban_db(tmp_path)
    add_task(db, "t_dev")
    settings = _settings(tmp_path, db)
    store = Store(settings.coord_db)
    kb = board(db)
    reset = 10**9

    def handler(request):
        return json_response({"message": "rate limited"}, status=403,
                             headers={"x-ratelimit-remaining": "0",
                                      "x-ratelimit-reset": str(reset)})

    gh = client_with(handler)
    slept: list[float] = []
    sched = Scheduler(settings, store=store, board=kb, gh=gh,
                      config=SchedulerConfig(interval=0.01, backoff_cap=5.0),
                      now=lambda: 10**9 - 5, sleep=slept.append, log=lambda _s: None)

    outcome = sched.run(max_iterations=1)

    assert outcome["iterations"] == 1
    assert round(sum(slept), 3) == 5.0  # min(reset-now, cap)
    store.close()
    kb.close()


def test_stop_event_ends_loop(tmp_path):
    db = make_kanban_db(tmp_path)
    add_task(db, "t_dev")
    settings = _settings(tmp_path, db)
    store = Store(settings.coord_db)
    links.bind(store, REPO, 192, "me", "t_dev")
    kb = board(db)
    issue = {"number": 192, "state": "open", "updated_at": "2026-10-30T11:00:00Z"}
    gh = client_with(_issue_handler([issue]))
    import threading

    stop = threading.Event()
    sched = Scheduler(settings, store=store, board=kb, gh=gh,
                      config=SchedulerConfig(interval=0.01),
                      sleep=lambda _s: stop.set(), stop_event=stop, log=lambda _s: None)

    outcome = sched.run()

    assert outcome["iterations"] == 1  # stopped during the first wait
    store.close()
    kb.close()


def test_pidfile_guards_double_start(tmp_path):
    path = tmp_path / "gks.pid"
    first = PidFile(path)
    first.acquire()
    assert path.exists()
    with pytest.raises(AlreadyRunning):
        PidFile(path).acquire()
    first.release()
    assert not path.exists()
    second = PidFile(path)
    second.acquire()
    second.release()


def test_pidfile_lock_is_exclusive_under_simultaneous_start(tmp_path):
    """Two daemon contenders cannot both pass the old read-then-write race."""
    path = tmp_path / "gks.pid"
    start = threading.Barrier(3)
    release = threading.Event()
    results = []
    errors = []

    def attempt():
        pf = PidFile(path)
        start.wait(timeout=5)
        try:
            pf.acquire()
        except AlreadyRunning:
            results.append("blocked")
        except BaseException as exc:
            errors.append(exc)
        else:
            results.append("acquired")
            release.wait(timeout=5)
            pf.release()

    a = threading.Thread(target=attempt)
    b = threading.Thread(target=attempt)
    a.start()
    b.start()
    try:
        start.wait(timeout=5)
        deadline = time.monotonic() + 5
        while len(results) < 2 and not errors and time.monotonic() < deadline:
            time.sleep(0.01)
        assert not errors
        assert sorted(results) == ["acquired", "blocked"]
        assert path.exists()
    finally:
        release.set()
        a.join(timeout=5)
        b.join(timeout=5)
    assert not a.is_alive() and not b.is_alive()
    assert not path.exists()
    assert path.with_name(path.name + ".lock").exists()


def test_pidfile_kernel_lock_recovers_from_crashed_writer(tmp_path):
    """OS lock is released on process death; stale PID is safely replaced."""
    path = tmp_path / "gks.pid"
    repo_root = Path(__file__).resolve().parents[2]
    code = (
        "import os, sys; "
        "from tools.github_kanban_sync.scheduler import PidFile; "
        "PidFile(sys.argv[1]).acquire(); os._exit(0)"
    )
    child = subprocess.run(
        [sys.executable, "-c", code, str(path)],
        cwd=repo_root, capture_output=True, text=True, timeout=10,
    )
    assert child.returncode == 0, child.stderr
    assert path.exists()
    pf = PidFile(path)
    try:
        pf.acquire()
        assert pf.read_pid() == os.getpid()
        assert pf.read_record()["nonce"] is not None
    finally:
        pf.release()
    assert not path.exists()


def test_stop_daemon_cooperates_without_signalling_any_pid(tmp_path, monkeypatch):
    """Even a live PID in a pidfile is not permission to send a UNIX signal."""
    path = tmp_path / "gks.pid"
    pf = PidFile(path)
    pf.acquire()
    signalled = []
    real_kill = os.kill

    def guarded_kill(pid, sig):
        signalled.append((pid, sig))
        assert sig == 0, "stop_daemon must NEVER signal arbitrary PIDs"
        return real_kill(pid, sig)

    monkeypatch.setattr("tools.github_kanban_sync.scheduler.os.kill", guarded_kill)
    result = {}

    def request():
        result.update(stop_daemon(path, timeout=4.0))

    caller = threading.Thread(target=request)
    caller.start()
    try:
        deadline = time.monotonic() + 3
        while not pf.stop_requested() and time.monotonic() < deadline:
            time.sleep(0.01)
        assert pf.stop_requested()
        assert pf.read_record()["nonce"] is not None
    finally:
        pf.release()
        caller.join(timeout=5)
    assert not caller.is_alive()
    assert result["stopped"] is True and result["pid"] == os.getpid()
    assert all(sig == 0 for _, sig in signalled)
    assert not path.exists()


def test_stale_stop_request_cannot_stop_restarted_daemon(tmp_path):
    path = tmp_path / "gks.pid"
    old = PidFile(path)
    old.acquire()
    record = old.read_record()
    old.release()
    fresh = PidFile(path)
    fresh.acquire()
    try:
        assert fresh.read_record()["nonce"] != record["nonce"]
        fresh.stop_path.write_text(json.dumps(record))
        assert fresh.stop_requested() is False
        assert fresh.stop_path.exists()
    finally:
        fresh.release()
    assert not path.exists()
    assert not fresh.stop_path.exists()


def test_legacy_pidfile_containing_a_live_pid_cannot_signal_it(tmp_path, monkeypatch):
    path = tmp_path / "old-gks.pid"
    path.write_text(str(os.getpid()))
    def no_kill(pid, sig):
        if sig:
            pytest.fail("unverified PID must never receive a signal")

    monkeypatch.setattr("tools.github_kanban_sync.scheduler.os.kill", no_kill)
    out = stop_daemon(path, timeout=0)
    assert out["stopped"] is False
    assert out["reason"] == "legacy_pidfile_unsafe"
    assert path.read_text() == str(os.getpid())


def test_cooperative_stop_interrupts_running_scheduler(tmp_path):
    path = tmp_path / "gks.pid"
    pf = PidFile(path)
    pf.acquire()
    settings = Settings(coord_db=tmp_path / "coord.db")
    store = Store(settings.coord_db)
    sched = Scheduler(
        settings, store=store, board=None, gh=None,
        config=SchedulerConfig(interval=30.0),
        stop_requested=pf.stop_requested, log=lambda _: None,
    )
    entered = threading.Event()
    errors = []

    def one_cycle():
        sched.iteration += 1
        entered.set()
        return {
            "iteration": sched.iteration, "correlation_id": "test",
            "new_events": 0, "published": 0,
        }

    sched.run_once = one_cycle
    def run():
        try:
            sched.run()
        except BaseException as exc:
            errors.append(exc)
        finally:
            pf.release()

    thread = threading.Thread(target=run)
    thread.start()
    try:
        assert entered.wait(timeout=5)
        stopped = stop_daemon(path, timeout=5.0)
        assert stopped["stopped"] is True
        thread.join(timeout=5)
        assert not errors
        assert not thread.is_alive()
        assert sched.stopped
    finally:
        sched.request_stop()
        thread.join(timeout=5)
        pf.release()
        store.close()


def test_stop_daemon_reports_no_and_stale_pidfile(tmp_path):
    path = tmp_path / "gks.pid"
    out = stop_daemon(path)
    assert out["stopped"] is False and out["reason"] == "no_pidfile"
    path.write_text("999999999")  # a pid that cannot exist
    out = stop_daemon(path)
    assert out["stopped"] is False and out["reason"] == "stale_pidfile"
    assert not path.exists()  # stale pidfile cleaned up


def test_status_exposes_scheduler_state(tmp_path):
    db = make_kanban_db(tmp_path)
    add_task(db, "t_dev")
    settings = _settings(tmp_path, db)
    store = Store(settings.coord_db)
    links.bind(store, REPO, 192, "me", "t_dev")
    kb = board(db)
    gh = client_with(_issue_handler([]))
    sched = Scheduler(settings, store=store, board=kb, gh=gh,
                      config=SchedulerConfig(interval=0.01), log=lambda _s: None)

    sched.run(max_iterations=1)

    status = observability.status(store)
    assert status["scheduler"]["iteration"] == 1
    assert status["scheduler"]["status"] == "stopped"
    assert status["health"]["scheduler_status"] == "stopped"
    store.close()
    kb.close()


def test_cli_daemon_stop_without_pidfile(tmp_path, capsys):
    rc = cli.main(["daemon", "--stop", "--pidfile", str(tmp_path / "nope.pid")])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["stopped"] is False and out["reason"] == "no_pidfile"


def test_cli_daemon_parser_flags():
    parser = cli.build_parser()
    args = parser.parse_args(["daemon", "--interval", "1", "--once", "--max-iterations", "2"])
    assert args.interval == 1 and args.once is True and args.max_iterations == 2
    assert args.pidfile  # a default pidfile is always resolved
