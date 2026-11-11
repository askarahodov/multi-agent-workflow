"""Run-scoped quarantine remains discoverable beyond a saturated global queue."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import httpx
import pytest

from conftest import seed_workflow
from orchestration_server.api import build_app
from orchestration_server.config import Settings
from orchestration_server.models import SagaEvent, Task


@pytest.mark.asyncio
async def test_run_scope_is_applied_before_limit_and_saga_duplicates(harness):
    project, _, _, old_run, _ = await seed_workflow(harness.orch, harness.queries)
    new_run = await harness.orch.launch_run(
        project.id, "target-run", [{"title": "target-task"}],
    )
    target = (await harness.queries.list_tasks(new_run.id))[0]
    older = datetime.now(timezone.utc) - timedelta(days=2)
    async with harness.sf() as session:
        old_tasks = [
            Task(workflow_run_id=old_run.id, title=f"stale-{n}",
                 status="blocked", created_at=older)
            for n in range(105)
        ]
        session.add_all(old_tasks)
        await session.flush()
        session.add_all([
            SagaEvent(run_id=old_run.id, aggregate_type="task",
                      aggregate_id=task.id, event_type="task.recovery_quarantined")
            for task in old_tasks
        ])
        session.add(SagaEvent(
            run_id=old_run.id, aggregate_type="task",
            aggregate_id=old_tasks[0].id, event_type="task.recovery_quarantined",
        ))
        target_row = await session.get(Task, target.id)
        target_row.status = "blocked"
        session.add(SagaEvent(
            run_id=new_run.id, aggregate_type="task",
            aggregate_id=target.id, event_type="task.recovery_quarantined",
        ))
        await session.commit()

    assert len(await harness.queries.list_recovery_quarantine(limit=100)) == 100
    scoped = await harness.queries.list_recovery_quarantine(
        limit=100, run_id=new_run.id,
    )
    assert [t.id for t in scoped] == [target.id]
    assert len(await harness.queries.list_recovery_quarantine(
        limit=200, run_id=old_run.id,
    )) == 105

    app = build_app(Settings(database_url=harness.url, recover_on_startup=False))
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://testserver",
        ) as client:
            response = await client.get(
                "/api/v1/admin/recovery-quarantine",
                params={"run_id": new_run.id, "limit": 100},
            )
            assert response.status_code == 200, response.text
            assert [row["id"] for row in response.json()] == [target.id]
            assert (await client.get(
                "/api/v1/admin/recovery-quarantine",
                params={"run_id": "absent"},
            )).json() == []
            assert (await client.get(
                "/api/v1/admin/recovery-quarantine",
                params={"run_id": new_run.id, "limit": 201},
            )).status_code == 422
