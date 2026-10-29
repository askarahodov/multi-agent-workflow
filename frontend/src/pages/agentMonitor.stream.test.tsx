/**
 * AgentMonitor ↔ live WebSocket stream integration.
 *
 * Proves the "watch agents execute" leg of the user journey: when a run is
 * selected, lifecycle events pushed over the run WebSocket appear in the live
 * agent log, the connection state is surfaced accessibly, and a dropped socket
 * transparently reconnects (network-blip recovery) without duplicating events.
 */

import { render, screen, cleanup, act } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { ReactNode } from 'react';

import AgentMonitor from './AgentMonitor';
import { I18nProvider } from '../i18n';
import { ToastProvider } from '../components';
import { useMvpStore } from '../mvp/mvpStore';
import { MockAdapter } from '../api/mockAdapter';
import type { SagaRunEvent } from '../api/runStream';

class FakeWebSocket {
  static instances: FakeWebSocket[] = [];
  url: string;
  onopen: ((ev: Event) => void) | null = null;
  onmessage: ((ev: MessageEvent) => void) | null = null;
  onerror: ((ev: Event) => void) | null = null;
  onclose: ((ev: CloseEvent) => void) | null = null;
  closed = false;

  constructor(url: string) {
    this.url = url;
    FakeWebSocket.instances.push(this);
  }

  close(): void {
    this.closed = true;
  }

  open(): void {
    this.onopen?.(new Event('open'));
  }

  push(event: SagaRunEvent): void {
    this.onmessage?.({ data: JSON.stringify({ type: 'run_event', ...event }) } as MessageEvent);
  }

  drop(): void {
    this.onclose?.({ code: 1006 } as CloseEvent);
  }
}

function Providers({ children }: { children: ReactNode }) {
  return (
    <I18nProvider>
      <ToastProvider>{children}</ToastProvider>
    </I18nProvider>
  );
}

function events(run_id = 'run-1'): SagaRunEvent[] {
  return [
    { id: 1, run_id, event: 'run.launched', aggregate_type: 'run', aggregate_id: run_id },
    { id: 2, run_id, event: 'task.claimed', aggregate_type: 'task', aggregate_id: 'task-1' },
    {
      id: 3,
      run_id,
      event: 'task.completed',
      aggregate_type: 'task',
      aggregate_id: 'task-1',
      payload: { summary: 'done' },
    },
  ];
}

beforeEach(() => {
  FakeWebSocket.instances = [];
  vi.stubGlobal('WebSocket', FakeWebSocket);
  act(() => {
    useMvpStore.setState({ api: new MockAdapter(), projectId: null, runId: 'run-1', taskId: null });
  });
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.useRealTimers();
});

describe('AgentMonitor live stream', () => {
  it('renders lifecycle events pushed over the run WebSocket', async () => {
    render(
      <Providers>
        <AgentMonitor />
      </Providers>,
    );

    await act(async () => {
      // Let the runs selector load, then the stream opens.
    });
    const socket = FakeWebSocket.instances.at(-1);
    expect(socket?.url).toContain('/workflows/runs/run-1/ws');

    act(() => socket?.open());
    act(() => {
      for (const event of events()) socket?.push(event);
    });

    const entries = await screen.findAllByTestId('agent-log-entry');
    expect(entries).toHaveLength(3);
    expect(screen.getByText(/run\.launched/)).toBeInTheDocument();
    expect(screen.getByText(/task\.completed task-1: done/)).toBeInTheDocument();
    // Connection state is exposed as accessible text.
    expect(screen.getByText('В реальном времени')).toBeInTheDocument();
  });

  it('reconnects after a network blip and resumes from the last event id', async () => {
    vi.useFakeTimers();
    render(
      <Providers>
        <AgentMonitor />
      </Providers>,
    );

    const first = FakeWebSocket.instances.at(-1);
    act(() => first?.open());
    act(() => {
      first?.push({ id: 10, run_id: 'run-1', event: 'run.launched' });
      first?.drop();
    });
    expect(screen.getByText('Переподключение…')).toBeInTheDocument();

    // Advance past the reconnect backoff; a new socket resumes from after=10.
    act(() => {
      vi.advanceTimersByTime(2000);
    });
    const second = FakeWebSocket.instances.at(-1);
    expect(second).not.toBe(first);
    expect(second?.url).toContain('after=10');

    act(() => {
      second?.open();
      second?.push({ id: 11, run_id: 'run-1', event: 'task.completed', aggregate_id: 'task-1' });
    });

    const entries = screen.getAllByTestId('agent-log-entry');
    expect(entries).toHaveLength(2);
  });
});
