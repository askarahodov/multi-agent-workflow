/** Read-only task lifecycle: attempts, Contract Gate, Git and independent QA evidence.
 * Native leased workers own execution; the end-user UI never impersonates an agent.
 */

import type { AttemptResponse, TaskResponse, GitEvidenceResponse, TaskQaStatus } from '../../api/types';
import { useMvpStore } from '../mvpStore';
import { useAsync } from '../useAsync';
import { Card, formatDate, PageHeader, StatusBadge } from '../ui';

export default function TaskSection() {
  const taskId = useMvpStore((s) => s.taskId);
  // Fully remount request state when the selection changes. This prevents
  // attempts/QA/Git evidence for a previous task being shown under a new card.
  return <TaskContent key={taskId ?? 'none'} taskId={taskId} />;
}

function TaskContent({ taskId }: { taskId: string | null }) {
  const api = useMvpStore((s) => s.api);
  const selectTask = useMvpStore((s) => s.selectTask);
  const selectRun = useMvpStore((s) => s.selectRun);
  const setSection = useMvpStore((s) => s.setSection);

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
  const independentQa = useAsync<TaskQaStatus | null>(() =>
    useMvpStore.getState().taskId
      ? api.getTaskQaStatus(useMvpStore.getState().taskId!)
      : Promise.resolve(null),
  );

  function refreshAll() {
    task.reload();
    attempts.reload();
    gitEvidence.reload();
    independentQa.reload();
  }

  // Never display another task's cached details during rapid navigation.
  const visibleTask = task.data?.id === taskId ? task.data : null;

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
        subtitle="Серверные статусы, история попыток, Contract Gate и независимые QA-артефакты. Исполнением управляет native worker."
      />

      {task.loading ? <p style={{ color: '#5b6472' }}>Загрузка…</p> : null}
      {task.error ? <p style={{ color: '#a3271c' }}>Ошибка: {task.error.message}</p> : null}
      {visibleTask ? (
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
                <strong style={{ fontSize: 16 }}>{visibleTask.title}</strong>
                <StatusBadge status={visibleTask.status} />
              </div>
              {visibleTask.description ? (
                <p style={{ color: '#5b6472', fontSize: 13 }}>{visibleTask.description}</p>
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
                <dd style={{ margin: 0 }}>{visibleTask.id}</dd>
                <dt style={{ color: '#5b6472' }}>Запуск</dt>
                <dd style={{ margin: 0 }}>{visibleTask.workflow_run_id}</dd>
                <dt style={{ color: '#5b6472' }}>Узел</dt>
                <dd style={{ margin: 0 }}>{visibleTask.node_id ?? '—'}</dd>
                <dt style={{ color: '#5b6472' }}>Приоритет</dt>
                <dd style={{ margin: 0 }}>{visibleTask.priority}</dd>
                <dt style={{ color: '#5b6472' }}>Агент</dt>
                <dd style={{ margin: 0 }}>{visibleTask.assigned_agent_id ?? 'не назначен'}</dd>
                <dt style={{ color: '#5b6472' }}>Попытки</dt>
                <dd style={{ margin: 0 }}>
                  {visibleTask.attempt_count}/{visibleTask.max_attempts}
                </dd>
                <dt style={{ color: '#5b6472' }}>Старт</dt>
                <dd style={{ margin: 0 }}>{formatDate(visibleTask.started_at)}</dd>
                <dt style={{ color: '#5b6472' }}>Завершён</dt>
                <dd style={{ margin: 0 }}>{formatDate(visibleTask.completed_at)}</dd>
              </dl>
              {visibleTask.input_data ? (
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
                    {JSON.stringify(visibleTask.input_data, null, 2)}
                  </pre>
                </details>
              ) : null}
              {visibleTask.output_data ? (
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
                    {JSON.stringify(visibleTask.output_data, null, 2)}
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

            <Card title="Независимая QA">
              {independentQa.loading ? <p>Загрузка QA…</p> : null}
              {independentQa.error ? (
                <p role="alert">Ошибка чтения QA evidence: {independentQa.error.message}</p>
              ) : null}
              {independentQa.data?.status === 'disabled' ? (
                <p data-testid="task-qa-status">Строгая независимая QA не включена для этого сервера.</p>
              ) : null}
              {independentQa.data?.status === 'pending' ? (
                <p data-testid="task-qa-status">
                  Ожидается независимая QA. Контракт и отчёт worker не заменяют tester/reviewer/security gates.
                </p>
              ) : null}
              {independentQa.data?.status === 'verified' ? (
                <div data-testid="task-qa-status">
                  <p>QA подтверждена операторским подписанным свидетельством.</p>
                  <p style={{ overflowWrap: 'anywhere', fontSize: 12 }}>
                    Git SHA: <code>{independentQa.data.commit_sha}</code>
                  </p>
                  <p style={{ fontSize: 12 }}>
                    Пройденные gates: tester · reviewer · security
                  </p>
                  <p style={{ fontSize: 12, color: '#5b6472' }}>
                    Подписант: {independentQa.data.issued_by}
                  </p>
                  <p style={{ fontSize: 12, color: '#5b6472' }}>
                    Аттестация QA не является разрешением на выпуск релиза.
                  </p>
                </div>
              ) : null}
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

          {/* End-user task details are intentionally read-only. Worker/administrator
              mutation routes remain server-authorized, never surfaced here. */}
          <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
            <Card title="Контроль жизненного цикла">
              <p data-testid="task-readonly-status">
                Карточка доступна только для просмотра. Запуск и завершение задач
                выполняет назначенный native worker через серверную аренду.
                Ручные Claim / Submit / Fail / Block не являются пользовательскими
                действиями и не могут заменить проверку Contract Gate.
              </p>
              <p>
                Если задача ожидает обработки, проверьте доступность worker в журнале.
                Если задача заблокирована после сбоя, откройте карантин для
                сверки побочных действий без автоматического повтора.
              </p>
              <button type="button" data-testid="task-open-run"
                onClick={() => {
                  selectRun(visibleTask!.workflow_run_id);
                  setSection('runs');
                }} style={{padding:10,marginBottom:8}}>
                Открыть запуск
              </button>
              <button type="button" data-testid="task-open-log"
                onClick={() => {
                  selectRun(visibleTask!.workflow_run_id);
                  setSection('agent-log');
                }} style={{padding:10,marginBottom:8}}>
                Открыть живой журнал
              </button>
              <button type="button" data-testid="task-open-recovery"
                onClick={() => setSection('recovery')} style={{padding:10}}>
                Карантин и безопасное восстановление
              </button>
            </Card>
            <button type="button"
              onClick={() => selectTask(null)}
              style={{ padding: '8px 12px', borderRadius: 6,
                border: '1px solid #c8ced6', background: '#fff', cursor: 'pointer' }}>
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

