/**
 * MVP v1 — Conveyor & roles section (конвейер и роли).
 *
 * Shows the platform's registered agent roles (the "roles" side: who can pick
 * up work) alongside the conveyor (a pipeline view of the currently selected
 * run's tasks in order). An agent can be registered here (offline mock / real
 * `/agents/register`), reinforcing the "conveyor and roles" workflow.
 */

import { type FormEvent, useEffect, useState } from 'react';
import { sanitizeTaskDisplayText } from '../../api/taskDisplayRedaction';

import type { AgentResponse, ApiAdapter, RunResponse, TaskResponse } from '../../api/types';
import { useMvpStore } from '../mvpStore';
import { useAsync } from '../useAsync';
import { Card, formatDate, PageHeader, StatusBadge } from '../ui';

/** Bound pagination and validate the server's project filter independently. */
export async function listConveyorRuns(api: ApiAdapter, projectId: string | null): Promise<RunResponse[]> {
  const collected: RunResponse[] = [];
  const seen = new Set<string>();
  let after: string | undefined;
  for (let page = 0; page < 100; page += 1) {
    const response = await api.listRuns({ projectId: projectId ?? undefined, after, limit: 100 });
    if (!Array.isArray(response.items)) throw new Error('Сервер вернул некорректный список запусков');
    collected.push(...response.items.filter((run) => !projectId || run.project_id === projectId));
    if (!response.next_cursor) return collected;
    if (seen.has(response.next_cursor)) throw new Error('Сервер повторяет курсор запусков');
    seen.add(response.next_cursor);
    after = response.next_cursor;
  }
  throw new Error('Превышен предел страниц запусков');
}

