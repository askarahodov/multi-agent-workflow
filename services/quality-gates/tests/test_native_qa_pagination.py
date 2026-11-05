"""Adversarial paginated independent-QA discovery regressions for #11.

The transport is a real httpx.MockTransport, without provider, Git or paid calls.
No successful stage may be attested by these cursor fixtures.
"""
from __future__ import annotations

import json

import httpx
import pytest

from quality_gates.native_qa_controller import (
    NativeQaController, QaControllerConfig, QaControllerError,
)

RUN_A = "11111111-1111-1111-1111-111111111111"
RUN_B = "22222222-2222-2222-2222-222222222222"


def controller(handler):
    config = QaControllerConfig(
        orch_url="https://orchestration.example",
        orch_admin_key="controller-test-key",
        qg_url="https://qa.example",
        qg_admin_key="separate-qa-key",
        test_command=("python", "-m", "pytest", "-q"),
    )

    def qa_forbidden(_request):
        raise AssertionError("pagination failure must not reach independent QA")

    return NativeQaController(
        config,
        git_store=object(),
        orchestration_transport=httpx.MockTransport(handler),
        qa_transport=httpx.MockTransport(qa_forbidden),
    )


def page(items, cursor=None):
    # Keep intentionally malformed Unicode as a JSON escape, so the parser
    # receives the hostile value and the QA controller itself must reject it.
    body = json.dumps({"items": items, "next_cursor": cursor}, ensure_ascii=True)
    return httpx.Response(200, content=body.encode("ascii"),
                          headers={"content-type": "application/json"})


@pytest.mark.asyncio
async def test_run_cursor_cycle_a_b_a_fails_before_any_more_task_requests():
    task_queries = []

    def handler(request):
        if request.url.path == "/api/v1/workflows/runs":
            cursor = request.url.params.get("after")
            following = {None: "run-A", "run-A": "run-B", "run-B": "run-A"}
            assert cursor in following
            return page([{"id": RUN_A, "status": "running"}], following[cursor])
        if request.url.path.endswith("/tasks"):
            task_queries.append(str(request.url))
            return page([])
        raise AssertionError("unexpected HTTP endpoint")

    async with controller(handler) as qa:
        assert await qa.run_once() is None
        assert await qa.run_once() is None
        with pytest.raises(QaControllerError, match="QA discovery cursor invalid"):
            await qa.run_once()
        assert len(task_queries) == 2
        assert qa._run_cursor == "run-B"
        assert qa._run_cursor_seen == {"run-A", "run-B"}


@pytest.mark.asyncio
async def test_task_cursor_cycle_a_b_a_fails_without_attesting_a_task():
    queried = []
    def handler(request):
        if request.url.path == "/api/v1/workflows/runs":
            return page([{"id": RUN_A, "status": "running"}])
        if request.url.path.endswith("/tasks"):
            after = request.url.params.get("after")
            queried.append(after)
            return page(
                [{"status": "pending", "workflow_run_id": RUN_A}],
                {None: "page-A", "page-A": "page-B", "page-B": "page-A"}[after],
            )
        raise AssertionError("unexpected HTTP endpoint")

    async with controller(handler) as qa:
        for _ in range(2):
            assert await qa.run_once() is None
        with pytest.raises(QaControllerError, match="QA discovery cursor invalid"):
            await qa.run_once()
        assert queried == [None, "page-A", "page-B"]
        assert qa._task_cursors[RUN_A] == "page-B"
        assert qa._task_cursor_seen[RUN_A] == {"page-A", "page-B"}


@pytest.mark.parametrize(
    "bad_items,bad_cursor",
    [
        ([], "next"),                  # no progress despite continuation
        ([{"status": "running"}], ""), # empty cursor
        ([{"status": "running"}], 12), # non-string cursor
        ([None], "next"),              # malformed row
    ],
)
@pytest.mark.asyncio
async def test_invalid_run_page_rejected_before_task_lookup(bad_items, bad_cursor):
    queries = []
    def handler(request):
        queries.append(request.url.path)
        return page(bad_items, bad_cursor)

    async with controller(handler) as qa:
        with pytest.raises(QaControllerError):
            await qa.run_once()
        assert queries == ["/api/v1/workflows/runs"]
        assert qa._run_cursor is None
        assert qa._run_cursor_seen == set()


@pytest.mark.asyncio
async def test_cursor_history_fails_closed_at_bounded_limit_and_never_evicts():
    def handler(request):
        if request.url.path == "/api/v1/workflows/runs":
            cursor = request.url.params.get("after")
            return page(
                [{"id": RUN_A, "status": "running"}],
                {None: "A", "A": "B", "B": "C"}[cursor],
            )
        if request.url.path.endswith("/tasks"):
            return page([])
        raise AssertionError("unexpected HTTP endpoint")

    async with controller(handler) as qa:
        qa._MAX_CURSOR_HISTORY = 2
        assert await qa.run_once() is None
        assert await qa.run_once() is None
        with pytest.raises(QaControllerError, match="QA discovery cursor invalid"):
            await qa.run_once()
        assert qa._run_cursor == "B"
        assert qa._run_cursor_seen == {"A", "B"}


