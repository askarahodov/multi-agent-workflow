/**
 * Agent monitor layout (live agent log, ADR-110 §3.6, ADR-106).
 *
 * Design-system implementation of the "Живой журнал" section. It consumes the
 * run-scoped **WebSocket** event stream (with an automatic SSE fallback and a
 * poll-snapshot fallback when no streaming transport is available) so task
 * boards, agent logs and gate statuses update as transitions happen.
 *
 * The pure `diffToEvents` / `snapshotToKey` helpers are kept (and exported for
 * unit tests) for the degraded polling path; `sagaEventToLogEvent` maps the
 * streamed saga events into the same `RunLogEvent` shape.
 *
 * The feed is a polite live region so streamed updates are announced to
 * assistive tech (ADR-110 §3.3 rule 3).
 */

import { useEffect, useRef, useState } from 'react';

import type { ApiAdapter, RunLogEvent, RunResponse } from '../../api/types';
import { DEFAULT_BASE_URL, RunEventStream, StreamAuthenticationError, type StreamStatus } from '../../api/client';
import { sanitizeRunLogText } from '../../api/runStream';
import { sanitizeTaskDisplayText } from '../../api/taskDisplayRedaction';
import { useMvpStore } from '../../mvp/mvpStore';
import { Button, Card, Select, StatusBadge, type StatusTone } from '../../components';
import { EmptyState } from '../../components/EmptyState';
import { PageHeader } from '../../patterns';

const POLL_MS = 2000;
const MAX_VISIBLE_EVENTS = 500;
const MAX_RUN_CATALOG_PAGES = 100;

// A run on a later cursor page must remain selectable from the journal.
// Failure/cyclic pagination is not a successful empty list. This is a client
// discovery safeguard; server auth still determines who may read each run.
async function loadRunCatalog(api:ApiAdapter,projectId:string|null):Promise<RunResponse[]> {
  const results:RunResponse[]=[];
  const cursors=new Set<string>();
  let after:string|undefined;
  for(let page=0;page<MAX_RUN_CATALOG_PAGES;page++){
    const batch=await api.listRuns({projectId:projectId??undefined,after,limit:100});
    if(!Array.isArray(batch.items) || batch.items.length>100 ||
       batch.items.some(run=>!run || typeof run.id!=='string' || typeof run.project_id!=='string'))
      throw new Error('Некорректная страница каталога запусков');
    results.push(...batch.items);
    if(batch.next_cursor==null) return results;
    if(typeof batch.next_cursor!=='string' || !batch.next_cursor ||
       !batch.items.length || cursors.has(batch.next_cursor))
      throw new Error('Некорректный курсор каталога запусков');
    cursors.add(batch.next_cursor);
    after=batch.next_cursor;
  }
  throw new Error('Превышен предел страниц каталога запусков');
}

interface CatalogRead {
  api:ApiAdapter;projectId:string|null;items:RunResponse[]|null;error:string|null;
}

type MonitorEvent = RunLogEvent & { source: 'stream' | 'snapshot' };

function appendEvents(current: MonitorEvent[], incoming: MonitorEvent[]): MonitorEvent[] {
  const known = new Set(current.map(item => item.id));
  const additions = incoming.filter(item => !known.has(item.id));
  return [...current, ...additions].slice(-MAX_VISIBLE_EVENTS);
}

/** True when the runtime exposes a streaming transport (browsers do). */
export function hasStreamingTransport(): boolean {
  return (
    typeof globalThis.WebSocket !== 'undefined' || typeof globalThis.EventSource !== 'undefined'
  );
}

/** Diff two snapshots into new log events (pure; unit-tested). */
export function diffToEvents(
  previous: ReturnType<typeof snapshotToKey> | null,
  current: ReturnType<typeof snapshotToKey>,
  runName: string,
): RunLogEvent[] {
  const events: RunLogEvent[] = [];
  const now = new Date().toISOString();
  const run = current.run;
  const prevRun = previous?.run;

  if (!prevRun || prevRun.status !== run.status) {
    const level =
      run.status === 'completed' ? 'success' : run.status === 'failed' ? 'error' : 'info';
    events.push({
      id: `run-${run.id}-${new Date().getTime()}`,
      at: now,
      kind: 'run',
      level,
      message: sanitizeRunLogText(`run "${runName}" → ${run.status}`),
      run_id: run.id,
    });
  }

  const prevTasks = new Map((previous?.tasks ?? []).map((t) => [t.id, t.status]));
  for (const task of current.tasks) {
    const prevStatus = prevTasks.get(task.id);
    if (prevStatus === undefined || prevStatus !== task.status) {
      const level =
        task.status === 'completed'
          ? 'success'
          : task.status === 'failed'
            ? 'error'
            : task.status === 'blocked'
              ? 'warn'
              : 'info';
      events.push({
        id: `task-${task.id}-${new Date().getTime()}`,
        at: now,
        kind: 'task',
        level,
        message: sanitizeRunLogText(`task "${task.title}" → ${task.status}`),
        run_id: run.id,
        task_id: task.id,
      });
    }
  }
  return events;
}

