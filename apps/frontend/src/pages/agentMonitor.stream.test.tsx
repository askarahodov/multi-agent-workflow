/**
 * AgentMonitor ↔ live WebSocket stream integration.
 *
 * Proves the "watch agents execute" leg of the user journey: when a run is
 * selected, lifecycle events pushed over the run WebSocket appear in the live
 * agent log, the connection state is surfaced accessibly, and a dropped socket
 * transparently reconnects (network-blip recovery) without duplicating events.
 */

import { render, screen, cleanup, act, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { ReactNode } from 'react';

import AgentMonitor from './AgentMonitor';
import { I18nProvider } from '../i18n';
import { ToastProvider } from '../components';
import { useMvpStore } from '../mvp/mvpStore';
import { MockAdapter } from '../api/mockAdapter';
import { createApiClient } from '../api/client';
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
  vi.unstubAllEnvs();
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

  it('keeps the live stream mode when switching runs (B2)', async () => {
    render(
      <Providers>
        <AgentMonitor />
      </Providers>,
    );

    await act(async () => {});
    const first = FakeWebSocket.instances.at(-1);
    expect(first?.url).toContain('/workflows/runs/run-1/ws');
    act(() => first?.open());
    expect(screen.getByText('В реальном времени')).toBeInTheDocument();

    // Switch the selected run: the old stream is torn down on purpose.
    act(() => {
      useMvpStore.setState({ runId: 'run-2' });
    });

    const second = FakeWebSocket.instances.at(-1);
    expect(second).not.toBe(first);
    expect(second?.url).toContain('/workflows/runs/run-2/ws');
    act(() => second?.open());

    // The page must remain in live-stream mode — not degrade to polling.
    expect(screen.getByText('В реальном времени')).toBeInTheDocument();
    expect(screen.queryByText(/Опрос каждые/)).not.toBeInTheDocument();
  });
});


describe('AgentMonitor ticket authorization failure', () => {
  it('does not make unauthorized polling requests after a 401 ticket rejection', async () => {
    vi.stubEnv('VITE_STREAM_TICKETS_ENABLED', '1');
    const adapter = new MockAdapter();
    const issue = vi.spyOn(adapter, 'issueStreamTicket').mockRejectedValue(
      Object.assign(new Error('unauthorized'), { status: 401 }),
    );
    const snapshot = vi.spyOn(adapter, 'getRunSnapshot');
    act(() => {
      useMvpStore.setState({ api: adapter, runId: 'run-1' });
    });
    render(
      <Providers>
        <AgentMonitor />
      </Providers>,
    );
    await waitFor(() => expect(issue).toHaveBeenCalledTimes(1));
    expect(await screen.findByText(/stream ticket authorization required/)).toBeInTheDocument();
    expect(screen.getByText('Поток закрыт')).toBeInTheDocument();
    expect(screen.queryByText(/Опрос каждые/)).not.toBeInTheDocument();
    expect(snapshot).not.toHaveBeenCalled();
    expect(FakeWebSocket.instances).toHaveLength(0);
  });
});


describe('AgentMonitor authenticated HTTP ticket integration', () => {
  it('uses a runtime credential for WS tickets and refreshes it on reconnect', async () => {
    vi.stubEnv('VITE_STREAM_TICKETS_ENABLED', '1');
    let credential = 'browser-session-1';
    let serial = 0;
    const issued: Array<{ url: string; authorization: string | undefined; transport: string }> = [];
    const fetchImpl: typeof fetch = async (input, init) => {
      const url = String(input);
      const headers = init?.headers as Record<string, string>;
      if (url.endsWith('/workflows/runs/run-1/stream-tickets')) {
        const transport = JSON.parse(String(init?.body)).transport as string;
        issued.push({ url, authorization: headers.Authorization, transport });
        serial++;
        return new Response(JSON.stringify({ ticket: `short-ticket-${serial}` }), {
          status: 200, headers: { 'Content-Type': 'application/json', 'Cache-Control': 'no-store' },
        });
      }
      if (url.endsWith('/workflows/runs')) {
        return new Response(JSON.stringify({ items: [], next_cursor: null }), {
          status: 200, headers: { 'Content-Type': 'application/json' },
        });
      }
      throw new Error(`Unexpected HTTP path: ${url}`);
    };
    const adapter = createApiClient({
      tokenProvider: async () => credential,
      fetchImpl,
    });
    act(() => useMvpStore.setState({ api: adapter, runId: 'run-1' }));
    render(<Providers><AgentMonitor /></Providers>);
    await waitFor(() => expect(FakeWebSocket.instances).toHaveLength(1));
    const first = FakeWebSocket.instances[0];
    expect(first.url).toContain('stream_ticket=short-ticket-1');
    expect(first.url).not.toContain('browser-session-');
    expect(issued[0]).toEqual({
      url: '/api/v1/workflows/runs/run-1/stream-tickets',
      authorization: 'Bearer browser-session-1',
      transport: 'websocket',
    });
    act(() => {
      first.open();
      first.push(events()[0]);
    });
    expect(await screen.findAllByTestId('agent-log-entry')).toHaveLength(1);
    credential = 'browser-session-2';
    act(() => first.drop());
    await waitFor(() => expect(FakeWebSocket.instances).toHaveLength(2), { timeout: 4000 });
    const second = FakeWebSocket.instances[1];
    expect(second.url).toContain('stream_ticket=short-ticket-2');
    expect(second.url).toContain('after=1');
    expect(second.url).not.toContain('browser-session-');
    expect(issued.map(x => x.authorization)).toEqual([
      'Bearer browser-session-1', 'Bearer browser-session-2',
    ]);
    act(() => {
      second.open();
      second.push({ ...events()[1], id: 2 });
    });
    expect(await screen.findAllByTestId('agent-log-entry')).toHaveLength(2);
  });

  it('never opens a stream or starts polling when the runtime session is unavailable', async () => {
    vi.stubEnv('VITE_STREAM_TICKETS_ENABLED', '1');
    const calls: string[] = [];
    const adapter = createApiClient({
      tokenProvider: () => undefined,
      fetchImpl: async input => {
        calls.push(String(input));
        return new Response(JSON.stringify({ items: [], next_cursor: null }), { status: 200 });
      },
    });
    act(() => useMvpStore.setState({ api: adapter, runId: 'run-1' }));
    render(<Providers><AgentMonitor /></Providers>);
    expect(await screen.findByText(/stream ticket authorization required/)).toBeInTheDocument();
    expect(FakeWebSocket.instances).toHaveLength(0);
    expect(screen.getByText('Поток закрыт')).toBeInTheDocument();
    expect(screen.queryByText(/Опрос каждые/)).not.toBeInTheDocument();
    expect(calls).toHaveLength(0);
  });
});
