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
