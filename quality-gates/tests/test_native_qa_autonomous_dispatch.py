"""Finite operator-enabled independent QA dispatch is fail closed."""
from __future__ import annotations

import pytest

from quality_gates import native_qa_controller as module


@pytest.mark.parametrize("config", [
    {},
    {"MAW_QA_AUTONOMOUS_ENABLED": "0"},
    {"MAW_QA_AUTONOMOUS_ENABLED": "yes"},
])
def test_dispatch_rejects_missing_operator_opt_in(config):
    with pytest.raises(ValueError, match="opt-in"):
        module.autonomous_qa_limits(config, ("python", "-B", "-m", "pytest", "-q"))


def test_dispatch_rejects_default_failed_test_before_network():
    with pytest.raises(ValueError, match="real operator test"):
        module.autonomous_qa_limits(
            {"MAW_QA_AUTONOMOUS_ENABLED": "1"},
            ("python", "-B", "-c", "raise SystemExit(1)"),
        )


@pytest.mark.parametrize("name,value", [
    ("MAW_QA_AUTONOMOUS_MAX_POLLS", "0"),
    ("MAW_QA_AUTONOMOUS_MAX_POLLS", "1001"),
    ("MAW_QA_AUTONOMOUS_MAX_POLLS", "bad"),
    ("MAW_QA_AUTONOMOUS_MAX_VERIFICATIONS", "0"),
    ("MAW_QA_AUTONOMOUS_MAX_VERIFICATIONS", "101"),
    ("MAW_QA_AUTONOMOUS_MAX_VERIFICATIONS", "1.5"),
])
def test_dispatch_rejects_invalid_budget(name, value):
    with pytest.raises(ValueError, match="budget"):
        module.autonomous_qa_limits(
            {"MAW_QA_AUTONOMOUS_ENABLED": "1", name: value},
            ("python", "-B", "-m", "pytest", "-q"),
        )


def test_dispatch_default_budget_is_finite():
    assert module.autonomous_qa_limits(
        {"MAW_QA_AUTONOMOUS_ENABLED": "1"},
        ("python", "-B", "-m", "pytest", "-q"),
    ) == (100, 7)


@pytest.mark.asyncio
async def test_dispatch_shares_single_qa_controller_until_completion_budget(monkeypatch):
    calls = []

    class FakeQA:
        def __init__(self, config, git_store):
            calls.append("constructed")
        async def __aenter__(self):
            return self
        async def __aexit__(self, *_):
            calls.append("closed")
        async def run_once(self):
            calls.append("polled")
            return "verified-task" if calls.count("polled") % 2 == 0 else None

    class FakeConfig:
        test_command = ("python", "-B", "-m", "pytest", "-q")

    monkeypatch.setattr(module, "NativeQaController", FakeQA)
    monkeypatch.setattr(module, "controller_from_env", lambda: (FakeConfig(), object(), 1, 0.01))
    monkeypatch.setattr(module, "autonomous_qa_limits", lambda env, test: (20, 2))
    assert await module.run_autonomous_qa() == 0
    assert calls == ["constructed", "polled", "polled", "polled", "polled", "closed"]


@pytest.mark.asyncio
async def test_dispatch_does_not_retry_after_failed_gate(monkeypatch):
    calls = []
    class FailingQA:
        def __init__(self, config, git_store):
            pass
        async def __aenter__(self):
            return self
        async def __aexit__(self, *_):
            calls.append("closed")
        async def run_once(self):
            calls.append("polled")
            raise module.QaControllerError("Gate failed")
    class FakeConfig:
        test_command = ("python", "-B", "-m", "pytest", "-q")
    monkeypatch.setattr(module, "NativeQaController", FailingQA)
    monkeypatch.setattr(module, "controller_from_env", lambda: (FakeConfig(), object(), 1, 0.01))
    monkeypatch.setattr(module, "autonomous_qa_limits", lambda env, test: (20, 2))
    with pytest.raises(module.QaControllerError):
        await module.run_autonomous_qa()
    assert calls == ["polled", "closed"]


@pytest.mark.asyncio
async def test_qa_bounded_page_scans_late_runs_and_tasks():
    from quality_gates.native_qa_controller import NativeQaController
    from unittest.mock import AsyncMock
    qa = object.__new__(NativeQaController)
    qa.config = type("Config", (), {"max_runs": 1, "max_tasks": 1})()
    qa._run_cursor = None
    qa._task_cursors = {}
    qa.orch = object()
    observed = []
    async def request(client, method, path, *, payload=None, params=None):
        observed.append((path, params.get("after")))
        if path == "/workflows/runs":
            if "after" not in params:
                return {"items": [{"id": "early"}], "next_cursor": "run-next"}
            return {"items": [{"id": "late"}], "next_cursor": None}
        if path.endswith("/tasks"):
            if "after" not in params:
                return {"items": [{"id": "first"}], "next_cursor": "task-next"}
            return {"items": [{"id": "second"}], "next_cursor": None}
        raise AssertionError("unexpected request")
    qa.request = request
    runs, cursor = await qa._scoped_page(
        "/workflows/runs", limit=1, previous=None,
    )
    assert runs[0]["id"] == "early" and cursor == "run-next"
    later, cursor = await qa._scoped_page(
        "/workflows/runs", limit=1, previous=cursor,
    )
    assert later[0]["id"] == "late" and cursor is None
    tasks, next_task = await qa._scoped_page(
        "/workflows/runs/late/tasks", limit=1, previous=None,
    )
    assert tasks[0]["id"] == "first"
    tasks, last_task = await qa._scoped_page(
        "/workflows/runs/late/tasks", limit=1, previous=next_task,
    )
    assert tasks[0]["id"] == "second" and last_task is None
    assert observed == [
        ("/workflows/runs", None), ("/workflows/runs", "run-next"),
        ("/workflows/runs/late/tasks", None),
        ("/workflows/runs/late/tasks", "task-next"),
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize("bad", [
    {"items": [], "next_cursor": 12},
    {"items": [], "next_cursor": "same"},
    {"items": [], "next_cursor": ""},
    {"items": [{}, {}], "next_cursor": None},
    {"items": ["bad"], "next_cursor": None},
    {"items": "invalid", "next_cursor": None},
])
async def test_qa_rejects_untrusted_discovery_page(bad):
    from quality_gates.native_qa_controller import NativeQaController, QaControllerError
    qa = object.__new__(NativeQaController)
    qa.orch = object()
    async def request(*args, **kwargs):
        return bad
    qa.request = request
    with pytest.raises(QaControllerError):
        await qa._scoped_page("/workflows/runs", limit=1, previous="same")
