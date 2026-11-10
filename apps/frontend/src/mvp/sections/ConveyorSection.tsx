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

import type { AgentDefinitionRef, AgentResponse, ApiAdapter, RunResponse, TaskResponse } from '../../api/types';
import AgentBudgetOverview from './AgentBudgetOverview';
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

/** Cursor pagination is fail-closed: a missed page may hide a blocked stage. */
export async function listConveyorTasks(api: ApiAdapter, runId: string): Promise<TaskResponse[]> {
  const all: TaskResponse[] = [];
  const seen = new Set<string>();
  let after: string | undefined;
  for (let page = 0; page < 100; page++) {
    const result = await api.listRunTasks(runId, { after, limit: 100 });
    if (!Array.isArray(result.items) ||
        result.items.some(item => !item || item.workflow_run_id !== runId)) {
      throw new Error('Некорректные задачи выбранного запуска');
    }
    all.push(...result.items);
    if (!result.next_cursor) return all;
    if (seen.has(result.next_cursor)) throw new Error('Сервер повторяет курсор задач');
    seen.add(result.next_cursor);
    after = result.next_cursor;
  }
  throw new Error('Превышен предел страниц задач');
}

async function listConveyorProfiles(api: ApiAdapter): Promise<AgentDefinitionRef[]> {
  const result: AgentDefinitionRef[] = [];
  const seen = new Set<string>();
  let after: string | undefined;
  for (let page = 0; page < 100; page++) {
    const response = await api.listAgentDefinitions({ after, limit: 100 });
    if (!Array.isArray(response.items)) throw new Error('Каталог профилей недоступен');
    result.push(...response.items);
    if (!response.next_cursor) return result;
    if (seen.has(response.next_cursor)) throw new Error('Повторяется курсор профилей');
    seen.add(response.next_cursor);
    after = response.next_cursor;
  }
  throw new Error('Превышен предел страниц профилей');
}

/** Published task refs are provenance only, never a worker authorization. */
export function stageReference(task: TaskResponse): {
  agent_definition_id: string; model_profile_id: string; tool_policy_id: string;
} | null {
  const refs = task.input_data?.workflow_agent_reference;
  if (!refs || typeof refs !== 'object' || Array.isArray(refs)) return null;
  const value = refs as Record<string, unknown>;
  if (Object.keys(value).length !== 3 ||
      ['agent_definition_id', 'model_profile_id', 'tool_policy_id'].some(
        field => typeof value[field] !== 'string' || !value[field])) return null;
  return {
    agent_definition_id: value.agent_definition_id as string,
    model_profile_id: value.model_profile_id as string,
    tool_policy_id: value.tool_policy_id as string,
  };
}

export default function ConveyorSection() {
  const api = useMvpStore((s) => s.api);
  const runId = useMvpStore((s) => s.runId);
  const projectId = useMvpStore((s) => s.projectId);
  const selectRun = useMvpStore((s) => s.selectRun);
  const [inspectedProfileId, setInspectedProfileId] = useState<string | null>(null);
  const profiles = useAsync<AgentDefinitionRef[]>(() => listConveyorProfiles(api));

  const agents = useAsync<AgentResponse[]>(() => api.listAgents());
  const runs = useAsync<RunResponse[]>(() =>
    listConveyorRuns(api, useMvpStore.getState().projectId));
  const pipeline = useAsync<TaskResponse[]>(() =>
    useMvpStore.getState().runId
      ? listConveyorTasks(api, useMvpStore.getState().runId!)
      : Promise.resolve([]),
  );

  const [agentName, setAgentName] = useState('');
  const [registering, setRegistering] = useState(false);
  const [registerError, setRegisterError] = useState<string | null>(null);

  useEffect(() => {
    runs.reload();
    profiles.reload();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [api, projectId]);

  useEffect(() => {
    setInspectedProfileId(null);
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
  const profileLookup = new Map((profiles.data ?? []).map(profile => [profile.id, profile]));
  const selectedProfile = visibleTasks.some(task =>
    stageReference(task)?.agent_definition_id === inspectedProfileId)
    ? profileLookup.get(inspectedProfileId ?? '') : undefined;

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
        subtitle="Зарегистрированные native workers отдельно от логических профилей и стадий опубликованного workflow."
      />

      <div
        style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16, alignItems: 'start' }}
      >
        {/* Left: roles / agents */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
          <Card title="Зарегистрированные native workers">
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

          <Card title="Зарегистрировать native worker">
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
                        {(() => {
                          const ref = stageReference(task);
                          if (!ref) return <p data-testid={'conveyor-stage-profile-' + task.id}>
                            Опубликованный профиль не указан. Историческая задача
                            не доказывает готовность native worker.
                          </p>;
                          if (profiles.loading) return <p>Проверка профиля этапа…</p>;
                          if (profiles.error) return <p role="alert">Профили недоступны; готовность этапа неизвестна.</p>;
                          const profile = profileLookup.get(ref.agent_definition_id);
                          if (!profile) return <p data-testid={'conveyor-stage-profile-' + task.id}
                            role="alert">Профиль этапа не найден. Требуется новая публикация.</p>;
                          const matching = profile.default_model_profile_id === ref.model_profile_id &&
                            profile.default_tool_policy_id === ref.tool_policy_id;
                          return <div data-testid={'conveyor-stage-profile-' + task.id}>
                            <p>Логический профиль: <strong>{sanitizeTaskDisplayText(profile.name)}</strong>
                              {' '}· роль {sanitizeTaskDisplayText(profile.role ?? 'не задана')}
                              {' '}· текущая ревизия v{profile.version ?? '?'}.</p>
                            <p>{matching
                              ? 'Модель и policy совпадают с текущим профилем. Ревизия на задаче не зафиксирована.'
                              : 'Модель или policy после публикации изменилась; требуется новый workflow snapshot.'}</p>
                            <button type="button" data-testid={'conveyor-inspect-budget-' + task.id}
                              onClick={() => setInspectedProfileId(profile.id)}>
                              Проверить серверный бюджет профиля
                            </button>
                            <p>Логический профиль не подтверждает live native worker,
                              provider key, бюджет streaming или независимую QA.</p>
                          </div>;
                        })()}
                      </div>
                    </li>
                  ))}
                </ol>
              )
            ) : null}
            {selectedProfile ? <AgentBudgetOverview
              agentId={selectedProfile.id} version={selectedProfile.version ?? null}/> : null}
          </Card>
        </div>
      </div>
    </div>
  );
}