interface SnapshotKey {
  run: { id: string; status: string };
  tasks: Array<{ id: string; title: string; status: string }>;
}

/** Stable key describing a snapshot's observable state. */
export function snapshotToKey(snapshot: {
  run: { id: string; status: string };
  tasks: Array<{ id: string; title: string; status: string }>;
}): SnapshotKey {
  return {
    run: { id: snapshot.run.id, status: snapshot.run.status },
    tasks: snapshot.tasks.map((t) => ({ id: t.id, title: t.title, status: t.status })),
  };
}

function levelColour(level: RunLogEvent['level']): string {
  switch (level) {
    case 'error':
      return 'var(--color-error)';
    case 'warn':
      return 'var(--color-warn)';
    case 'success':
      return 'var(--color-success)';
    default:
      return 'var(--color-primary)';
  }
}

/** Human label + tone for the stream connection badge (text, not colour alone). */
function statusLabel(status: StreamStatus): { label: string; tone: StatusTone } {
  switch (status) {
    case 'open':
      return { label: 'В реальном времени', tone: 'success' };
    case 'connecting':
      return { label: 'Подключение…', tone: 'info' };
    case 'reconnecting':
      return { label: 'Переподключение…', tone: 'warn' };
    case 'closed':
      return { label: 'Поток закрыт', tone: 'error' };
    default:
      return { label: 'Ожидание', tone: 'info' };
  }
}

