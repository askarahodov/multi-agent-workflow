/** Read-only task lifecycle: attempts, Contract Gate, Git and independent QA evidence.
 * Native leased workers own execution; the end-user UI never impersonates an agent.
 */

import { useEffect, useRef, useState } from 'react';
import type { ApiAdapter, AttemptResponse, TaskResponse, GitEvidenceResponse, TaskQaStatus, RunResponse } from '../../api/types';
import { useMvpStore } from '../mvpStore';
import { useAsync } from '../useAsync';
import { Card, formatDate, PageHeader, StatusBadge } from '../ui';
import { sanitizeTaskDisplayText, stringifyTaskDisplayValue } from '../../api/taskDisplayRedaction';
import {trustedTaskQa,trustedTaskGitReports} from './taskEvidenceValidation';

/** Evidence must not be fetched until task -> run -> project ownership has
 * been confirmed by real backend reads. A/B/A and adapter changes fail closed. */
export default function TaskSection(){
  const api=useMvpStore(state=>state.api);
  const projectId=useMvpStore(state=>state.projectId);
  const runId=useMvpStore(state=>state.runId);
  const taskId=useMvpStore(state=>state.taskId);
  const [refresh,setRefresh]=useState(0);
  const scopeRef=useRef({api,projectId,runId,taskId,refresh,revision:0});
  const old=scopeRef.current;
  if(old.api!==api||old.projectId!==projectId||old.runId!==runId||
     old.taskId!==taskId||old.refresh!==refresh){
    scopeRef.current={api,projectId,runId,taskId,refresh,revision:old.revision+1};
  }
  const scope=scopeRef.current;
  type Verified={scope:typeof scope;task:TaskResponse;run:RunResponse};
  const [proof,setProof]=useState<Verified|null>(null);
  const [failure,setFailure]=useState<{scope:typeof scope;message:string}|null>(null);
  const current=proof?.scope.revision===scope.revision &&
    proof.scope.api===api && proof.scope.projectId===projectId &&
    proof.scope.runId===runId && proof.scope.taskId===taskId ? proof:null;
  const error=failure?.scope.revision===scope.revision &&
    failure.scope.api===api && failure.scope.projectId===projectId &&
    failure.scope.runId===runId && failure.scope.taskId===taskId ? failure.message:null;
  useEffect(()=>{
    let active=true;
    if(!taskId)return ()=>{active=false;};
    void (async()=>{
      try{
        const task=await api.getTask(taskId);
        if(!task || task.id!==taskId || !task.workflow_run_id ||
           (runId && task.workflow_run_id!==runId))
          throw new Error('Task/run mismatch');
        if(!active)return;
        const run=await api.getRun(task.workflow_run_id);
        if(!run || run.id!==task.workflow_run_id ||
           (projectId && run.project_id!==projectId))
          throw new Error('Task/project mismatch');
        if(active)setProof({scope,task,run});
      }catch{
        if(active)setFailure({scope,message:
          'Принадлежность задачи текущему запуску и проекту не подтверждена. Обновите выбор.'});
      }
    })();
    return ()=>{active=false;};
  },[api,projectId,runId,taskId,refresh]); // eslint-disable-line react-hooks/exhaustive-deps
  if(!taskId)return <div><PageHeader title="Карточка задачи"
    subtitle="Откройте задачу с доски или из запусков."/><Card><p>Задача не выбрана.</p></Card></div>;
  if(!current)return <div><PageHeader title="Карточка задачи"
    subtitle="Сначала проверяется принадлежность задачи проекту и запуску."/>
    {error?<p role="alert" data-testid="task-scope-error">{error}</p>:
      <p role="status" data-testid="task-scope-loading">Проверяем серверные связи задачи…</p>}
    <button type="button" onClick={()=>setRefresh(i=>i+1)}>Повторить проверку</button>
  </div>;
  return <TaskContent key={scope.revision} api={api} taskId={taskId}
    verifiedTask={current.task} verifiedRun={current.run}
    refreshScope={()=>setRefresh(i=>i+1)}/>;
}