export default function ConveyorSection() {
  const api = useMvpStore((s) => s.api);
  const runId = useMvpStore((s) => s.runId);
  const projectId = useMvpStore((s) => s.projectId);
  const selectRun = useMvpStore((s) => s.selectRun);

  const agents = useAsync<AgentResponse[]>(() => api.listAgents());
  const runs = useAsync<RunResponse[]>(() =>
    listConveyorRuns(api, useMvpStore.getState().projectId));
  const pipeline = useAsync<TaskResponse[]>(() =>
    useMvpStore.getState().runId
      ? api.listRunTasks(useMvpStore.getState().runId!).then((page) => page.items)
      : Promise.resolve([]),
  );

  const [agentName, setAgentName] = useState('');
  const [registering, setRegistering] = useState(false);
  const [registerError, setRegisterError] = useState<string | null>(null);

  useEffect(() => {
    runs.reload();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [api, projectId]);

  useEffect(() => {
    pipeline.reload();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [runId]);

  // useAsync intentionally retains old data while a replacement request loads.
  // The visible run and its tasks must always belong to the current selection.
  const visibleRuns = (runs.data ?? []).filter((run) =>
    !projectId || run.project_id === projectId);
  const activeRun = visibleRuns.find((run) => run.id === runId);
  const visibleTasks = activeRun
    ? (pipeline.data ?? []).filter((task) => task.workflow_run_id === activeRun.id)
    : [];

  async function onRegister(event: FormEvent) {
    event.preventDefault();
    if (!agentName.trim()) return;
    setRegistering(true);
    setRegisterError(null);
    try {
      await api.registerAgent({ name: agentName.trim() });
      setAgentName('');
      agents.reload();
    } catch (error) {
      setRegisterError(error instanceof Error ? error.message : String(error));
    } finally {
      setRegistering(false);
    }
  }

  return (
    <div>
      <PageHeader
        title="Конвейер и роли"
        subtitle="Роли-агенты платформы и порядок задач выбранного запуска (конвейер)."
      />

      <div
        style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16, alignItems: 'start' }}
      >
        {/* Left: roles / agents */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
          <Card title="Роли (зарегистрированные агенты)">
            {agents.loading ? <p style={{ color: '#5b6472' }}>Загрузка…</p> : null}
            {agents.error ? (
              <p style={{ color: '#a3271c' }}>Ошибка: {sanitizeTaskDisplayText(agents.error.message)}</p>
            ) : null}
            {!agents.loading && !agents.error ? (
              agents.data!.length === 0 ? (
                <p style={{ color: '#5b6472' }}>Агенты не зарегистрированы.</p>
              ) : (
                <ul style={{ listStyle: 'none', margin: 0, padding: 0 }}>
                  {agents.data!.map((agent) => (
                    <li
                      key={agent.id}
                      style={{
                        display: 'flex',
                        justifyContent: 'space-between',
                        alignItems: 'center',
                        padding: '10px 12px',
                        border: '1px solid #e2e6ea',
                        borderRadius: 8,
                        marginBottom: 8,
                      }}
                    >
                      <div>
                        <strong>{sanitizeTaskDisplayText(agent.name)}</strong>
                        <p style={{ margin: '2px 0 0', color: '#9aa2af', fontSize: 12 }}>
                          {agent.id}
                        </p>
                      </div>
                      <StatusBadge status={agent.status} />
                    </li>
                  ))}
                </ul>
              )
            ) : null}
          </Card>

          <Card title="Зарегистрировать роль">
            <form onSubmit={onRegister}>
              <div style={{ display: 'flex', gap: 8 }}>
                <input
                  data-testid="agent-name-input"
                  value={agentName}
                  onChange={(e) => setAgentName(e.target.value)}
                  placeholder="Имя агента"
                  style={{
                    flex: 1,
                    padding: '8px 10px',
                    borderRadius: 6,
                    border: '1px solid #c8ced6',
                  }}
                />
                <button
                  type="submit"
                  data-testid="agent-register-button"
                  disabled={registering || !agentName.trim()}
                  style={{
                    padding: '8px 14px',
                    borderRadius: 6,
                    border: 'none',
                    background: '#1c5fa8',
                    color: '#fff',
                    fontWeight: 600,
                    cursor: 'pointer',
                    opacity: registering || !agentName.trim() ? 0.6 : 1,
                  }}
                >
                  {registering ? '…' : 'Регистрация'}
                </button>
              </div>
              {registerError ? (
                <p style={{ color: '#a3271c', fontSize: 13, marginTop: 8 }}>{sanitizeTaskDisplayText(registerError)}</p>
              ) : null}
            </form>
          </Card>
        </div>

        {/* Right: conveyor pipeline */}
        <div>
          <Card title="Конвейер (задачи выбранного запуска)">
            <div style={{ marginBottom: 12 }}>
              <span style={{ fontSize: 12, color: '#5b6472', display: 'block', marginBottom: 4 }}>
                Запуск:
              </span>
              <select
                data-testid="conveyor-run-select"
                value={runId ?? ''}
                onChange={(e) => selectRun(e.target.value || null)}
                style={{
                  width: '100%',
                  padding: '8px 10px',
                  borderRadius: 6,
                  border: '1px solid #c8ced6',
                }}
              >
                <option value="">— выберите запуск —</option>
                {visibleRuns.map((run) => (
                  <option key={run.id} value={run.id}>
                    {sanitizeTaskDisplayText(run.name)}
                  </option>
                ))}
              </select>
            </div>

            {!activeRun ? (
              <p style={{ color: '#5b6472' }}>Выберите запуск, чтобы увидеть конвейер задач.</p>
            ) : null}
            {pipeline.loading ? <p style={{ color: '#5b6472' }}>Загрузка…</p> : null}
            {pipeline.error ? (
              <p style={{ color: '#a3271c' }}>Ошибка: {sanitizeTaskDisplayText(pipeline.error.message)}</p>
            ) : null}
            {activeRun && !pipeline.loading && !pipeline.error ? (
              visibleTasks.length === 0 ? (
                <p style={{ color: '#5b6472' }}>В этом запуске нет задач.</p>
              ) : (
                <ol style={{ margin: 0, paddingLeft: 20 }}>
                  {visibleTasks.map((task, index) => (
                    <li key={task.id} style={{ marginBottom: 8 }}>
                      <div
                        style={{
                          border: '1px solid #e2e6ea',
                          borderRadius: 8,
                          padding: '8px 10px',
                          background: '#fff',
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
                          <span style={{ fontSize: 12, color: '#9aa2af' }}>#{index + 1}</span>
                          <strong style={{ flex: 1 }}>{sanitizeTaskDisplayText(task.title)}</strong>
                          <StatusBadge status={task.status} />
                        </div>
                        <p style={{ margin: '4px 0 0', color: '#9aa2af', fontSize: 12 }}>
                          {task.assigned_agent_id
                            ? `агент: ${sanitizeTaskDisplayText(task.assigned_agent_id)}`
                            : 'агент не назначен'}{' '}
                          · старт {formatDate(task.started_at)}
                        </p>
                      </div>
                    </li>
                  ))}
                </ol>
              )
            ) : null}
          </Card>
        </div>
      </div>
    </div>
  );
}
