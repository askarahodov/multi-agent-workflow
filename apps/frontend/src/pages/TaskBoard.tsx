/** Project-scoped, read-only view of server-owned task state. No client-side moves. */
import { useCallback, useEffect, useMemo, useState } from 'react';
import type { ApiAdapter, CursorPage, ProjectResponse, RunResponse, TaskResponse } from '../api/types';
import { useMvpStore } from '../mvp/mvpStore';
import { Button, Card, Input, Select } from '../components';
import { PageHeader } from '../patterns';

/** Explicitly bounded pagination: never silently show a truncated board as complete. */
export async function collectPages<T>(
  list: (after?: string) => Promise<CursorPage<T>>,
  maxPages = 100,
): Promise<T[]> {
  const rows: T[] = [];
  const seen = new Set<string>();
  let after: string | undefined;
  for (let i = 0; i < maxPages; i += 1) {
    const page = await list(after);
    if (!Array.isArray(page.items)) throw new Error('Сервер вернул некорректную страницу');
    rows.push(...page.items);
    if (!page.next_cursor) return rows;
    if (seen.has(page.next_cursor)) throw new Error('Сервер вернул повторяющийся курсор');
    seen.add(page.next_cursor);
    after = page.next_cursor;
  }
  throw new Error('Превышен предел страниц. Уточните фильтры и повторите загрузку.');
}

export async function loadProjectBoard(api: ApiAdapter, projectId: string | null): Promise<{
  runs: RunResponse[]; tasks: TaskResponse[];
}> {
  // Query the authoritative run list; filter by project ID *before* requesting
  // tasks, including when the API adapter ignores project query parameters.
  const allRuns = await collectPages((after) => api.listRuns({ after, limit: 100, ...(projectId ? {projectId} : {}) }));
  const runs = projectId ? allRuns.filter((run) => run.project_id === projectId) : allRuns;
  const tasks: TaskResponse[] = [];
  // Sequential requests bound fan-out. Each task must belong to the run just
  // requested; no cross-project leakage even on a faulty backend response.
  for (const run of runs) {
    const pageTasks = await collectPages((after) => api.listRunTasks(run.id, {after,limit:100}));
    if (pageTasks.some((task) => task.workflow_run_id !== run.id)) {
      throw new Error('Неконсистентные данные: задача принадлежит другому запуску');
    }
    tasks.push(...pageTasks);
  }
  return {runs,tasks};
}

const COLUMNS = [
  {id:'pending', title:'Ожидает'},
  {id:'in_progress', title:'В работе'},
  {id:'qa', title:'Независимая проверка'},
  {id:'approval', title:'Согласование'},
  {id:'blocked', title:'Заблокировано'},
  {id:'quarantine', title:'Карантин / восстановление'},
  {id:'completed', title:'Завершено'},
  {id:'failed', title:'Ошибка'},
  {id:'other', title:'Другие статусы'},
] as const;
type ColumnId = typeof COLUMNS[number]['id'];
export function statusColumn(status: string): ColumnId {
  if (status === 'pending' || status === 'ready') return 'pending';
  if (status === 'in_progress' || status === 'claimed' || status === 'running') return 'in_progress';
  if (status.includes('qa') || status.includes('review') || status.includes('verification')) return 'qa';
  if (status.includes('approval') || status.includes('human')) return 'approval';
  if (status.includes('quarantine') || status.includes('recovery') || status.includes('interrupted')) return 'quarantine';
  if (status === 'blocked') return 'blocked';
  if (status === 'completed') return 'completed';
  if (status === 'failed') return 'failed';
  return 'other'; // never manufacture an in-progress signal for unknown states
}

