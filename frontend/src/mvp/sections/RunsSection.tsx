/**
 * MVP v1 — Runs & results section (запуски и результаты).
 *
 * Lists workflow runs, lets the user create a new run with one or more tasks
 * and launch the conveyor (`POST /workflows/runs`), then inspect a run's task
 * breakdown. Selecting a run or a task routes the shared selection so the
 * Task-card and Live-agent-log sections open the right entity.
 */

import { type FormEvent, useEffect, useState } from 'react';

import type { RunResponse, TaskResponse } from '../../api/types';
import { useMvpStore } from '../mvpStore';
import { useAsync } from '../useAsync';
import { Card, formatDate, PageHeader, StatusBadge } from '../ui';

interface TaskRow {
  title: string;
  description: string;
}

export default function RunsSection() {
  const api = useMvpStore((s) => s.api);
  const projectId = useMvpStore((s) => s.projectId);
  const runId = useMvpStore((s) => s.runId);
  const selectRun = useMvpStore((s) => s.selectRun);
  const selectTask = useMvpStore((s) => s.selectTask);
  const setSection = useMvpStore((s) => s.setSection);

  const runs = useAsync<RunResponse[]>(async () => {
    const page = await api.listRuns({ projectId: projectId ?? undefined });
    return page.items;
  });

  const selectedRun = useAsync<RunResponse | null>(() =>
    useMvpStore.getState().runId
      ? api.getRun(useMvpStore.getState().runId!)
      : Promise.resolve(null),
  );
  const selectedTasks = useAsync<TaskResponse[]>(() =>
    useMvpStore.getState().runId
      ? api.listRunTasks(useMvpStore.getState().runId!).then((page) => page.items)
      : Promise.resolve([]),
  );

  // Refetch the runs list and selected-run detail when selection changes.
  useEffect(() => {
    runs.reload();
    selectedRun.reload();
    selectedTasks.reload();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projectId, runId]);

  const [name, setName] = useState('');
  const [rows, setRows] = useState<TaskRow[]>([{ title: '', description: '' }]);
  const [sequential, setSequential] = useState(false);
  const [launching, setLaunching] = useState(false);
  const [launchError, setLaunchError] = useState<string | null>(null);

  function addTaskRow() {
    setRows((r) => [...r, { title: '', description: '' }]);
  }

  function updateRow(index: number, patch: Partial<TaskRow>) {
    setRows((r) => r.map((row, i) => (i === index ? { ...row, ...patch } : row)));
  }

  async function onCreateRun(event: FormEvent) {
    event.preventDefault();
    const tasks = rows
      .filter((row) => row.title.trim())
      .map((row, index) => ({
        title: row.title.trim(),
        description: row.description.trim() || undefined,
        depends_on: sequential && index > 0 ? [index - 1] : [],
      }));
    if (!name.trim() || tasks.length === 0) return;
    if (!projectId) {
      setLaunchError('Сначала выберите проект в разделе «Проект».');
      return;
    }
    setLaunching(true);
    setLaunchError(null);
    try {
      const created = await api.launchRun({ project_id: projectId, name: name.trim(), tasks });
      selectRun(created.id);
      setName('');
      setRows([{ title: '', description: '' }]);
      runs.reload();
      selectedRun.reload();
      selectedTasks.reload();
    } catch (error) {
      setLaunchError(error instanceof Error ? error.message : String(error));
    } finally {
      setLaunching(false);
    }
  }

  function openTask(task: TaskResponse) {
    selectTask(task.id);
    setSection('task');
  }

  return (
    <div>
      <PageHeader
        title="Запуски и результаты"
        subtitle="Создайте задачу и запустите конвейер против реального backend (или mock в dev)."
      />

      <div
        style={{ display: 'grid', gridTemplateColumns: '3fr 2fr', gap: 16, alignItems: 'start' }}
      >
        {/* Left: runs list */}
        <div>
          <Card title={`Запуски${projectId ? ' (проект)' : ''}`}>
            {runs.loading ? <p style={{ color: '#5b6472' }}>Загрузка…</p> : null}
            {runs.error ? <p style={{ color: '#a3271c' }}>Ошибка: {runs.error.message}</p> : null}
            {!runs.loading && !runs.error && runs.data!.length === 0 ? (
              <p style={{ color: '#5b6472' }}>Запусков пока нет. Создайте первый справа.</p>
            ) : null}
            <ul style={{ listStyle: 'none', margin: 0, padding: 0 }}>
              {runs.data?.map((run) => (
                <li
                  key={run.id}
                  style={{
                    padding: '10px 12px',
                    border: '1px solid #e2e6ea',
                    borderRadius: 8,
                    marginBottom: 8,
                    cursor: 'pointer',
                    background: run.id === runId ? '#f2f6fc' : '#fff',
                    outline: run.id === runId ? '1px solid #1c5fa8' : undefined,
                  }}
                  onClick={() => {
                    selectRun(run.id);
                    selectedRun.reload();
                    selectedTasks.reload();
                  }}
                >
                  <div
                    style={{
                      display: 'flex',
                      justifyContent: 'space-between',
                      alignItems: 'center',
                      gap: 8,
                    }}
                  >
                    <strong>{run.name}</strong>
                    <StatusBadge status={run.status} />
                  </div>
                  <p style={{ margin: '4px 0 0', color: '#9aa2af', fontSize: 12 }}>
                    {run.id} · старт {formatDate(run.started_at ?? run.created_at)}
                  </p>
                  {run.output_data ? (
                    <pre
                      style={{
                        margin: '8px 0 0',
                        fontSize: 11,
                        background: '#f7f8fa',
                        padding: 8,
                        borderRadius: 6,
                        maxHeight: 90,
                        overflow: 'auto',
                      }}
                    >
                      {JSON.stringify(run.output_data, null, 2)}
                    </pre>
                  ) : null}
                </li>
              ))}
            </ul>
          </Card>
        </div>

        {/* Right: create + selected run detail */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
          <Card title="Создать запуск (конвейер)">
            <form onSubmit={onCreateRun}>
              <label style={{ display: 'block', marginBottom: 8 }}>
                <span style={{ fontSize: 12, color: '#5b6472', display: 'block', marginBottom: 4 }}>
                  Название запуска *
                </span>
                <input
                  data-testid="run-name-input"
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  placeholder="Например: Обработка заявок Q3"
                  style={{
                    width: '100%',
                    boxSizing: 'border-box',
                    padding: '8px 10px',
                    borderRadius: 6,
                    border: '1px solid #c8ced6',
                  }}
                />
              </label>
              <span style={{ fontSize: 12, color: '#5b6472', display: 'block', marginBottom: 4 }}>
                Задачи (заголовок обязателен)
              </span>
              {rows.map((row, index) => (
                <div key={index} style={{ display: 'flex', gap: 8, marginBottom: 8 }}>
                  <input
                    data-testid={`task-title-input-${index}`}
                    value={row.title}
                    onChange={(e) => updateRow(index, { title: e.target.value })}
                    placeholder={`Задача ${index + 1}`}
                    style={{
                      flex: 1,
                      padding: '8px 10px',
                      borderRadius: 6,
                      border: '1px solid #c8ced6',
                    }}
                  />
                  {rows.length > 1 ? (
                    <button
                      type="button"
                      onClick={() => setRows((r) => r.filter((_, i) => i !== index))}
                      style={{
                        padding: '0 10px',
                        borderRadius: 6,
                        border: '1px solid #c8ced6',
                        background: '#fff',
                      }}
                      title="Убрать задачу"
                    >
                      ×
                    </button>
                  ) : null}
                </div>
              ))}
              <button
                type="button"
                data-testid="add-task-row"
                onClick={addTaskRow}
                style={{
                  marginBottom: 12,
                  padding: '6px 10px',
                  borderRadius: 6,
                  border: '1px solid #c8ced6',
                  background: '#fff',
                  cursor: 'pointer',
                }}
              >
                + Задача
              </button>
              <label style={{ display: 'block', marginBottom: 12, fontSize: 13 }}>
                <input
                  type="checkbox"
                  data-testid="sequential-task-dependencies"
                  checked={sequential}
                  onChange={e => setSequential(e.target.checked)}
                />
                {' '}Выполнять задачи последовательно (следующая только после completed предыдущей)
              </label>
              <p style={{ fontSize: 12, color: '#5b6472', marginTop: -6 }}>
                Порядок не заменяет Contract Gate: для автоматической проверки каждой стадии
                нужны серверные контракты.
              </p>
              {launchError ? <p style={{ color: '#a3271c', fontSize: 13 }}>{launchError}</p> : null}
              <button
                type="submit"
                data-testid="run-create-button"
                disabled={
                  launching || !name.trim() || rows.filter((r) => r.title.trim()).length === 0
                }
                style={{
                  display: 'block',
                  width: '100%',
                  padding: '10px',
                  borderRadius: 6,
                  border: 'none',
                  background: '#1c5fa8',
                  color: '#fff',
                  fontWeight: 600,
                  cursor: 'pointer',
                  opacity: launching ? 0.6 : 1,
                }}
              >
                {launching ? 'Запуск…' : 'Создать и запустить конвейер'}
              </button>
            </form>
          </Card>

          {runId ? (
            <Card title="Детали выбранного запуска">
              {selectedRun.loading ? <p style={{ color: '#5b6472' }}>Загрузка…</p> : null}
              {selectedRun.error ? (
                <p style={{ color: '#a3271c' }}>Ошибка: {selectedRun.error.message}</p>
              ) : null}
              {selectedRun.data ? (
                <RunDetail
                  run={selectedRun.data}
                  tasks={selectedTasks.data ?? []}
                  onOpenTask={openTask}
                />
              ) : null}
            </Card>
          ) : null}
        </div>
      </div>
    </div>
  );
}

function RunDetail({
  run,
  tasks,
  onOpenTask,
}: {
  run: RunResponse;
  tasks: TaskResponse[];
  onOpenTask: (task: TaskResponse) => void;
}) {
  return (
    <div>
      <div
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          marginBottom: 8,
        }}
      >
        <strong>{run.name}</strong>
        <StatusBadge status={run.status} />
      </div>
      <dl
        style={{
          margin: 0,
          fontSize: 13,
          display: 'grid',
          gridTemplateColumns: 'auto 1fr',
          gap: '4px 12px',
        }}
      >
        <dt style={{ color: '#5b6472' }}>ID</dt>
        <dd style={{ margin: 0 }}>{run.id}</dd>
        <dt style={{ color: '#5b6472' }}>Проект</dt>
        <dd style={{ margin: 0 }}>{run.project_id}</dd>
        <dt style={{ color: '#5b6472' }}>Старт</dt>
        <dd style={{ margin: 0 }}>{formatDate(run.started_at)}</dd>
        <dt style={{ color: '#5b6472' }}>Завершён</dt>
        <dd style={{ margin: 0 }}>{formatDate(run.completed_at)}</dd>
      </dl>
      {tasks.length > 0 ? (
        <div style={{ marginTop: 12 }}>
          <span style={{ fontSize: 12, color: '#5b6472', display: 'block', marginBottom: 6 }}>
            Задачи запуска (нажмите, чтобы открыть карточку)
          </span>
          <ul style={{ listStyle: 'none', margin: 0, padding: 0 }}>
            {tasks.map((task) => (
              <li key={task.id}>
                <button
                  data-testid={`run-task-${task.id}`}
                  onClick={() => onOpenTask(task)}
                  style={{
                    width: '100%',
                    textAlign: 'left',
                    padding: '8px 10px',
                    borderRadius: 6,
                    border: '1px solid #e2e6ea',
                    background: '#fff',
                    cursor: 'pointer',
                    marginBottom: 6,
                    display: 'flex',
                    justifyContent: 'space-between',
                    alignItems: 'center',
                    gap: 8,
                  }}
                >
                  <span>{task.title}</span>
                  <StatusBadge status={task.status} />
                </button>
              </li>
            ))}
          </ul>
        </div>
      ) : null}
    </div>
  );
}