function TaskContent({taskId,api,verifiedTask,verifiedRun,refreshScope}:{
  taskId:string;api:ApiAdapter;verifiedTask:TaskResponse;verifiedRun:RunResponse;
  refreshScope:()=>void;
}) {
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

  function refreshAll(){refreshScope();}
  // A secondary task GET cannot override a previously verified ownership
  // chain. A mismatch hides the entire card until the next server refresh.
  const visibleTask = task.data?.id===taskId &&
    task.data.workflow_run_id===verifiedTask.workflow_run_id ? task.data:null;
  const attemptsValid=!attempts.loading&&!attempts.error &&
    Array.isArray(attempts.data) && attempts.data.every(item=>
      item?.task_id===taskId && typeof item.id==='string' && !!item.id);
  const safeAttempts=attemptsValid ? attempts.data! : [];
  const gitValid=!gitEvidence.loading&&!gitEvidence.error &&
    trustedTaskGitReports(gitEvidence.data,taskId);
  const safeGit=gitValid ? gitEvidence.data! : [];
  const qa=(!independentQa.loading&&!independentQa.error &&
    independentQa.data?.task_id===taskId) ? independentQa.data:null;
  // A receipt must describe the same completed attempt and worker-reported
  // commit as the independently read task evidence. Never promote a stale
  // or cross-attempt receipt based only on a 'verified' status field.
  const qaVerified=trustedTaskQa(qa,taskId) && attemptsValid && gitValid &&
    typeof qa?.attempt_id==='string' &&
    safeAttempts.some(attempt=>attempt.id===qa.attempt_id && attempt.status==='completed') &&
    safeGit.some(artifact=>artifact.attempt_id===qa.attempt_id &&
      artifact.commit_sha===qa.commit_sha);

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

      <p data-testid="task-run-verified" role="status">
        Принадлежность задачи запуску {verifiedRun.id} и проекту {verifiedRun.project_id}
        {' '}подтверждена сервером. Это не разрешение на выпуск.
      </p>
      {task.loading ? <p style={{ color: '#5b6472' }}>Загрузка…</p> : null}
      {task.error ? <p role="alert">Ошибка: {sanitizeTaskDisplayText(task.error.message)}</p> : null}
      {!task.loading && !task.error && !visibleTask ?
        <p role="alert">Сервер вернул другую задачу или запуск; детали скрыты.</p> : null}
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
                <strong style={{ fontSize: 16 }}>{sanitizeTaskDisplayText(visibleTask.title)}</strong>
                <StatusBadge status={visibleTask.status} />
              </div>
              {visibleTask.description ? (
                <p style={{ color: '#5b6472', fontSize: 13 }}>{sanitizeTaskDisplayText(visibleTask.description)}</p>
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
                    {stringifyTaskDisplayValue(visibleTask.input_data)}
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
                    {stringifyTaskDisplayValue(visibleTask.output_data)}
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
              {!gitEvidence.loading && !gitEvidence.error && gitValid && safeGit.length === 0
                ? <p>Подтверждённых Contract Gate Git-отчётов нет.</p> : null}
              {!gitEvidence.loading && !gitEvidence.error && !gitValid ?
                <p role="alert" data-testid="task-git-invalid">
                  Нельзя подтвердить принадлежность Git-отчётов задаче; артефакты скрыты.
                </p> : null}
              {safeGit.map(item => (
                <div key={item.attempt_id} data-testid="task-git-artifact">
                  <p style={{ fontSize: 12 }}>Источник: {item.provenance}</p>
                  <code style={{ overflowWrap: 'anywhere' }}>{item.commit_sha}</code>
                  <ul>{item.changed_paths.map(path => <li key={path}>{sanitizeTaskDisplayText(path)}</li>)}</ul>
                </div>
              ))}
            </Card>

            <Card title="Независимая QA">
              {independentQa.loading ? <p>Загрузка QA…</p> : null}
              {independentQa.error ? (
                <p role="alert">Ошибка чтения QA evidence: {sanitizeTaskDisplayText(independentQa.error.message)}</p>
              ) : null}
              {qa?.status === 'disabled' ? (
                <p data-testid="task-qa-status">Строгая независимая QA не включена для этого сервера.</p>
              ) : null}
              {qa?.status === 'pending' ? (
                <p data-testid="task-qa-status">
                  Ожидается независимая QA. Контракт и отчёт worker не заменяют tester/reviewer/security gates.
                </p>
              ) : null}
              {qa?.status === 'verified' && !qaVerified ?
                <p role="alert" data-testid="task-qa-invalid">
                  Нет достоверного подтверждения QA: проверьте Git SHA, task ID и независимые gates.
                </p> : null}
              {!independentQa.loading && !independentQa.error && !qa ?
                <p role="alert" data-testid="task-qa-invalid">
                  Подтверждение QA не принадлежит выбранной задаче или отсутствует.
                </p> : null}
              {qaVerified ? (
                <div data-testid="task-qa-status">
                  <p>QA подтверждена операторским подписанным свидетельством.</p>
                  <p style={{ overflowWrap: 'anywhere', fontSize: 12 }}>
                    Git SHA: <code>{qa!.commit_sha}</code>
                  </p>
                  <p style={{ fontSize: 12 }}>
                    Пройденные gates: tester · reviewer · security
                  </p>
                  <p style={{ fontSize: 12, color: '#5b6472' }}>
                    Подписант: {sanitizeTaskDisplayText(qa!.issued_by ?? '')}
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
                <p style={{ color: '#a3271c' }}>Ошибка: {sanitizeTaskDisplayText(attempts.error.message)}</p>
              ) : null}
              {!attempts.loading && !attempts.error && !attemptsValid ?
                <p role="alert" data-testid="task-attempts-invalid">
                  История попыток не соответствует выбранной задаче; записи скрыты.
                </p> : null}
              {!attempts.loading && !attempts.error && attemptsValid && safeAttempts.length === 0 ? (
                <p style={{ color: '#5b6472' }}>Попыток пока нет.</p>
              ) : null}
              <ul style={{ listStyle: 'none', margin: 0, padding: 0 }}>
                {safeAttempts.map((attempt) => (
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
                        {sanitizeTaskDisplayText(attempt.error)}
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
                        {stringifyTaskDisplayValue(attempt.output_data)}
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
                onClick={() => {
                  const id = visibleTask!.id;
                  selectRun(visibleTask!.workflow_run_id);
                  selectTask(id);
                  setSection('recovery');
                }} style={{padding:10}}>
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

