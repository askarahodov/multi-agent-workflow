/**
 * MVP v1 — Conveyor & roles section (конвейер и роли).
 *
 * Shows the platform's registered agent roles (the "roles" side: who can pick
 * up work) alongside the conveyor (a pipeline view of the currently selected
 * run's tasks in order). An agent can be registered here (offline mock / real
 * `/agents/register`), reinforcing the "conveyor and roles" workflow.
 */

import { type FormEvent, useEffect, useState } from 'react';

import type { AgentResponse, RunResponse, TaskResponse } from '../../api/types';
import { useMvpStore } from '../mvpStore';
import { useAsync } from '../useAsync';
import { Card, formatDate, PageHeader, StatusBadge } from '../ui';

export default function ConveyorSection() {
  const api = useMvpStore((s) => s.api);
  const runId = useMvpStore((s) => s.runId);
  const selectRun = useMvpStore((s) => s.selectRun);

  const agents = useAsync<AgentResponse[]>(() => api.listAgents());
  const runs = useAsync<RunResponse[]>(async () => (await api.listRuns({})).items);
  const pipeline = useAsync<TaskResponse[]>(() =>
    useMvpStore.getState().runId
      ? api.listRunTasks(useMvpStore.getState().runId!).then((page) => page.items)
      : Promise.resolve([]),
  );

  const [agentName, setAgentName] = useState('');
  const [registering, setRegistering] = useState(false);
  const [registerError, setRegisterError] = useState<string | null>(null);

  useEffect(() => {
    pipeline.reload();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [runId]);

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
              <p style={{ color: '#a3271c' }}>Ошибка: {agents.error.message}</p>
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
                        <strong>{agent.name}</strong>
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
                <p style={{ color: '#a3271c', fontSize: 13, marginTop: 8 }}>{registerError}</p>
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
                {runs.data?.map((run) => (
                  <option key={run.id} value={run.id}>
                    {run.name}
                  </option>
                ))}
              </select>
            </div>

            {!runId ? (
              <p style={{ color: '#5b6472' }}>Выберите запуск, чтобы увидеть конвейер задач.</p>
            ) : null}
            {pipeline.loading ? <p style={{ color: '#5b6472' }}>Загрузка…</p> : null}
            {pipeline.error ? (
              <p style={{ color: '#a3271c' }}>Ошибка: {pipeline.error.message}</p>
            ) : null}
            {runId && !pipeline.loading && !pipeline.error ? (
              pipeline.data!.length === 0 ? (
                <p style={{ color: '#5b6472' }}>В этом запуске нет задач.</p>
              ) : (
                <ol style={{ margin: 0, paddingLeft: 20 }}>
                  {pipeline.data!.map((task, index) => (
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
                          <strong style={{ flex: 1 }}>{task.title}</strong>
                          <StatusBadge status={task.status} />
                        </div>
                        <p style={{ margin: '4px 0 0', color: '#9aa2af', fontSize: 12 }}>
                          {task.assigned_agent_id
                            ? `агент: ${task.assigned_agent_id}`
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
