/**
 * MVP v1 — Live agent log section (живой журнал агента).
 *
 * Streams the currently selected run's lifecycle as a live, timestamped log by
 * polling the existing run/task endpoints. No dedicated SSE log endpoint exists
 * yet, so the MVP uses short-interval polling of `getRunSnapshot` and diffs
 * consecutive snapshots into `RunLogEvent`s (ADR-101 §8 permits polling during
 * the migration period; this decision is documented here and in the section UI).
 *
 * The log auto-appends on a timer; it is append-only for the session so the
 * user always sees the events discovered since they opened the section.
 */

import { useEffect, useRef, useState } from 'react';

import type { RunLogEvent, RunResponse } from '../../api/types';
import { useMvpStore } from '../mvpStore';
import { useAsync } from '../useAsync';
import { Card, PageHeader } from '../ui';

const POLL_MS = 2000;

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

export default function AgentLogSection() {
  const api = useMvpStore((s) => s.api);
  const runId = useMvpStore((s) => s.runId);
  const runs = useAsync<RunResponse[]>(async () => (await api.listRuns({})).items);

  const [events, setEvents] = useState<RunLogEvent[]>([]);
  const [paused, setPaused] = useState(false);
  const [pollError, setPollError] = useState<string | null>(null);
  const previousKey = useRef<ReturnType<typeof snapshotToKey> | null>(null);
  const currentRunRef = useRef<string | null>(null);

  // Reset the log when the displayed run changes (not on every effect re-run).
  if (currentRunRef.current !== runId) {
    currentRunRef.current = runId;
    setEvents([]);
    setPollError(null);
    previousKey.current = null;
  }

  useEffect(() => {
    if (!runId) return;
    const targetRunId = runId;
    let mounted = true;

    async function poll() {
      if (paused) return;
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
  }, [api, runId, paused]);

  return (
    <div>
      <PageHeader
        title="Живой журнал агента"
        subtitle="События жизненного цикла выбранного запуска в реальном времени (polling через получение снимков запуска и задач)."
      />

      <div
        style={{
          display: 'flex',
          gap: 12,
          marginBottom: 12,
          alignItems: 'center',
          flexWrap: 'wrap',
        }}
      >
        <select
          data-testid="log-run-select"
          value={runId ?? ''}
          onChange={(e) => useMvpStore.getState().selectRun(e.target.value || null)}
          style={{
            padding: '8px 10px',
            borderRadius: 6,
            border: '1px solid #c8ced6',
            minWidth: 240,
          }}
        >
          <option value="">— выберите запуск —</option>
          {runs.data?.map((run) => (
            <option key={run.id} value={run.id}>
              {run.name}
            </option>
          ))}
        </select>
        <button
          data-testid="log-pause-button"
          onClick={() => setPaused((p) => !p)}
          style={{
            padding: '8px 12px',
            borderRadius: 6,
            border: '1px solid #c8ced6',
            background: '#fff',
            cursor: 'pointer',
          }}
        >
          {paused ? '▶ Возобновить' : '⏸ Пауза'}
        </button>
        <button
          data-testid="log-clear-button"
          onClick={() => {
            setEvents([]);
            previousKey.current = null;
          }}
          style={{
            padding: '8px 12px',
            borderRadius: 6,
            border: '1px solid #c8ced6',
            background: '#fff',
            cursor: 'pointer',
          }}
        >
          Очистить
        </button>
        <span style={{ fontSize: 12, color: '#5b6472' }}>
          запрос каждые {(POLL_MS / 1000).toFixed(0)} с
        </span>
      </div>

      {!runId ? (
        <Card>
          <p style={{ color: '#5b6472' }}>Выберите запуск, чтобы увидеть живой журнал агента.</p>
        </Card>
      ) : (
        <Card>
          {pollError ? (
            <p style={{ color: '#a3271c', fontSize: 13 }}>Ошибка опроса: {pollError}</p>
          ) : null}
          {events.length === 0 ? (
            <p style={{ color: '#5b6472' }}>Ожидание событий…</p>
          ) : (
            <div
              data-testid="agent-log-feed"
              style={{ fontFamily: 'monospace', fontSize: 12, maxHeight: 480, overflow: 'auto' }}
            >
              {events.map((event) => (
                <div
                  key={event.id}
                  style={{
                    display: 'flex',
                    gap: 10,
                    padding: '3px 0',
                    borderBottom: '1px solid #f2f4f7',
                  }}
                >
                  <span style={{ color: '#9aa2af', whiteSpace: 'nowrap' }}>
                    {new Date(event.at).toLocaleTimeString()}
                  </span>
                  <span style={{ color: levelColour(event.level), fontWeight: 600, minWidth: 60 }}>
                    [{event.kind}]
                  </span>
                  <span style={{ color: '#2b3440' }}>{event.message}</span>
                </div>
              ))}
            </div>
          )}
        </Card>
      )}
    </div>
  );
}

function levelColour(level: RunLogEvent['level']): string {
  switch (level) {
    case 'error':
      return '#a3271c';
    case 'warn':
      return '#9a6a12';
    case 'success':
      return '#18703b';
    default:
      return '#1c5fa8';
  }
}
