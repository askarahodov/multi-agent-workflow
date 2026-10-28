"""SQL-level limits for native discovery: ordered, validated, backwards-compatible."""
import pytest
from orchestration_server.queries import OrchestrationQueries


@pytest.mark.asyncio
async def test_query_limits_reject_boolean_float_zero_and_oversized_before_database():
    queries = OrchestrationQueries(None)
    for value in (True, False, 0, -1, 1001, 1.5, "2"):
        with pytest.raises(ValueError):
            await queries.list_runs(limit=value)
        with pytest.raises(ValueError):
            await queries.list_tasks("run-id", limit=value)


def test_worker_discovery_uses_engine_authorized_bounded_readiness():
    import inspect
    from orchestration_server.native_worker import NativeWorker
    source = inspect.getsource(NativeWorker.run_once)
    assert 'self.engine.ready_tasks(' in source
    assert 'limit=min(100, self.max_runs_scan * self.max_tasks_per_run)' in source
    assert 'runs[:self.max_runs_scan]' not in source
    assert 'tasks[:self.max_tasks_per_run]' not in source
