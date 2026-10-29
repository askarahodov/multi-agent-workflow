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

import type { RunLogEvent, RunResponse } from '../api/types';
import { DEFAULT_BASE_URL, RunEventStream, type StreamStatus } from '../api/client';
import { useMvpStore } from '../mvp/mvpStore';
import { useAsync } from '../mvp/useAsync';
import { Button, Card, Select, StatusBadge, type StatusTone } from '../components';
import { EmptyState } from '../components/EmptyState';
import { PageHeader } from '../patterns';

const POLL_MS = 2000;

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
      message: `run "${runName}" → ${run.status}`,
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
        message: `task "${task.title}" → ${task.status}`,
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
  const runs = useAsync<RunResponse[]>(async () => (await api.listRuns({})).items);

  const [events, setEvents] = useState<RunLogEvent[]>([]);
  const [paused, setPaused] = useState(false);
  const [pollError, setPollError] = useState<string | null>(null);
  const [streamStatus, setStreamStatus] = useState<StreamStatus>('idle');
  // Live mode: the WebSocket/SSE stream when available, else snapshot polling.
  const [mode, setMode] = useState<'stream' | 'polling'>(() =>
    hasStreamingTransport() ? 'stream' : 'polling',
  );
  const previousKey = useRef<ReturnType<typeof snapshotToKey> | null>(null);
  const currentRunRef = useRef<string | null>(null);
  const pausedRef = useRef(false);
  pausedRef.current = paused;

  if (currentRunRef.current !== runId) {
    currentRunRef.current = runId;
    setEvents([]);
    setPollError(null);
    setStreamStatus('idle');
    setMode(hasStreamingTransport() ? 'stream' : 'polling');
    previousKey.current = null;
  }

  /* -------- Primary path: WebSocket (SSE fallback) live event stream -------- */
  useEffect(() => {
    if (!runId || mode !== 'stream') return;
    const targetRunId = runId;
    const stream = new RunEventStream(targetRunId, { baseUrl: DEFAULT_BASE_URL });
    stream.subscribe({
      onEvent: (event) => {
        if (pausedRef.current) return;
        setEvents((existing) => [...existing, event]);
      },
      onStatus: (status) => {
        setStreamStatus(status);
        // A stream that gave up (no transport / retries exhausted) degrades to
        // snapshot polling rather than showing a dead feed.
        if (status === 'closed') setMode('polling');
      },
      onError: (error) => setPollError(error.message),
    });
    stream.start();
    return () => stream.stop();
  }, [runId, mode]);

  /* -------- Fallback path: snapshot polling (no streaming transport) -------- */
  useEffect(() => {
    if (!runId || mode !== 'polling') return;
    const targetRunId = runId;
    let mounted = true;

    async function poll() {
      if (pausedRef.current) return;
      try {
        const snapshot = await api.getRunSnapshot(targetRunId);
        if (!mounted) return;
        const name = runs.data?.find((r) => r.id === targetRunId)?.name ?? targetRunId;
        const key = snapshotToKey(snapshot);
        const next = diffToEvents(previousKey.current, key, name);
        if (next.length > 0) {
          setEvents((existing) => [...existing, ...next]);
        }
        previousKey.current = key;
      } catch (error) {
        if (mounted) setPollError(error instanceof Error ? error.message : String(error));
      }
    }

    poll();
    const timer = setInterval(poll, POLL_MS);
    return () => {
      mounted = false;
      clearInterval(timer);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [api, runId, mode, paused]);

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
          {runs.data?.map((run) => (
            <option key={run.id} value={run.id}>
              {run.name}
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
            previousKey.current = null;
          }}
        >
          Очистить
        </Button>
        {paused ? <StatusBadge status="paused" tone="warn" label="Пауза" /> : null}
        {runId ? (
          <span data-testid="log-stream-status">
            {streamBadge ? (
              <StatusBadge status={streamStatus} tone={status.tone} label={status.label} />
            ) : (
              <StatusBadge
                status="polling"
                tone="info"
                label={`Опрос каждые ${(POLL_MS / 1000).toFixed(0)} с`}
              />
            )}
          </span>
        ) : null}
      </div>

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
              Ошибка потока: {pollError}
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
            {events.length === 0 ? (
              <span style={{ color: 'var(--color-text-muted)' }}>Ожидание событий…</span>
            ) : (
              events.map((event) => (
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
                  <span style={{ color: 'var(--color-text)' }}>{event.message}</span>
                </div>
              ))
            )}
          </div>
        </Card>
      )}
    </div>
  );
}