export default function TaskBoard() {
  const api = useMvpStore((s) => s.api);
  const projectId = useMvpStore((s) => s.projectId);
  const selectProject = useMvpStore((s) => s.selectProject);
  const runId = useMvpStore((s) => s.runId);
  const selectRun = useMvpStore((s) => s.selectRun);
  const selectTask = useMvpStore((s) => s.selectTask);
  const setSection = useMvpStore((s) => s.setSection);
  const [projects, setProjects] = useState<ProjectResponse[]>([]);
  const [runs, setRuns] = useState<RunResponse[]>([]);
  const [tasks, setTasks] = useState<TaskResponse[]>([]);
  const [filter, setFilter] = useState('');
  const [statusFilter, setStatusFilter] = useState('');
  const [refreshKey, setRefreshKey] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const refresh = useCallback(() => setRefreshKey((value) => value+1), []);

  useEffect(() => {
    let active = true;
    setLoading(true);
    setError(null);
    // Clear stale tasks immediately, not only when fresh results arrive.
    setTasks([]); setRuns([]);
    Promise.all([api.listProjects(),loadProjectBoard(api,projectId)])
      .then(([newProjects,result]) => {
        if (!active) return;
        setProjects(newProjects);
        setRuns(result.runs);
        setTasks(result.tasks);
      }).catch((reason: unknown) => {
        if (active) setError(reason instanceof Error ? reason.message : 'Не удалось загрузить доску');
      }).finally(() => {if (active) setLoading(false);});
    return () => {active=false;};
  }, [api,projectId,refreshKey]);

  // Invalid/stale focused run must not override a project's isolation.
  const effectiveRunId = runId && runs.some((run) => run.id === runId) ? runId : null;
  const runsById = useMemo(() => new Map(runs.map((run) => [run.id,run])),[runs]);
  const visible = useMemo(() => tasks.filter((task) => {
    const run = runsById.get(task.workflow_run_id);
    if (!run || (projectId && run.project_id !== projectId)) return false;
    if (effectiveRunId && run.id !== effectiveRunId) return false;
    if (statusFilter && statusColumn(task.status) !== statusFilter) return false;
    const needle = filter.trim().toLowerCase();
    return !needle || [task.title,task.id,task.node_id ?? '',task.assigned_agent_id ?? '',run.name]
      .some((item) => item.toLowerCase().includes(needle));
  }),[tasks,runsById,projectId,effectiveRunId,statusFilter,filter]);
  const buckets = useMemo(() => {
    const result = {} as Record<ColumnId, TaskResponse[]>;
    for (const column of COLUMNS) result[column.id] = [];
    for (const task of visible) result[statusColumn(task.status)].push(task);
    return result;
  },[visible]);
  function openTask(task:TaskResponse) {
    selectRun(task.workflow_run_id);
    selectTask(task.id);
    setSection('task');
  }
  return <div>
    <PageHeader title="Kanban-доска" subtitle="Жизненный цикл серверных задач. Статусы меняет оркестратор, а не перетаскивание карточек."
      breadcrumbs={[{label:'Платформа'},{label:'Kanban-доска'}]}/>
    <p>Это доска задач пользовательских запусков, не локальный Hermes Kanban. Для изменения состояния откройте карточку задачи и используйте разрешённые сервером действия.</p>
    <div style={{display:'flex',gap:12,flexWrap:'wrap',alignItems:'center',marginBottom:16}}>
      <label htmlFor="board-project-filter">Проект</label>
      <Select id="board-project-filter" data-testid="board-project-filter" value={projectId??''}
        onChange={(event)=>{selectProject(event.target.value||null);selectRun(null);}}
        style={{maxWidth:240,marginBlockEnd:0}}>
        <option value="">Все проекты</option>
        {projects.map((project)=><option key={project.id} value={project.id}>{project.name}</option>)}
      </Select>
      <label htmlFor="board-run-filter">Запуск</label>
      <Select id="board-run-filter" data-testid="board-run-filter" value={effectiveRunId??''}
        onChange={(event)=>selectRun(event.target.value||null)}
        style={{maxWidth:260,marginBlockEnd:0}}>
        <option value="">Все запуски проекта</option>
        {runs.map((run)=><option key={run.id} value={run.id}>{run.name}</option>)}
      </Select>
      <label htmlFor="board-status-filter">Статус</label>
      <Select id="board-status-filter" value={statusFilter}
        onChange={(event)=>setStatusFilter(event.target.value)} style={{maxWidth:200,marginBlockEnd:0}}>
        <option value="">Все статусы</option>
        {COLUMNS.map((col)=><option key={col.id} value={col.id}>{col.title}</option>)}
      </Select>
      <label htmlFor="board-search">Поиск</label>
      <Input id="board-search" value={filter} onChange={(event)=>setFilter(event.target.value)}
        placeholder="Задача, агент, стадия…" style={{maxWidth:220,marginBlockEnd:0}}/>
      <Button variant="secondary" disabled={loading} onClick={refresh}>Обновить</Button>
    </div>
    {loading ? <p role="status">Загрузка всех страниц запусков и задач…</p> : null}
    {error ? <div role="alert"><p>{error}</p><Button onClick={refresh}>Повторить</Button></div> : null}
    {!loading && !error ? <>
      <p role="status">Найдено задач: {visible.length}. Запусков в области: {runs.length}.</p>
      {!visible.length ? <p>Задач по выбранным фильтрам нет. Создайте запуск или измените фильтры.</p> : null}
      <div style={{display:'grid',gridTemplateColumns:'repeat(auto-fit,minmax(220px,1fr))',gap:12,alignItems:'start'}}>
        {COLUMNS.map((column)=><Card key={column.id} title={<span>{column.title} ({buckets[column.id].length})</span>}>
          {buckets[column.id].length === 0 ? <p>Пусто</p> :
          <ul style={{margin:0,padding:0,listStyle:'none',display:'grid',gap:8}}>
            {buckets[column.id].map((task)=><li key={task.id}>
              <button type="button" data-testid={`board-task-${column.id}-${task.id}`}
                onClick={()=>openTask(task)} style={{width:'100%',textAlign:'left',padding:10,
                  border:'1px solid var(--color-border)',background:'var(--color-surface)',borderRadius:6}}>
                <strong>{task.title}</strong>
                <span style={{display:'block',fontSize:12}}>Запуск: {runsById.get(task.workflow_run_id)?.name}</span>
                <span style={{display:'block',fontSize:12}}>Статус API: {task.status}</span>
                {task.node_id ? <span style={{display:'block',fontSize:12}}>Стадия: {task.node_id}</span> : null}
                {task.assigned_agent_id ? <span style={{display:'block',fontSize:12}}>Агент: {task.assigned_agent_id}</span> : null}
                <span style={{display:'block',fontSize:12}}>Попытки: {task.attempt_count}/{task.max_attempts}</span>
                <span style={{display:'block',fontSize:11}}>Открыть карточку и подтверждённые QA/Git-сведения</span>
              </button>
            </li>)}
          </ul>}
        </Card>)}
      </div>
    </> : null}
  </div>;
}
