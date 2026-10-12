"""Tests for the unified CI pipeline (task items (a)+(b))."""

from __future__ import annotations

import sys

import pytest

from tools.ci.pipeline import CIPipeline, QualityGateApiClient
from tools.ci import runner as _runner
from tools.ci.sdlc import GateVerdict
from tools.ci.runner import SuiteResult


def _fake_suite_results():
    return [
        SuiteResult(module="orchestration-server", passed=10, exit_code=0),
        SuiteResult(module="agent-management", passed=8, exit_code=0),
        SuiteResult(module="quality-gates", passed=6, exit_code=0),
        SuiteResult(module="runtime-hardening", passed=9, exit_code=0),
        SuiteResult(module="tools", passed=5, exit_code=0),
    ]


def test_discover_test_dir(tmp_path):
    (tmp_path / "agent-management" / "tests").mkdir(parents=True)
    assert _runner.discover_test_dir(tmp_path, "agent-management") is not None
    assert _runner.discover_test_dir(tmp_path, "nope") is None


def test_suite_result_defaults():
    r = SuiteResult(module="x")
    assert r.ok is False
    r2 = SuiteResult(module="x", passed=1, exit_code=0)
    assert r2.ok is True


def test_report_parsing():
    text = "123 passed, 2 failed in 9.10s"
    assert _runner._extract_int(text, "passed") == 123
    assert _runner._extract_int(text, "failed") == 2


@pytest.mark.asyncio
async def test_pipeline_runs_and_completes(monkeypatch):
    monkeypatch.setattr(_runner, "run_all_backend_suites", lambda root: _fake_suite_results())
    pipe = CIPipeline(".")
    report = await pipe.run()
    assert report.sdlc is not None
    assert report.sdlc["complete"] is True
    assert len(report.suite_results) == 5
    assert report.overall_ok is True


@pytest.mark.asyncio
async def test_pipeline_with_real_quality_gate_client_is_flagged(monkeypatch):
    monkeypatch.setattr(_runner, "run_all_backend_suites", lambda root: _fake_suite_results())

    class FakeClient:
        def __init__(self):
            self.calls = []

        async def run_gate(self, gate, *, task_id, workspace=None, context=None):
            self.calls.append(gate)
            return GateVerdict(gate=gate, passed=True, findings=[])

    fake = FakeClient()
    # The pipeline accepts any object with .run_gate via build_sdlc_gate_runner.
    from tools.ci.pipeline import build_sdlc_gate_runner

    runner_fn = build_sdlc_gate_runner(fake, task_id="t1")
    verds = await runner_fn(type("P", (), {"name": "tester", "required_gates": ("tester",)})(), {}, None)
    assert verds[0].passed is True
    assert fake.calls == ["tester"]


@pytest.mark.asyncio
async def test_unconfigured_gates_do_not_silently_pass(monkeypatch):
    monkeypatch.setattr(_runner, "run_all_backend_suites", lambda root: _fake_suite_results())
    from tools.ci.pipeline import build_sdlc_gate_runner

    runner_fn = build_sdlc_gate_runner(None, task_id="t1")
    phase = type("P", (), {"name": "tester", "required_gates": ("tester",)})()
    verds = await runner_fn(phase, {}, None)
    assert verds[0].passed is False
    assert "not configured" in verds[0].findings[0]


def test_quality_gate_api_client_raises_on_http_error():
    client = QualityGateApiClient("http://127.0.0.1:1")
    # No live server — assert the error path raises a transport Error.
    import asyncio

    async def go():
        with pytest.raises(QualityGateApiClient.Error):
            await client.run_gate("tester", task_id="t")

    asyncio.run(go())