/**
 * MVP v1 — Kanban board section (канбан-доска).
 *
 * Groups the platform's tasks by their lifecycle status into the standard
 * kanban columns and lists the conveyor runs alongside. Clicking a task opens
 * its card (task section). Data comes from the existing run/task endpoints
 * (`GET /workflows/runs`, `GET /workflows/runs/{id}/tasks`).
 */

import { useEffect } from 'react';

import type { RunResponse, TaskResponse } from '../../api/types';
import { useMvpStore } from '../mvpStore';
import { useAsync } from '../useAsync';
import { Card, PageHeader, StatusBadge } from '../ui';

const COLUMNS = ['pending', 'in_progress', 'blocked', 'completed', 'failed'];

export default function BoardSection() {
  const api = useMvpStore((s) => s.api);
  const runId = useMvpStore((s) => s.runId);
  const selectRun = useMvpStore((s) => s.selectRun);
  const selectTask = useMvpStore((s) => s.selectTask);
  const setSection = useMvpStore((s) => s.setSection);

  const runs = useAsync<RunResponse[]>(async () => (await api.listRuns({})).items);
  const tasks = useAsync<TaskResponse[]>(async () => {
    const state = useMvpStore.getState();
    let ids: string[];
    if (state.runId) {
      ids = [state.runId];
    } else {
      const allRuns = await api.listRuns({});
      ids = allRuns.items.map((run) => run.id);
    }
    const pages = await Promise.all(ids.map((id) => api.listRunTasks(id)));
    return pages.flatMap((page) => page.items);
  });

  // (Re)load tasks whenever the run filter changes or the run list settles so a
  // brand-new run's tasks appear on the board without a manual refresh.
  useEffect(() => {
    tasks.reload();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [runId, runs.data]);

  function grouped(): Record<string, TaskResponse[]> {
    const buckets: Record<string, TaskResponse[]> = {};
    for (const column of COLUMNS) buckets[column] = [];
    for (const task of tasks.data ?? []) {
      const key = COLUMNS.includes(task.status) ? task.status : 'in_progress';
      buckets[key].push(task);
    }
    return buckets;
  }

  function openTask(task: TaskResponse) {
    selectTask(task.id);
    setSection('task');
  }

  return (
    <div>
      <PageHeader
        title="Kanban-доска"
        subtitle="Состояние задач на каждом этапе жизненного цикла (D-luch ADR-101: состояния отображаются согласованно)."
      />

      <div
        style={{
          display: 'flex',
          gap: 16,
          marginBottom: 16,
          flexWrap: 'wrap',
          alignItems: 'center',
        }}
      >
        <span style={{ fontSize: 12, color: '#5b6472' }}>Фильтр по запуску:</span>
        <select
          data-testid="board-run-filter"
          value={runId ?? ''}
          onChange={(e) => {
            selectRun(e.target.value || null);
            tasks.reload();
          }}
          style={{
            padding: '6px 10px',
            borderRadius: 6,
            border: '1px solid #c8ced6',
            maxWidth: 320,
          }}
        >
          <option value="">Все запуски</option>
          {runs.data?.map((run) => (
            <option key={run.id} value={run.id}>
              {run.name}
            </option>
          ))}
        </select>
        <StatusBadge
          status={runId ? 'selected' : 'all'}
          tone={runId ? 'accent' : 'muted'}
          label={runId ? 'Один запуск' : 'Все запуски'}
        />
      </div>

      {tasks.loading ? <p style={{ color: '#5b6472' }}>Загрузка…</p> : null}
      {tasks.error ? <p style={{ color: '#a3271c' }}>Ошибка: {tasks.error.message}</p> : null}
      {!tasks.loading && !tasks.error ? (
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(5, 1fr)', gap: 12 }}>
          {COLUMNS.map((column) => {
            const items = grouped()[column];
            return (
              <Card
                key={column}
                title={
                  <span>
                    {column}{' '}
                    <span style={{ color: '#9aa2af', fontWeight: 500 }}>({items.length})</span>
                  </span>
                }
              >
                {items.length === 0 ? (
                  <p style={{ color: '#c0c5cd', fontSize: 12, margin: 0 }}>Пусто</p>
                ) : (
                  <ul style={{ listStyle: 'none', margin: 0, padding: 0 }}>
                    {items.map((task) => (
                      <li key={task.id} style={{ marginBottom: 8 }}>
                        <button
                          data-testid={`board-task-${column}-${task.id}`}
                          onClick={() => openTask(task)}
                          style={{
                            width: '100%',
                            textAlign: 'left',
                            padding: '8px 10px',
                            borderRadius: 6,
                            border: '1px solid #e2e6ea',
                            background: '#fff',
                            cursor: 'pointer',
                            fontSize: 12,
                          }}
                        >
                          <strong>{task.title}</strong>
                          <p
                            style={{
                              margin: '4px 0 0',
                              color: '#9aa2af',
                              fontSize: 11,
                              overflow: 'hidden',
                              textOverflow: 'ellipsis',
                              whiteSpace: 'nowrap',
                            }}
                          >
                            {task.id}
                          </p>
                        </button>
                      </li>
                    ))}
                  </ul>
                )}
              </Card>
            );
          })}
        </div>
      ) : null}
    </div>
  );
}
