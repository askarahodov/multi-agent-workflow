/**
 * Run-centric execution UX. Product launches come from immutable published
 * workflow snapshots, never an ad-hoc task list that bypasses graph validation.
 */
import { useEffect, useState } from 'react';
import { sanitizeTaskDisplayText } from '../../api/taskDisplayRedaction';

import type { RunResponse, TaskResponse, WorkflowDefinitionDTO, WorkflowVersionDTO, PublishedRunPreflight } from '../../api/types';
import { useMvpStore } from '../mvpStore';
import { useAsync } from '../useAsync';
import { Card, formatDate, PageHeader, StatusBadge } from '../ui';

async function allPages<T>(
  load: (after?: string) => Promise<{ items: T[]; next_cursor?: string | null }>,
): Promise<T[]> {
  const values: T[] = [];
  const seen = new Set<string>();
  let after: string | undefined;
  for (let page = 0; page < 100; page++) {
    const response = await load(after);
    values.push(...response.items);
    if (!response.next_cursor) return values;
    if (seen.has(response.next_cursor)) throw new Error('Сервер повторяет курсор списка');
    seen.add(response.next_cursor);
    after = response.next_cursor;
  }
  throw new Error('Превышен предел страниц списка');
}

export default function RunsSection() {
  const api = useMvpStore((s) => s.api);
  const projectId = useMvpStore((s) => s.projectId);
  const runId = useMvpStore((s) => s.runId);
  const selectRun = useMvpStore((s) => s.selectRun);
  const selectTask = useMvpStore((s) => s.selectTask);
  const setSection = useMvpStore((s) => s.setSection);
  const [definitionId, setDefinitionId] = useState('');
  const [versionId, setVersionId] = useState('');
  const [launching, setLaunching] = useState(false);
  const [launchError, setLaunchError] = useState('');
  const [notice, setNotice] = useState('');
  const [preflight, setPreflight] = useState<PublishedRunPreflight | null>(null);
  const [checking, setChecking] = useState(false);

  const definitions = useAsync<WorkflowDefinitionDTO[]>(() =>
    allPages((after) => api.listWorkflows({ after, limit: 100 })));
  const versions = useAsync<WorkflowVersionDTO[]>(() =>
    definitionId ? allPages((after) => api.listVersions(definitionId, { after, limit: 100 })) : Promise.resolve([]));
  const runs = useAsync<RunResponse[]>(() =>
    allPages((after) => api.listRuns({ projectId: projectId ?? undefined, after, limit: 100 })));
  const selectedRun = useAsync<RunResponse | null>(() =>
    useMvpStore.getState().runId ? api.getRun(useMvpStore.getState().runId!) : Promise.resolve(null));
  const tasks = useAsync<TaskResponse[]>(() =>
    useMvpStore.getState().runId
      ? allPages((after) => api.listRunTasks(useMvpStore.getState().runId!, { after, limit: 100 }))
      : Promise.resolve([]));

  useEffect(() => { definitions.reload(); runs.reload(); }, [api, projectId]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    setDefinitionId('');
    setVersionId('');
    setLaunchError('');
    setPreflight(null);
  }, [projectId]);
  useEffect(() => {
    setVersionId('');
    setPreflight(null);
    versions.reload();
  }, [definitionId]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    selectedRun.reload();
    tasks.reload();
  }, [runId]); // eslint-disable-line react-hooks/exhaustive-deps

  const availableDefinitions = (definitions.data ?? [])
    .filter((entry) => entry.is_active && (!entry.project_id || entry.project_id === projectId));
  const selectedDefinition = availableDefinitions.find((entry) => entry.id === definitionId);
  const selectedVersion = (versions.data ?? []).find((entry) => entry.id === versionId);
  const canLaunch = Boolean(projectId && selectedDefinition && selectedVersion && !launching && !checking &&
    preflight?.can_create_run && preflight.workflow_definition_id === definitionId &&
    preflight.workflow_version_id === versionId);

  async function checkPreflight() {
    if (!projectId || !selectedDefinition || !selectedVersion || checking) return;
    setChecking(true);
    setPreflight(null);
    setLaunchError('');
    try {
      const report = await api.preflightPublishedRun(selectedDefinition.id, selectedVersion.id, projectId);
      setPreflight(report);
    } catch (cause) {
      setLaunchError(cause instanceof Error ? cause.message : String(cause));
    } finally {
      setChecking(false);
    }
  }

  async function launchPublished() {
    if (!projectId || !selectedDefinition || !selectedVersion || launching) {
      setLaunchError('Выберите проект, workflow и опубликованную версию.');
      return;
    }
    // Re-fetch on every launch; a previous positive report is not a durable
    // authorization or evidence that contracts are still present.
    setLaunching(true);
    setLaunchError('');
    setNotice('');
    try {
      const current = await api.preflightPublishedRun(selectedDefinition.id, selectedVersion.id, projectId);
      setPreflight(current);
      if (!current.can_create_run) {
        setLaunchError('Серверный preflight заблокировал запуск. Исправьте ошибки.');
        return;
      }
      if (!window.confirm(
        'Создать запуск версии №' + selectedVersion.version_number + ' workflow «' + selectedDefinition.name +
        '»? Preflight не подтверждает наличие live worker, доступность модели, бюджет и разрешение выпуска. ' +
        'При включённом worker возможны платные AI-запросы. Продолжить?',
      )) return;
      const result = await api.launchPublishedRun(selectedDefinition.id, selectedVersion.id, {
        project_id: projectId,
        name: selectedVersion.definition_snapshot.metadata.name,
      });
      selectRun(result.id);
      await Promise.all([api.getRun(result.id), api.listRunTasks(result.id)]);
      runs.reload();
      selectedRun.reload();
      tasks.reload();
      setNotice('Создан запуск опубликованной версии №' + selectedVersion.version_number);
    } catch (cause) {
      setLaunchError(cause instanceof Error ? cause.message : String(cause));
    } finally {
      setLaunching(false);
    }
  }

  function refreshAll() {
    runs.reload();
    selectedRun.reload();
    tasks.reload();
  }

  // useAsync retains its previous result while the next request loads.
  // Never display a different run/project's details or tasks in the new scope.
  const visibleRuns = (runs.data ?? []).filter((item) =>
    !projectId || item.project_id === projectId);
  const run = selectedRun.data?.id === runId &&
    (!projectId || selectedRun.data.project_id === projectId) ? selectedRun.data : null;
  const visibleTasks = run
    ? (tasks.data ?? []).filter((task) => task.workflow_run_id === run.id)
    : [];
  const input = run?.input_data ?? {};
  const sourceVersion = typeof input._workflow_version_id === 'string' ? input._workflow_version_id : null;
  const sourceDefinition = typeof input._workflow_definition_id === 'string' ? input._workflow_definition_id : null;

  return (
    <div>
      <PageHeader title="Запуски и результаты"
        subtitle="Запускайте только опубликованные версии из редактора. История задач и журнал принадлежат серверному запуску." />
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(min(100%, 330px), 1fr))', gap: 16, alignItems: 'start' }}>
        <div>
          <Card title={projectId ? 'Запуски проекта' : 'Запуски — сначала выберите проект'}>
            <button type="button" onClick={refreshAll} data-testid="runs-refresh">Обновить</button>
            {runs.loading ? <p>Загрузка…</p> : null}
            {runs.error ? <p role="alert">{sanitizeTaskDisplayText(runs.error.message)}</p> : null}
            {!runs.loading && !runs.error && !visibleRuns.length ? <p>Запусков пока нет. Опубликуйте граф в редакторе.</p> : null}
            <ul style={{ listStyle: 'none', margin: 0, padding: 0 }}>
              {visibleRuns.map((entry) => (
                <li key={entry.id} style={{ margin: '8px 0' }}>
                  <button type="button" onClick={() => {
                    if (entry.id === runId) refreshAll();
                    else selectRun(entry.id);
                  }}
                    aria-pressed={runId === entry.id} data-testid={'select-run-' + entry.id}
                    style={{ width: '100%', textAlign: 'left', padding: 10, border: '1px solid #c8ced6', borderRadius: 6 }}>
                    <strong>{sanitizeTaskDisplayText(entry.name)}</strong> · <StatusBadge status={entry.status} />
                    <div style={{ fontSize: 12 }}>{formatDate(entry.started_at ?? entry.created_at)}</div>
                  </button>
                </li>
              ))}
            </ul>
          </Card>
        </div>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
          <Card title="Запустить опубликованный workflow">
            <p style={{ fontSize: 13 }}>Новый процесс создаётся в редакторе. Сохраните черновик, опубликуйте неизменяемую версию, затем запускайте её здесь.</p>
            <button type="button" data-testid="runs-open-editor" onClick={() => setSection('editor')}>
              Открыть редактор
            </button>
            {!projectId ? <p role="status">Выберите проект в разделе «Проект».</p> : null}
            {definitions.error ? <p role="alert">{sanitizeTaskDisplayText(definitions.error.message)}</p> : null}
            <label style={{ display: 'block', marginTop: 12 }}>
              Workflow
              <select data-testid="runs-definition-select" value={definitionId}
                onChange={(e) => setDefinitionId(e.target.value)} disabled={!projectId || launching || definitions.loading}
                style={{ display: 'block', width: '100%' }}>
                <option value="">Выберите опубликованный workflow</option>
                {availableDefinitions.map((entry) => <option value={entry.id} key={entry.id}>{sanitizeTaskDisplayText(entry.name)}</option>)}
              </select>
            </label>
            {projectId && !definitions.loading && !availableDefinitions.length ?
              <p>Для выбранного проекта нет доступных workflow. Создайте и опубликуйте граф в редакторе.</p> : null}
            <label style={{ display: 'block', marginTop: 12 }}>
              Неизменяемая версия
              <select data-testid="runs-version-select" value={versionId}
                onChange={(e) => { setVersionId(e.target.value); setPreflight(null); }}
                disabled={!definitionId || versions.loading || launching}
                style={{ display: 'block', width: '100%' }}>
                <option value="">Выберите версию</option>
                {(versions.data ?? []).map((item) => (
                  <option key={item.id} value={item.id}>№{item.version_number} · {formatDate(item.created_at)}</option>
                ))}
              </select>
            </label>
            {definitionId && !versions.loading && !versions.error && !versions.data?.length ?
              <p role="status">Нет опубликованных версий. Сначала опубликуйте граф.</p> : null}
            {versions.error ? <p role="alert">{sanitizeTaskDisplayText(versions.error.message)}</p> : null}
            <p style={{ fontSize: 12 }}>Запуск проверяет сохранённую версию на сервере. Права, Contract Gate и QA не отключаются. Отсутствие worker или профиля не означает готовность к исполнению.</p>
            <button type="button" data-testid="runs-check-preflight"
              disabled={!projectId || !selectedDefinition || !selectedVersion || checking || launching}
              onClick={() => { void checkPreflight(); }}>
              {checking ? 'Проверка…' : 'Проверить готовность запуска'}
            </button>
            {preflight ? <section data-testid="runs-preflight" aria-label="Серверный preflight">
              <p role="status">{preflight.can_create_run ?
                'Серверные проверки допускают создание запуска. Это НЕ подтверждает готовность live worker и платного провайдера.' :
                'Создание запуска заблокировано серверными проверками.'}</p>
              <p>Компилируемых задач: {preflight.task_count}. Реальное исполнение: {preflight.execution_ready ?
                'подтверждено' : 'не подтверждено'}.</p>
              <ul>{preflight.checks.map(check => <li key={check.code}>
                <strong>{check.status === 'pass' ? 'Проверено' : check.status === 'block' ? 'Блокирует' : 'Не проверено'}:</strong>
                {' '}{check.code} — {sanitizeTaskDisplayText(check.detail)}
              </li>)}</ul>
            </section> : null}
            {launchError ? <p role="alert">{sanitizeTaskDisplayText(launchError)}</p> : null}
            {notice ? <p role="status">{sanitizeTaskDisplayText(notice)}</p> : null}
            <button type="button" data-testid="runs-launch-published"
              disabled={!canLaunch} onClick={() => { void launchPublished(); }}>
              {launching ? 'Запуск…' : 'Запустить опубликованную версию'}
            </button>
          </Card>
          {runId ? (
            <Card title="Детали выбранного запуска">
              {selectedRun.loading ? <p>Загрузка…</p> : null}
              {selectedRun.error ? <p role="alert">{sanitizeTaskDisplayText(selectedRun.error.message)}</p> : null}
              {run ? (
                <div>
                  <strong>{sanitizeTaskDisplayText(run.name)}</strong> · <StatusBadge status={run.status} />
                  <dl style={{ fontSize: 12 }}>
                    <dt>Запуск</dt><dd style={{ overflowWrap: 'anywhere' }}>{run.id}</dd>
                    <dt>Проект</dt><dd>{run.project_id}</dd>
                    <dt>Источник</dt><dd>{sourceVersion ?
                      'Опубликованный граф: ' + sourceDefinition + ' / ' + sourceVersion :
                      'Исторический или ручной запуск (без подтверждённой опубликованной версии)'}</dd>
                    <dt>Начало</dt><dd>{formatDate(run.started_at ?? run.created_at)}</dd>
                    <dt>Завершение</dt><dd>{formatDate(run.completed_at)}</dd>
                  </dl>
                  <button type="button" data-testid="runs-open-log"
                    onClick={() => setSection('agent-log')}>Открыть живой журнал</button>
                  <button type="button" data-testid="runs-open-recovery"
                    onClick={() => setSection('recovery')}>Восстановление / карантин</button>
                  {tasks.loading ? <p>Загрузка задач…</p> : null}
                  {tasks.error ? <p role="alert">{sanitizeTaskDisplayText(tasks.error.message)}</p> : null}
                  <ul style={{ listStyle: 'none', padding: 0 }}>
                    {visibleTasks.map((task) => (
                      <li key={task.id} style={{ margin: '8px 0' }}>
                        <button type="button" data-testid={'run-task-' + task.id}
                          onClick={() => { selectTask(task.id); setSection('task'); }}>
                          {sanitizeTaskDisplayText(task.title)} · <StatusBadge status={task.status} />
                        </button>
                      </li>
                    ))}
                  </ul>
                </div>
              ) : null}
            </Card>
          ) : null}
        </div>
      </div>
    </div>
  );
}
