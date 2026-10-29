"""Task DAG validation, claimability and result passing (ADR-109)."""

from __future__ import annotations

import pytest

from agent_runtime.errors import ErrorKind, PlatformError
from agent_runtime.graph import MAX_DEPENDENCIES, MAW_UPSTREAM_KEY, TaskGraph, TaskStatus


def _three_stage():
    return TaskGraph.from_spec(
        [
            {"title": "Research"},
            {"title": "Architecture", "depends_on": [0]},
            {"title": "Implementation", "depends_on": [1]},
        ]
    )


def test_from_spec_builds_chain():
    graph = _three_stage()
    assert len(graph.nodes) == 3
    assert graph.ready_ids() == [graph.nodes[0].id]


def test_duplicate_dependencies_rejected():
    with pytest.raises(PlatformError) as exc:
        TaskGraph.from_spec([{"title": "a"}, {"title": "b", "depends_on": [0, 0]}])
    assert exc.value.kind is ErrorKind.VALIDATION_ERROR


def test_forward_dependency_rejected():
    with pytest.raises(PlatformError) as exc:
        TaskGraph.from_spec([{"title": "a", "depends_on": [1]}, {"title": "b"}])
    assert exc.value.kind is ErrorKind.VALIDATION_ERROR


def test_out_of_range_dependency_rejected():
    with pytest.raises(PlatformError):
        TaskGraph.from_spec([{"title": "a", "depends_on": [5]}])


def test_too_many_dependencies_rejected():
    tasks = [{"title": f"t{i}"} for i in range(MAX_DEPENDENCIES + 1)]
    tasks.append({"title": "root", "depends_on": list(range(MAX_DEPENDENCIES + 1))})
    with pytest.raises(PlatformError) as exc:
        TaskGraph.from_spec(tasks)
    assert "dependencies" in exc.value.message


def test_contract_required_when_flagged():
    with pytest.raises(PlatformError) as exc:
        TaskGraph.from_spec([{"title": "a"}], require_contract=True)
    assert exc.value.kind is ErrorKind.VALIDATION_ERROR


def test_reserved_upstream_key_rejected():
    with pytest.raises(PlatformError) as exc:
        TaskGraph.from_spec([{"title": "a", "input_data": {MAW_UPSTREAM_KEY: []}}])
    assert MAW_UPSTREAM_KEY in exc.value.message


def test_dependent_not_claimable_until_prerequisite_completes():
    graph = _three_stage()
    t0, t1, t2 = (n.id for n in graph.nodes)
    ok, reason = graph.claimable(t1)
    assert ok is False
    assert "prerequisites not completed" in reason

    with pytest.raises(PlatformError) as exc:
        graph.claim(t1)
    assert exc.value.kind is ErrorKind.CLAIM_DENIED

    graph.claim(t0)
    graph.complete(t0, summary="research done")
    assert graph.claimable(t1)[0] is True
    assert graph.claimable(t2)[0] is False


def test_ready_ids_reflects_completion_order():
    graph = _three_stage()
    t0, t1, t2 = (n.id for n in graph.nodes)
    graph.claim(t0)
    graph.complete(t0, summary="r")
    assert graph.ready_ids() == [t1]
    graph.claim(t1)
    graph.complete(t1, summary="a")
    assert graph.ready_ids() == [t2]


def test_completion_propagates_upstream_handoff():
    graph = _three_stage()
    t0, t1, t2 = (n.id for n in graph.nodes)
    graph.complete(t0, summary="upstream summary")
    dependent = graph.node(t1)
    assert dependent.upstream == [{"prev_task_id": t0, "summary": "upstream summary"}]
    assert graph.node(t2).upstream == []


def test_failed_dependent_detected_by_ready_set():
    graph = _three_stage()
    t0, t1, t2 = (n.id for n in graph.nodes)
    graph.claim(t0)
    graph.fail(t0, error={"error_code": "tool_timeout"})
    assert graph.ready_ids() == []  # dependents never become ready
    assert graph.node(t1).status is TaskStatus.PENDING
    assert graph.all_terminal() is False


def test_claim_never_bumps_attempts_on_refusal():
    # Refusal is a pure predicate; there is no attempt counter to corrupt.
    graph = _three_stage()
    t1 = graph.nodes[1].id
    for _ in range(3):
        assert graph.claimable(t1)[0] is False
    assert graph.node(t1).status is TaskStatus.PENDING
