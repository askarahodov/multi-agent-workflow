/**
 * MVP v1 — Task card section (карточка задачи).
 *
 * Shows the currently selected task's full detail plus its attempts history.
 * Supports interaction against the real task lifecycle endpoints: claim
 * (`POST /tasks/{id}/claim`), submit (`.../attempts/{attempt}/submit`), fail
 * and block. Selecting a task comes from the board or the runs section.
 */

import { type CSSProperties, type FormEvent, useState } from 'react';

import type { AttemptResponse, TaskResponse, GitEvidenceResponse } from '../../api/types';
import { useMvpStore } from '../mvpStore';
import { useAsync } from '../useAsync';
import { Card, formatDate, PageHeader, StatusBadge } from '../ui';

export default function TaskSection() {
  const api = useMvpStore((s) => s.api);
  const taskId = useMvpStore((s) => s.taskId);
  const selectTask = useMvpStore((s) => s.selectTask);

  const task = useAsync<TaskResponse | null>(() =>
    useMvpStore.getState().taskId
      ? api.getTask(useMvpStore.getState().taskId!)
      : Promise.resolve(null),
  );
  const attempts = useAsync<AttemptResponse[]>(() =>
    useMvpStore.getState().taskId
      ? api.listTaskAttempts(useMvpStore.getState().taskId!)
      : Promise.resolve([]),
  );

  const gitEvidence = useAsync<GitEvidenceResponse[]>(() =>
    useMvpStore.getState().taskId
      ? api.listTaskGitEvidence(useMvpStore.getState().taskId!)
      : Promise.resolve([]),
  );
  const [agentId, setAgentId] = useState('ag_1');
  const [output, setOutput] = useState('{\n  "result": "ok"\n}');
  const [errorText, setErrorText] = useState('');
  const [reason, setReason] = useState('');
  const [actionError, setActionError] = useState<string | null>(null);

  function refreshAll() {
    task.reload();
    attempts.reload();
    gitEvidence.reload();
  }

  function clearActionError() {
    setActionError(null);
  }

  async function runAction(fn: () => Promise<unknown>) {
    clearActionError();
    try {
      await fn();
      refreshAll();
    } catch (error) {
      setActionError(error instanceof Error ? error.message : String(error));
    }
  }

  async function onClaim(event: FormEvent) {
    event.preventDefault();
    if (!taskId) return;
    await runAction(() => api.claimTask(taskId, { agent_id: agentId }));
  }

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    if (!taskId) return;
    const latest = attempts.data?.[attempts.data.length - 1];
    if (!latest) {
      setActionError('Сначала выполните claim — у задачи нет попытки.');
      return;
    }
    let parsed: Record<string, unknown>;
    try {
      parsed = JSON.parse(output);
    } catch {
      setActionError('Вывод должен быть корректным JSON.');
      return;
    }
    await runAction(() => api.submitTask(taskId, latest.id, { output: parsed }, agentId));
  }

  async function onFail(event: FormEvent) {
    event.preventDefault();
    if (!taskId) return;
    const latest = attempts.data?.[attempts.data.length - 1];
    if (!latest) {
      setActionError('Сначала выполните claim — у задачи нет попытки.');
      return;
    }
    const msg = errorText.trim() || 'failed by operator';
    await runAction(() => api.failTask(taskId, latest.id, { error: msg }, agentId));
  }

  async function onBlock(event: FormEvent) {
    event.preventDefault();
    if (!taskId) return;
    const msg = reason.trim() || 'blocked by operator';
    await runAction(() => api.blockTask(taskId, { reason: msg }, agentId));
  }

  if (!taskId) {
    return (
      <div>
        <PageHeader title="Карточка задачи" subtitle="Откройте задачу с доски или из запусков." />
        <Card>
          <p style={{ color: '#5b6472' }}>Задача не выбрана.</p>
        </Card>
      </div>
    );
  }

  return (
    <div>
      <PageHeader
        title="Карточка задачи"
        subtitle="Детали выбранной задачи и её попытки (жизненный цикл claim → submit/fail/block)."
      />

      {task.loading ? <p style={{ color: '#5b6472' }}>Загрузка…</p> : null}
      {task.error ? <p style={{ color: '#a3271c' }}>Ошибка: {task.error.message}</p> : null}
      {task.data ? (
        <div
          style={{ display: 'grid', gridTemplateColumns: '3fr 2fr', gap: 16, alignItems: 'start' }}
        >
          {/* Left: task detail + attempts */}
          <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
            <Card title="Задача">
              <div
                style={{
                  display: 'flex',
                  justifyContent: 'space-between',
                  alignItems: 'center',
                  marginBottom: 8,
                }}
              >
                <strong style={{ fontSize: 16 }}>{task.data.title}</strong>
                <StatusBadge status={task.data.status} />
              </div>
              {task.data.description ? (
                <p style={{ color: '#5b6472', fontSize: 13 }}>{task.data.description}</p>
              ) : null}
              <dl
                style={{
                  margin: '8px 0 0',
                  fontSize: 13,
                  display: 'grid',
                  gridTemplateColumns: 'auto 1fr',
                  gap: '4px 12px',
                }}
              >
                <dt style={{ color: '#5b6472' }}>ID</dt>
                <dd style={{ margin: 0 }}>{task.data.id}</dd>
                <dt style={{ color: '#5b6472' }}>Запуск</dt>
                <dd style={{ margin: 0 }}>{task.data.workflow_run_id}</dd>
                <dt style={{ color: '#5b6472' }}>Узел</dt>
                <dd style={{ margin: 0 }}>{task.data.node_id ?? '—'}</dd>
                <dt style={{ color: '#5b6472' }}>Приоритет</dt>
                <dd style={{ margin: 0 }}>{task.data.priority}</dd>
                <dt style={{ color: '#5b6472' }}>Агент</dt>
                <dd style={{ margin: 0 }}>{task.data.assigned_agent_id ?? 'не назначен'}</dd>
                <dt style={{ color: '#5b6472' }}>Попытки</dt>
                <dd style={{ margin: 0 }}>
                  {task.data.attempt_count}/{task.data.max_attempts}
                </dd>
                <dt style={{ color: '#5b6472' }}>Старт</dt>
                <dd style={{ margin: 0 }}>{formatDate(task.data.started_at)}</dd>
                <dt style={{ color: '#5b6472' }}>Завершён</dt>
                <dd style={{ margin: 0 }}>{formatDate(task.data.completed_at)}</dd>
              </dl>
              {task.data.input_data ? (
                <details style={{ marginTop: 10 }}>
                  <summary style={{ cursor: 'pointer', fontSize: 13, color: '#1c5fa8' }}>
                    Входные данные
                  </summary>
                  <pre
                    style={{
                      fontSize: 11,
                      background: '#f7f8fa',
                      padding: 8,
                      borderRadius: 6,
                      overflow: 'auto',
                    }}
                  >
                    {JSON.stringify(task.data.input_data, null, 2)}
                  </pre>
                </details>
              ) : null}
              {task.data.output_data ? (
                <details style={{ marginTop: 8 }} open>
                  <summary style={{ cursor: 'pointer', fontSize: 13, color: '#1c5fa8' }}>
                    Результат
                  </summary>
                  <pre
                    data-testid="task-output"
                    style={{
                      fontSize: 11,
                      background: '#f0f9f2',
                      padding: 8,
                      borderRadius: 6,
                      overflow: 'auto',
                    }}
                  >
                    {JSON.stringify(task.data.output_data, null, 2)}
                  </pre>
                </details>
              ) : null}
            </Card>

            <Card title="Git-артефакты">
              <p style={{ color: '#5b6472', fontSize: 12 }}>
                SHA сообщён доверенным worker. Это не независимая проверка Git и не разрешение на выпуск.
              </p>
              {gitEvidence.loading ? <p>Загрузка…</p> : null}
              {gitEvidence.error ? <p role="alert">Ошибка загрузки Git evidence</p> : null}
              {!gitEvidence.loading && !gitEvidence.error && gitEvidence.data?.length === 0
                ? <p>Подтверждённых Contract Gate Git-отчётов нет.</p> : null}
              {gitEvidence.data?.map(item => (
                <div key={item.attempt_id} data-testid="task-git-artifact">
                  <p style={{ fontSize: 12 }}>Источник: {item.provenance}</p>
                  <code style={{ overflowWrap: 'anywhere' }}>{item.commit_sha}</code>
                  <ul>{item.changed_paths.map(path => <li key={path}>{path}</li>)}</ul>
                </div>
              ))}
            </Card>

            <Card title="Попытки">
              {attempts.loading ? <p style={{ color: '#5b6472' }}>Загрузка…</p> : null}
              {attempts.error ? (
                <p style={{ color: '#a3271c' }}>Ошибка: {attempts.error.message}</p>
              ) : null}
              {!attempts.loading && !attempts.error && attempts.data!.length === 0 ? (
                <p style={{ color: '#5b6472' }}>Попыток пока нет.</p>
              ) : null}
              <ul style={{ listStyle: 'none', margin: 0, padding: 0 }}>
                {attempts.data?.map((attempt) => (
                  <li
                    key={attempt.id}
                    style={{
                      border: '1px solid #e2e6ea',
                      borderRadius: 8,
                      padding: '10px 12px',
                      marginBottom: 8,
                    }}
                  >
                    <div
                      style={{
                        display: 'flex',
                        justifyContent: 'space-between',
                        alignItems: 'center',
                      }}
                    >
                      <span style={{ fontSize: 12, color: '#9aa2af' }}>
                        попытка #{attempt.attempt_number}
                      </span>
                      <StatusBadge status={attempt.status} />
                    </div>
                    <p style={{ margin: '6px 0 0', fontSize: 13 }}>
                      агент: {attempt.agent_id ?? '—'} · {formatDate(attempt.started_at)}
                    </p>
                    {attempt.error ? (
                      <p style={{ margin: '4px 0 0', color: '#a3271c', fontSize: 13 }}>
                        {attempt.error}
                      </p>
                    ) : null}
                    {attempt.output_data ? (
                      <pre
                        style={{
                          fontSize: 11,
                          background: '#f7f8fa',
                          padding: 8,
                          borderRadius: 6,
                          overflow: 'auto',
                          marginTop: 6,
                        }}
                      >
                        {JSON.stringify(attempt.output_data, null, 2)}
                      </pre>
                    ) : null}
                  </li>
                ))}
              </ul>
            </Card>
          </div>

          {/* Right: task operations */}
          <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
            <Card title="Операции (lifecycle)">
              {actionError ? <p style={{ color: '#a3271c', fontSize: 13 }}>{actionError}</p> : null}

              <label style={{ display: 'block', marginBottom: 10 }}>
                <span style={{ fontSize: 12, color: '#5b6472', display: 'block', marginBottom: 4 }}>
                  Агент
                </span>
                <input
                  data-testid="task-agent-input"
                  value={agentId}
                  onChange={(e) => setAgentId(e.target.value)}
                  style={{
                    width: '100%',
                    boxSizing: 'border-box',
                    padding: '8px 10px',
                    borderRadius: 6,
                    border: '1px solid #c8ced6',
                  }}
                />
              </label>

              <form onSubmit={onClaim} style={{ marginBottom: 12 }}>
                <button
                  type="submit"
                  data-testid="task-claim-button"
                  style={buttonStyle}
                  disabled={!taskId}
                >
                  Claim (взять задачу)
                </button>
              </form>

              <form onSubmit={onSubmit} style={{ marginBottom: 12 }}>
                <label style={{ display: 'block', marginBottom: 6 }}>
                  <span
                    style={{ fontSize: 12, color: '#5b6472', display: 'block', marginBottom: 4 }}
                  >
                    Вывод (JSON)
                  </span>
                  <textarea
                    data-testid="task-output-input"
                    value={output}
                    onChange={(e) => setOutput(e.target.value)}
                    rows={3}
                    style={{
                      width: '100%',
                      boxSizing: 'border-box',
                      padding: '8px 10px',
                      borderRadius: 6,
                      border: '1px solid #c8ced6',
                      fontFamily: 'monospace',
                      fontSize: 12,
                    }}
                  />
                </label>
                <button
                  type="submit"
                  data-testid="task-submit-button"
                  style={{ ...buttonStyle, background: '#18703b', marginTop: 4 }}
                >
                  Submit (завершить)
                </button>
              </form>

              <form onSubmit={onFail} style={{ marginBottom: 12 }}>
                <label style={{ display: 'block', marginBottom: 6 }}>
                  <span
                    style={{ fontSize: 12, color: '#5b6472', display: 'block', marginBottom: 4 }}
                  >
                    Ошибка
                  </span>
                  <input
                    data-testid="task-fail-input"
                    value={errorText}
                    onChange={(e) => setErrorText(e.target.value)}
                    style={{
                      width: '100%',
                      boxSizing: 'border-box',
                      padding: '8px 10px',
                      borderRadius: 6,
                      border: '1px solid #c8ced6',
                    }}
                  />
                </label>
                <button
                  type="submit"
                  data-testid="task-fail-button"
                  style={{ ...buttonStyle, background: '#a3271c' }}
                >
                  Fail (провалить)
                </button>
              </form>

              <form onSubmit={onBlock}>
                <label style={{ display: 'block', marginBottom: 6 }}>
                  <span
                    style={{ fontSize: 12, color: '#5b6472', display: 'block', marginBottom: 4 }}
                  >
                    Причина блока
                  </span>
                  <input
                    data-testid="task-block-input"
                    value={reason}
                    onChange={(e) => setReason(e.target.value)}
                    style={{
                      width: '100%',
                      boxSizing: 'border-box',
                      padding: '8px 10px',
                      borderRadius: 6,
                      border: '1px solid #c8ced6',
                    }}
                  />
                </label>
                <button
                  type="submit"
                  data-testid="task-block-button"
                  style={{ ...buttonStyle, background: '#9a6a12' }}
                >
                  Block (заблокировать)
                </button>
              </form>
            </Card>

            <button
              onClick={() => selectTask(null)}
              style={{
                padding: '8px 12px',
                borderRadius: 6,
                border: '1px solid #c8ced6',
                background: '#fff',
                cursor: 'pointer',
              }}
            >
              Закрыть карточку
            </button>
          </div>
        </div>
      ) : null}

      <button
        onClick={refreshAll}
        style={{
          marginTop: 12,
          padding: '8px 12px',
          borderRadius: 6,
          border: '1px solid #c8ced6',
          background: '#fff',
          cursor: 'pointer',
        }}
      >
        Обновить
      </button>
    </div>
  );
}

const buttonStyle: CSSProperties = {
  width: '100%',
  padding: '9px',
  borderRadius: 6,
  border: 'none',
  background: '#1c5fa8',
  color: '#fff',
  fontWeight: 600,
  cursor: 'pointer',
};