@pytest.mark.asyncio
async def test_terminal_run_and_task_pages_reclaim_history_for_new_scan():
    run_queries = []
    task_queries = []

    def handler(request):
        if request.url.path == "/api/v1/workflows/runs":
            after = request.url.params.get("after")
            run_queries.append(after)
            return page(
                [{"id": RUN_A, "status": "running"}],
                "R" if after is None else None,
            )
        if request.url.path.endswith("/tasks"):
            after = request.url.params.get("after")
            task_queries.append(after)
            return page(
                [{"status": "pending", "workflow_run_id": RUN_A}],
                "T" if after is None else None,
            )
        raise AssertionError("unexpected HTTP endpoint")

    async with controller(handler) as qa:
        for _ in range(4):
            assert await qa.run_once() is None
        assert run_queries == [None, "R", None, "R"]
        assert task_queries == [None, "T", None, "T"]
        assert qa._run_cursor is None
        assert qa._run_cursor_seen == set()
        assert qa._task_cursors == {}
        assert qa._task_cursor_seen == {}
        assert qa._cursor_bytes_retained == 0


@pytest.mark.asyncio
async def test_task_cursor_windows_cannot_silently_evict_active_run():
    requests = []
    def handler(request):
        requests.append(request.url.path)
        if request.url.path == "/api/v1/workflows/runs":
            return page([{"id": RUN_B, "status": "running"}])
        if request.url.path.endswith("/tasks"):
            raise AssertionError("a new run must not consume tasks after capacity exhaustion")
        raise AssertionError("unexpected endpoint")

    async with controller(handler) as qa:
        qa._MAX_TASK_CURSOR_WINDOWS = 1
        qa._task_cursors[RUN_A] = "active-cursor"
        qa._task_cursor_seen[RUN_A] = {"active-cursor"}
        qa._cursor_bytes_retained = len("active-cursor")
        with pytest.raises(QaControllerError, match="QA active task cursor capacity exhausted"):
            await qa.run_once()
        assert requests == ["/api/v1/workflows/runs"]
        assert qa._task_cursors == {RUN_A: "active-cursor"}
        assert qa._task_cursor_seen == {RUN_A: {"active-cursor"}}


@pytest.mark.asyncio
async def test_terminal_task_page_releases_window_capacity_for_another_run():
    seen_runs = [RUN_A, RUN_B]

    def handler(request):
        if request.url.path == "/api/v1/workflows/runs":
            run_id = seen_runs.pop(0)
            return page([{"id": run_id, "status": "running"}])
        if request.url.path.endswith(f"/{RUN_A}/tasks"):
            assert request.url.params.get("after") == "old-task-cursor"
            return page([{"status": "pending"}])
        if request.url.path.endswith(f"/{RUN_B}/tasks"):
            return page([{"status": "pending"}], "new-task-cursor")
        raise AssertionError("unexpected endpoint")

    async with controller(handler) as qa:
        qa._MAX_TASK_CURSOR_WINDOWS = 1
        qa._task_cursors[RUN_A] = "old-task-cursor"
        qa._task_cursor_seen[RUN_A] = {"old-task-cursor"}
        qa._cursor_bytes_retained = len("old-task-cursor")
        assert await qa.run_once() is None
        assert qa._task_cursor_seen == {}
        assert await qa.run_once() is None
        assert qa._task_cursors == {RUN_B: "new-task-cursor"}
        assert qa._task_cursor_seen == {RUN_B: {"new-task-cursor"}}
        assert qa._cursor_bytes_retained == len("new-task-cursor")


@pytest.mark.parametrize("oversized", ["X" * 513, "é" * 257])
@pytest.mark.asyncio
async def test_oversized_cursor_bytes_fail_before_any_qa_or_task_request(oversized):
    paths = []
    def handler(request):
        paths.append(request.url.path)
        return page([{"id": RUN_A, "status": "running"}], oversized)

    async with controller(handler) as qa:
        with pytest.raises(QaControllerError, match="QA discovery cursor budget exhausted"):
            await qa.run_once()
        assert paths == ["/api/v1/workflows/runs"]
        assert qa._run_cursor is None
        assert qa._run_cursor_seen == set()
        assert qa._cursor_bytes_retained == 0


@pytest.mark.asyncio
async def test_shared_byte_budget_rejects_task_page_without_evicting_run_history():
    queries = []
    def handler(request):
        queries.append(request.url.path)
        if request.url.path == "/api/v1/workflows/runs":
            return page(
                [{"id": RUN_A, "status": "running"}],
                "ABC" if request.url.params.get("after") is None else None,
            )
        if request.url.path.endswith("/tasks"):
            return page([{"status": "pending"}], "DEFG")
        raise AssertionError("unexpected endpoint")

    async with controller(handler) as qa:
        qa._MAX_RETAINED_CURSOR_BYTES = 6
        with pytest.raises(QaControllerError, match="QA discovery cursor budget exhausted"):
            await qa.run_once()
        assert queries == [
            "/api/v1/workflows/runs",
            f"/api/v1/workflows/runs/{RUN_A}/tasks",
        ]
        assert qa._run_cursor == "ABC"
        assert qa._run_cursor_seen == {"ABC"}
        assert qa._cursor_bytes_retained == 3
        assert qa._task_cursors == {}
        assert qa._task_cursor_seen == {}

        # Only a verified terminal run page can reclaim those 3 bytes.
        assert await qa.run_once() is None
        assert qa._run_cursor is None
        assert qa._run_cursor_seen == set()
        assert qa._task_cursors == {RUN_A: "DEFG"}
        assert qa._task_cursor_seen == {RUN_A: {"DEFG"}}
        assert qa._cursor_bytes_retained == 4


@pytest.mark.asyncio
async def test_invalid_utf8_surrogate_cursor_fails_closed_without_retention():
    def handler(_request):
        return page([{"id": RUN_A, "status": "running"}], "\ud800")

    async with controller(handler) as qa:
        with pytest.raises(QaControllerError, match="QA discovery cursor invalid"):
            await qa.run_once()
        assert qa._cursor_bytes_retained == 0
        assert qa._run_cursor_seen == set()