export default function AgentMonitor() {
  const api = useMvpStore((s) => s.api);
  const runId = useMvpStore((s) => s.runId);
  const projectId = useMvpStore((s) => s.projectId);
  const [catalog, setCatalog] = useState<CatalogRead|null>(null);
  useEffect(()=>{
    let active=true;
    void loadRunCatalog(api,projectId).then(items=>{
      if(active) setCatalog({api,projectId,items,error:null});
    },(cause:unknown)=>{
      if(active) setCatalog({api,projectId,items:null,error:
        sanitizeTaskDisplayText(cause instanceof Error ? cause.message : 'Каталог недоступен')});
    });
    return ()=>{active=false;};
  },[api,projectId]);
  // Both adapter identity and project ownership are part of the read scope.
  // A stale response may still be in React state, but it cannot authorize a
  // stream for a new project or briefly show an old catalog.
  const currentCatalog=catalog?.api===api && catalog.projectId===projectId ? catalog:null;
  const visibleRuns=(currentCatalog?.items??[]).filter(run=>
    !projectId || run.project_id===projectId);
  const runIsInProject=!projectId || visibleRuns.some(run=>run.id===runId);

  const [events, setEvents] = useState<MonitorEvent[]>([]);
  const [levelFilter, setLevelFilter] = useState<'all' | RunLogEvent['level']>('all');
  const [taskFilter, setTaskFilter] = useState('');
  const [restartKey, setRestartKey] = useState(0);
  const [paused, setPaused] = useState(false);
  const [pollError, setPollError] = useState<string | null>(null);
  const [streamStatus, setStreamStatus] = useState<StreamStatus>('idle');
  // Live mode: the WebSocket/SSE stream when available, else snapshot polling.
  const [mode, setMode] = useState<'stream' | 'polling'>(() =>
    hasStreamingTransport() ? 'stream' : 'polling',
  );
  const previousKey = useRef<ReturnType<typeof snapshotToKey> | null>(null);
  const streamCursor = useRef(0);
  const currentScopeRef=useRef({api,projectId,runId});
  const pausedRef = useRef(false);
  pausedRef.current = paused;

  if (currentScopeRef.current.api!==api ||
      currentScopeRef.current.projectId!==projectId ||
      currentScopeRef.current.runId!==runId) {
    currentScopeRef.current={api,projectId,runId};
    setEvents([]);
    setPollError(null);
    setTaskFilter('');
    setStreamStatus('idle');
    setMode(hasStreamingTransport() ? 'stream' : 'polling');
    previousKey.current = null;
    streamCursor.current = 0;
  }

  /* -------- Primary path: WebSocket (SSE fallback) live event stream -------- */
  useEffect(() => {
    if (!runId || !runIsInProject || mode !== 'stream' || paused) return;
    const targetRunId = runId;
    let authorizationRejected = false;
    const stream = new RunEventStream(targetRunId, {
      baseUrl: DEFAULT_BASE_URL,
      afterEventId: streamCursor.current,
      streamTickets: import.meta.env.VITE_STREAM_TICKETS_ENABLED === '1',
      ticketProvider: (transport) => api.issueStreamTicket(targetRunId, transport),
    });
    stream.subscribe({
      onEvent: (event) => {
        // On pause do not advance the journal's persisted resume cursor.
        // Cleanup stops the old transport and resumption opens from the last
        // *displayed* event, allowing server replay of the paused interval.
        if(pausedRef.current || useMvpStore.getState().runId!==targetRunId ||
           useMvpStore.getState().projectId!==projectId ||
           useMvpStore.getState().api!==api) return;
        streamCursor.current = stream.getLastEventId();
        setEvents((existing) => appendEvents(existing, [{
          ...event, message: sanitizeRunLogText(event.message), source: 'stream',
        }]));
      },
      onStatus: (status) => {
        setStreamStatus(status);
        if (status === 'open') setPollError(null);
        // A stream that gave up (no transport / retries exhausted) degrades to
        // snapshot polling rather than showing a dead feed.
        if (status === 'closed' && !authorizationRejected && !pausedRef.current) setMode('polling');
      },
      onError: (error) => {
        if (error instanceof StreamAuthenticationError) authorizationRejected = true;
        setPollError(sanitizeRunLogText(error.message));
      },
    });
    stream.start();
    return () => stream.stop();
  }, [runId, mode, api, restartKey, projectId, runIsInProject, paused]);

  /* -------- Fallback path: snapshot polling (no streaming transport) -------- */
  useEffect(() => {
    if (!runId || !runIsInProject || mode !== 'polling') return;
    const targetRunId = runId;
    let mounted = true;
    let inFlight=false;

    async function poll() {
      // No concurrent snapshots: a slow earlier GET must never overwrite
      // the more recent state or generate an event from a regressed status.
      if (pausedRef.current || inFlight) return;
      inFlight=true;
      try {
        const snapshot = await api.getRunSnapshot(targetRunId);
        if (!mounted) return;
        const name = visibleRuns.find((r) => r.id === targetRunId)?.name ?? targetRunId;
        const key = snapshotToKey(snapshot);
        const next = diffToEvents(previousKey.current, key, name);
        if (next.length > 0) {
          setEvents((existing) => appendEvents(existing, next.map(event => ({
            ...event, message: sanitizeRunLogText(event.message), source: 'snapshot' as const,
          }))));
        }
        previousKey.current = key;
        setPollError(null);
      } catch (error) {
        if (mounted) setPollError(sanitizeRunLogText(error instanceof Error ? error.message : String(error)));
      } finally {inFlight=false;}
    }

    void poll();
    const timer = setInterval(poll, POLL_MS);
    return () => {
      mounted = false;
      clearInterval(timer);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [api, projectId, runId, runIsInProject, mode, paused]);

  // A retained selection must never silently reappear when its task was
  // cleared or evicted by the bounded event history.
  useEffect(() => {
    if (taskFilter && !events.some(event => event.task_id === taskFilter)) {
      setTaskFilter('');
    }
  }, [events, taskFilter]);

  const taskIds = [...new Set(events.map(event => event.task_id).filter(
    (id): id is string => typeof id === 'string' && id.length > 0,
  ))];
  const effectiveTaskFilter = taskIds.includes(taskFilter) ? taskFilter : '';
  const visibleEvents = events.filter((event) =>
    (levelFilter === 'all' || event.level === levelFilter) &&
    (!effectiveTaskFilter || event.task_id === effectiveTaskFilter),
  );

  function reconnect() {
    setPollError(null);
    setStreamStatus('idle');
    previousKey.current = null;
    setMode('stream');
    setRestartKey(value => value + 1);
  }

  const status = statusLabel(streamStatus);
  const streamBadge = mode === 'stream';

  return (
    <div>
      <PageHeader
        title="Живой журнал агента"
        subtitle="События жизненного цикла выбранного запуска в реальном времени."
        breadcrumbs={[{ label: 'Платформа' }, { label: 'Живой журнал' }]}
      />

      <div
        style={{
          display: 'flex',
          gap: 'var(--space-3)',
          marginBlockEnd: 'var(--space-3)',
          alignItems: 'center',
          flexWrap: 'wrap',
        }}
      >
        <label htmlFor="log-run-select" style={{ fontSize: 'var(--font-size-sm)', color: 'var(--color-text-muted)' }}>
          Запуск
        </label>
        <Select
          id="log-run-select"
          data-testid="log-run-select"
          value={runId ?? ''}
          onChange={(e) => useMvpStore.getState().selectRun(e.target.value || null)}
          style={{ minWidth: 240, marginBlockEnd: 0 }}
        >
          <option value="">— выберите запуск —</option>
          {visibleRuns.map((run) => (
            <option key={run.id} value={run.id}>
              {sanitizeTaskDisplayText(run.name)}
            </option>
          ))}
        </Select>
        <Button
          variant="secondary"
          data-testid="log-pause-button"
          onClick={() => setPaused((p) => !p)}
          aria-pressed={paused}
        >
          {paused ? '▶ Возобновить' : '⏸ Пауза'}
        </Button>
        <Button
          variant="secondary"
          data-testid="log-clear-button"
          onClick={() => {
            setEvents([]);
            setTaskFilter('');
            previousKey.current = null;
          }}
        >
          Очистить
        </Button>
        {runId ? <Button variant="secondary" data-testid="log-reconnect-button"
          onClick={reconnect}>Переподключить поток</Button> : null}
        {runId ? (
          <span data-testid="log-stream-status">
            {paused ? (
              <StatusBadge status="paused" tone="warn"
                label="Пауза — поток отключён, возобновление с курсора" />
            ) : !runIsInProject ? (
              <StatusBadge status="pending" tone="warn" label="Проверка принадлежности запуска" />
            ) : streamBadge ? (
              <StatusBadge status={streamStatus} tone={status.tone} label={status.label} />
            ) : (
              <StatusBadge
                status={pollError ? 'unavailable' : 'polling'}
                tone={pollError ? 'warn' : 'info'}
                label={pollError
                  ? 'Снимок API недоступен — состояние запуска устарело'
                  : `Опрос снимков каждые ${(POLL_MS / 1000).toFixed(0)} с — не live-поток`}
              />
            )}
          </span>
        ) : null}
      </div>

      {projectId && runId && !runIsInProject ? (
        <p role="alert" data-testid="log-scope-warning">
          {currentCatalog?.error ??
            (currentCatalog?.items ? 'Выбранный запуск не принадлежит текущему проекту.' :
              'Проверяем доступность запуска для текущего проекта…')}
        </p>
      ) : null}
      {runId ? <div style={{ display: 'flex', gap: 'var(--space-3)', flexWrap: 'wrap', marginBlockEnd: 'var(--space-3)' }}>
        <label htmlFor="log-level-filter">Уровень</label>
        <select id="log-level-filter" data-testid="log-level-filter"
          value={levelFilter} onChange={e => setLevelFilter(e.target.value as typeof levelFilter)}>
          <option value="all">Все уровни</option>
          <option value="info">Информация</option>
          <option value="success">Успешно</option>
          <option value="warn">Предупреждения</option>
          <option value="error">Ошибки</option>
        </select>
        <label htmlFor="log-task-filter">Задача</label>
        <select id="log-task-filter" data-testid="log-task-filter"
          value={effectiveTaskFilter}
          onChange={e => setTaskFilter(e.target.value)}>
          <option value="">Все задачи</option>
          {taskIds.map(id => <option key={id} value={id}>{id}</option>)}
        </select>
        <span data-testid="log-event-count" aria-live="polite">
          Показано {visibleEvents.length} из {events.length} событий
        </span>
      </div> : null}

      {!runId ? (
        <Card>
          <EmptyState
            title="Запуск не выбран"
            body="Выберите запуск, чтобы увидеть живой журнал агента."
            icon="🛰"
          />
        </Card>
      ) : (
        <Card>
          {pollError ? (
            <p role="alert" style={{ color: 'var(--color-error)', fontSize: 'var(--font-size-md)' }}>
              Ошибка потока: {sanitizeRunLogText(pollError)}
            </p>
          ) : null}
          <div
            data-testid="agent-log-feed"
            role="log"
            aria-live="polite"
            aria-atomic="false"
            aria-relevant="additions"
            style={{ fontFamily: 'var(--font-mono)', fontSize: 'var(--font-size-sm)', maxHeight: 480, overflow: 'auto' }}
          >
            {visibleEvents.length === 0 ? (
              <span style={{ color: 'var(--color-text-muted)' }}>Ожидание событий…</span>
            ) : (
              visibleEvents.map((event) => (
                <div
                  key={event.id}
                  data-testid="agent-log-entry"
                  style={{
                    display: 'flex',
                    gap: 'var(--space-2)',
                    padding: '3px 0',
                    borderBlockEnd: '1px solid var(--color-border-subtle)',
                  }}
                >
                  <span style={{ color: 'var(--color-text-subtle)', whiteSpace: 'nowrap' }}>
                    {new Date(event.at).toLocaleTimeString()}
                  </span>
                  <span style={{ color: levelColour(event.level), fontWeight: 600, minWidth: 60 }}>
                    [{event.kind}]
                  </span>
                  <span style={{ color: 'var(--color-text)' }}>{sanitizeRunLogText(event.message)}</span>
                  <span data-testid="log-event-source" style={{ color: 'var(--color-text-muted)' }}>
                    {event.source === 'stream' ? 'WS/SSE' : 'снимок API'}
                  </span>
                </div>
              ))
            )}
          </div>
        </Card>
      )}
    </div>
  );
}
