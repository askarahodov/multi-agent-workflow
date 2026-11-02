/**
 * Task board (Kanban) layout (ADR-110 §3.6).
 *
 * Design-system implementation of the "Kanban-доска" section. Tasks are grouped
 * by lifecycle status into responsive columns; each column has a real empty
 * state and the board as a whole handles loading/error consistently. Clicking a
 * task opens its card.
 */

import { useEffect } from 'react';

import type { RunResponse, TaskResponse } from '../api/types';
import { useMvpStore } from '../mvp/mvpStore';
import { useAsync } from '../mvp/useAsync';
import { Card, Select, StatusBadge } from '../components';
import { AsyncBoundary, PageHeader } from '../patterns';

const COLUMNS = ['pending', 'in_progress', 'blocked', 'completed', 'failed'] as const;

const COLUMN_LABEL: Record<string, string> = {
  pending: 'Ожидает',
  in_progress: 'В работе',
  blocked: 'Заблокировано',
  completed: 'Завершено',
  failed: 'Ошибка',
};

export default function TaskBoard() {
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

  useEffect(() => {
    tasks.reload();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [runId, runs.data]);

  function grouped(): Record<string, TaskResponse[]> {
    const buckets: Record<string, TaskResponse[]> = {};
    for (const column of COLUMNS) buckets[column] = [];
    for (const task of tasks.data ?? []) {
      const key = (COLUMNS as readonly string[]).includes(task.status) ? task.status : 'in_progress';
      buckets[key].push(task);
    }
    return buckets;
  }

  function openTask(task: TaskResponse) {
    selectTask(task.id);
    setSection('task');
  }

  const buckets = grouped();

  return (
    <div>
      <PageHeader
        title="Kanban-доска"
        subtitle="Состояние задач на каждом этапе жизненного цикла."
        breadcrumbs={[{ label: 'Платформа' }, { label: 'Kanban-доска' }]}
      />

      <div
        style={{
          display: 'flex',
          gap: 'var(--space-3)',
          marginBlockEnd: 'var(--space-4)',
          flexWrap: 'wrap',
          alignItems: 'center',
        }}
      >
        <label htmlFor="board-run-filter" style={{ fontSize: 'var(--font-size-sm)', color: 'var(--color-text-muted)' }}>
          Фильтр по запуску
        </label>
        <Select
          id="board-run-filter"
          data-testid="board-run-filter"
          value={runId ?? ''}
          onChange={(e) => {
            selectRun(e.target.value || null);
            tasks.reload();
          }}
          style={{ maxWidth: 320, marginBlockEnd: 0 }}
        >
          <option value="">Все запуски</option>
          {runs.data?.map((run) => (
            <option key={run.id} value={run.id}>
              {run.name}
            </option>
          ))}
        </Select>
        <StatusBadge
          status={runId ? 'selected' : 'all'}
          tone={runId ? 'accent' : 'muted'}
          label={runId ? 'Один запуск' : 'Все запуски'}
        />
      </div>

      <AsyncBoundary
        loading={tasks.loading}
        error={tasks.error}
        isEmpty={!tasks.loading && !tasks.error && (tasks.data?.length ?? 0) === 0}
        onRetry={tasks.reload}
        emptyTitle="Задач пока нет"
        emptyBody="Запустите конвейер, чтобы задачи появились на доске."
        skeletonLines={4}
      >
        <div
          style={{
            display: 'grid',
            gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))',
            gap: 'var(--space-3)',
            alignItems: 'start',
          }}
        >
          {COLUMNS.map((column) => {
            const items = buckets[column];
            return (
              <Card
                key={column}
                title={
                  <span>
                    {COLUMN_LABEL[column]}{' '}
                    <span style={{ color: 'var(--color-text-subtle)', fontWeight: 500 }}>({items.length})</span>
                  </span>
                }
              >
                {items.length === 0 ? (
                  <p style={{ color: 'var(--color-text-subtle)', fontSize: 'var(--font-size-sm)', margin: 0 }}>
                    Пусто
                  </p>
                ) : (
                  <ul style={{ listStyle: 'none', margin: 0, padding: 0, display: 'grid', gap: 'var(--space-2)' }}>
                    {items.map((task) => (
                      <li key={task.id}>
                        <button
                          type="button"
                          data-testid={`board-task-${column}-${task.id}`}
                          onClick={() => openTask(task)}
                          style={{
                            width: '100%',
                            textAlign: 'start',
                            padding: 'var(--space-2) var(--space-3)',
                            borderRadius: 'var(--radius-md)',
                            border: '1px solid var(--color-border)',
                            background: 'var(--color-surface)',
                            cursor: 'pointer',
                            fontSize: 'var(--font-size-sm)',
                          }}
                        >
                          <strong>{task.title}</strong>
                          <span
                            style={{
                              display: 'block',
                              marginBlockStart: '4px',
                              color: 'var(--color-text-subtle)',
                              fontSize: 'var(--font-size-xs)',
                              overflow: 'hidden',
                              textOverflow: 'ellipsis',
                              whiteSpace: 'nowrap',
                            }}
                          >
                            {task.id}
                          </span>
                        </button>
                      </li>
                    ))}
                  </ul>
                )}
              </Card>
            );
          })}
        </div>
      </AsyncBoundary>
    </div>
  );
}
