import { afterEach, describe, expect, it, vi } from 'vitest';

import {
  RunEventStream,
  parseSseData,
  parseWebSocketFrame,
  runEventSourceUrl,
  runWebSocketUrl,
  sagaEventToLogEvent,
  sanitizeRunLogText,
  toWebSocketBase,
  type SagaRunEvent,
} from './runStream';
import type { RunLogEvent } from './types';

/* --------------------------- transport doubles --------------------------- */

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

  emitOpen(): void {
    this.onopen?.(new Event('open'));
  }

  emit(message: unknown): void {
    this.onmessage?.({ data: JSON.stringify(message) } as MessageEvent);
  }

  emitRaw(data: string): void {
    this.onmessage?.({ data } as MessageEvent);
  }

  emitError(): void {
    this.onerror?.(new Event('error'));
  }

  emitClose(): void {
    this.onclose?.({ code: 1006 } as CloseEvent);
  }
}

class FakeEventSource {
  static instances: FakeEventSource[] = [];
  url: string;
  onopen: ((ev: Event) => void) | null = null;
  onmessage: ((ev: MessageEvent) => void) | null = null;
  onerror: ((ev: Event) => void) | null = null;
  closed = false;
  private listeners = new Map<string, Set<EventListener>>();

  constructor(url: string) {
    this.url = url;
    FakeEventSource.instances.push(this);
  }

  close(): void {
    this.closed = true;
  }

  addEventListener(type: string, handler: EventListener): void {
    let set = this.listeners.get(type);
    if (!set) {
      set = new Set();
      this.listeners.set(type, set);
    }
    set.add(handler);
  }

  removeEventListener(type: string, handler: EventListener): void {
    this.listeners.get(type)?.delete(handler);
  }

  emitOpen(): void {
    this.onopen?.(new Event('open'));
  }

  emitError(): void {
    this.onerror?.(new Event('error'));
  }

  /** Deliver a frame as a plain default-``message`` event (via ``onmessage``). */
  emit(event: SagaRunEvent): void {
    this.onmessage?.({ data: JSON.stringify(event) } as MessageEvent);
  }

  /**
   * Dispatch a raw SSE body exactly as a browser ``EventSource`` would: a frame
   * that names a type (`event: <type>`) goes only to listeners for that type;
   * a frame without a name goes to the default ``onmessage`` handler.
   */
  dispatchSse(text: string): void {
    for (const block of text.split('\n\n')) {
      if (!block.trim()) continue;
      let type = 'message';
      const data: string[] = [];
      for (const line of block.split('\n')) {
        if (line.startsWith(':')) continue;
        const idx = line.indexOf(':');
        const field = idx === -1 ? line : line.slice(0, idx);
        let value = idx === -1 ? '' : line.slice(idx + 1);
        if (value.startsWith(' ')) value = value.slice(1);
        if (field === 'event') type = value;
        else if (field === 'data') data.push(value);
      }
      if (data.length === 0) continue;
      const message = { data: data.join('\n') } as MessageEvent;
      if (type === 'message') this.onmessage?.(message);
      else this.listeners.get(type)?.forEach((handler) => handler(message));
    }
  }
}

function sagaEvent(overrides: Partial<SagaRunEvent> = {}): SagaRunEvent {
  return {
    id: 1,
    run_id: 'run-1',
    event: 'task.completed',
    aggregate_type: 'task',
    aggregate_id: 'task-1',
    payload: {},
    created_at: '2026-01-01T00:00:00+00:00',
    ...overrides,
  };
}

/** A deterministic scheduler so reconnect backoff can be stepped in tests. */
function makeScheduler() {
  let nextId = 0;
  const scheduled = new Map<number, () => void>();
  return {
    setTimeout: (handler: () => void, _timeout: number) => {
      const id = ++nextId;
      scheduled.set(id, handler);
      return id;
    },
    clearTimeout: (id: number) => {
      scheduled.delete(id);
    },
    /** Run every currently-pending timer (in insertion order). */
    flush(): void {
      const pending = [...scheduled.entries()];
      scheduled.clear();
      for (const [, handler] of pending) handler();
    },
    get size(): number {
      return scheduled.size;
    },
  };
}

afterEach(() => {
  FakeWebSocket.instances = [];
  FakeEventSource.instances = [];
  vi.restoreAllMocks();
});

/* ------------------------------ pure helpers ----------------------------- */

describe('runStream URL + framing helpers', () => {
  it('converts http/https bases to ws/wss', () => {
    expect(toWebSocketBase('http://host/api/v1')).toBe('ws://host/api/v1');
    expect(toWebSocketBase('https://host/api/v1')).toBe('wss://host/api/v1');
    expect(toWebSocketBase('/api/v1', 'https://app.example')).toBe('wss://app.example/api/v1');
  });

  it('builds a resumable ws URL with the api_key query param', () => {
    const url = runWebSocketUrl('/api/v1', 'run 1', { after: 42, apiKey: 'k' }, 'http://host');
    expect(url).toBe('ws://host/api/v1/workflows/runs/run%201/ws?after=42&api_key=k');
  });

  it('builds an SSE URL with the resume cursor', () => {
    expect(runEventSourceUrl('/api/v1', 'r1', { after: 7 })).toBe(
      '/api/v1/workflows/runs/r1/events?after=7',
    );
    expect(runEventSourceUrl('/api/v1', 'r1')).toBe('/api/v1/workflows/runs/r1/events');
  });

  it('parses websocket frames: ping, run_event, garbage', () => {
    expect(parseWebSocketFrame('{"type":"ping"}')).toBeNull();
    expect(parseWebSocketFrame('{ not json')).toBeUndefined();
    expect(parseWebSocketFrame('42')).toBeUndefined();
    const event = parseWebSocketFrame(JSON.stringify({ type: 'run_event', ...sagaEvent() }));
    expect(event?.event).toBe('task.completed');
  });

  it('parses SSE data payloads defensively', () => {
    expect(parseSseData(JSON.stringify(sagaEvent()))?.id).toBe(1);
    expect(parseSseData('nonsense')).toBeNull();
    expect(parseSseData('{"no":"event"}')).toBeNull();
  });
});

describe('sagaEventToLogEvent mapping', () => {
  it('maps lifecycle transitions to kind + level', () => {
    expect(sagaEventToLogEvent(sagaEvent({ event: 'run.launched' })).level).toBe('info');
    expect(sagaEventToLogEvent(sagaEvent({ event: 'run.completed' })).level).toBe('success');
    expect(sagaEventToLogEvent(sagaEvent({ event: 'run.failed' })).kind).toBe('run');
    expect(sagaEventToLogEvent(sagaEvent({ event: 'task.blocked' })).level).toBe('warn');
    expect(sagaEventToLogEvent(sagaEvent({ event: 'attempt.failed' })).kind).toBe('attempt');
  });

  it('surfaces a payload summary and links the task id', () => {
    const mapped = sagaEventToLogEvent(
      sagaEvent({ event: 'task.failed', payload: { error: 'boom' } }),
    );
    expect(mapped.message).toContain('boom');
    expect(mapped.task_id).toBe('task-1');
    expect(mapped.id).toBe('saga-1');
  });

  it('never drops an unknown event type', () => {
    const mapped = sagaEventToLogEvent(sagaEvent({ event: 'task.some_new_thing' }));
    expect(mapped.kind).toBe('info');
    expect(mapped.message).toContain('task.some_new_thing');
  });
});

/* -------------------------------- stream --------------------------------- */

describe('RunEventStream (WebSocket)', () => {
  it('delivers mapped events and tracks the resume cursor', () => {
    const received: RunLogEvent[] = [];
    const statuses: string[] = [];
    const stream = new RunEventStream('run-1', {
      websocketImpl: FakeWebSocket as unknown as typeof WebSocket,
    });
    stream.subscribe({
      onEvent: (e) => received.push(e),
      onStatus: (s) => statuses.push(s),
    });
    stream.start();

    const socket = FakeWebSocket.instances[0];
    expect(socket.url).toContain('/workflows/runs/run-1/ws');
    socket.emitOpen();
    socket.emit({ type: 'ping' });
    socket.emit({ type: 'run_event', ...sagaEvent({ id: 5, event: 'run.launched' }) });
    socket.emit({ type: 'run_event', ...sagaEvent({ id: 6, event: 'task.claimed' }) });

    expect(received.map((e) => e.id)).toEqual(['saga-5', 'saga-6']);
    expect(stream.getLastEventId()).toBe(6);
    expect(statuses).toContain('open');
    expect(stream.transport).toBe('websocket');
  });

  it('reconnects after a drop and resumes from the last seen id', () => {
    const scheduler = makeScheduler();
    const received: RunLogEvent[] = [];
    const stream = new RunEventStream('run-1', {
      websocketImpl: FakeWebSocket as unknown as typeof WebSocket,
      setTimeoutImpl: scheduler.setTimeout,
      clearTimeoutImpl: scheduler.clearTimeout,
      random: () => 1,
    });
    stream.subscribe({ onEvent: (e) => received.push(e) });
    stream.start();

    const first = FakeWebSocket.instances[0];
    first.emitOpen();
    first.emit({ type: 'run_event', ...sagaEvent({ id: 11, event: 'task.claimed' }) });
    first.emitClose();

    expect(stream.getStatus()).toBe('reconnecting');
    expect(scheduler.size).toBe(1);

    scheduler.flush();
    const second = FakeWebSocket.instances[1];
    expect(second.url).toContain('after=11');
    second.emitOpen();
    second.emit({ type: 'run_event', ...sagaEvent({ id: 12, event: 'task.completed' }) });

    // No duplicate of event 11, and the new event arrives exactly once.
    expect(received.map((e) => e.id)).toEqual(['saga-11', 'saga-12']);
    expect(stream.getLastEventId()).toBe(12);
  });

  it('gives up after maxRetries and reports closed', () => {
    const scheduler = makeScheduler();
    const stream = new RunEventStream('run-1', {
      websocketImpl: FakeWebSocket as unknown as typeof WebSocket,
      setTimeoutImpl: scheduler.setTimeout,
      clearTimeoutImpl: scheduler.clearTimeout,
      maxRetries: 2,
      random: () => 0,
    });
    const statuses: string[] = [];
    const errors: string[] = [];
    stream.subscribe({ onStatus: (s) => statuses.push(s), onError: (e) => errors.push(e.message) });
    stream.start();

    // First attempt fails, then two reconnects, then exhaustion.
    FakeWebSocket.instances[0].emitClose();
    for (let i = 0; i < 2; i += 1) {
      scheduler.flush();
      FakeWebSocket.instances.at(-1)?.emitClose();
    }
    scheduler.flush();

    expect(stream.getStatus()).toBe('closed');
    expect(statuses.at(-1)).toBe('closed');
    expect(errors.some((m) => m.includes('exhausted'))).toBe(true);
  });

  it('stop() cancels pending reconnects and closes an open transport', () => {
    const scheduler = makeScheduler();
    const stream = new RunEventStream('run-1', {
      websocketImpl: FakeWebSocket as unknown as typeof WebSocket,
      setTimeoutImpl: scheduler.setTimeout,
      clearTimeoutImpl: scheduler.clearTimeout,
    });
    stream.start();
    const socket = FakeWebSocket.instances[0];
    socket.emitOpen();
    expect(stream.getStatus()).toBe('open');

    stream.stop();
    expect(socket.closed).toBe(true);
    expect(stream.getStatus()).toBe('closed');

    // A drop after stop() must not schedule a reconnect.
    socket.emitClose();
    expect(scheduler.size).toBe(0);
    scheduler.flush();
    expect(FakeWebSocket.instances.length).toBe(1);
  });
});

describe('RunEventStream event integrity and recovery', () => {
  it('discards duplicate, out-of-order, invalid and cross-run frames without changing the cursor', () => {
    const received: string[] = [];
    const stream = new RunEventStream('run-1', {
      websocketImpl: FakeWebSocket as unknown as typeof WebSocket,
    });
    stream.subscribe({ onEvent: (event) => received.push(event.id) });
    stream.start();
    const socket = FakeWebSocket.instances[0];
    socket.emitOpen();
    socket.emit({ type: 'run_event', ...sagaEvent({ id: 7 }) });
    socket.emit({ type: 'run_event', ...sagaEvent({ id: 7 }) });
    socket.emit({ type: 'run_event', ...sagaEvent({ id: 6 }) });
    socket.emit({ type: 'run_event', ...sagaEvent({ id: 8, run_id: 'other-run' }) });
    socket.emit({ type: 'run_event', ...sagaEvent({ id: -1 }) });
    socket.emit({ type: 'run_event', ...sagaEvent({ id: 8.5 }) });
    socket.emit({ type: 'run_event', ...sagaEvent({ id: Number.MAX_SAFE_INTEGER + 1 }) });
    socket.emit({ type: 'run_event', ...sagaEvent({ id: 8 }) });
    expect(received).toEqual(['saga-7', 'saga-8']);
    expect(stream.getLastEventId()).toBe(8);
    stream.stop();
  });
});

describe('RunEventStream (SSE fallback)', () => {
  it('uses EventSource when WebSocket is unavailable', () => {
    const received: RunLogEvent[] = [];
    // Force "no WebSocket" so the stream must fall back to SSE.
    const stream = new RunEventStream('run-1', {
      websocketImpl: null,
      eventSourceImpl: FakeEventSource as unknown as typeof EventSource,
    });
    stream.subscribe({ onEvent: (e) => received.push(e) });

    stream.start();

    expect(stream.transport).toBe('sse');
    const source = FakeEventSource.instances[0];
    expect(source.url).toContain('/workflows/runs/run-1/events');
    source.emitOpen();
    source.emit(sagaEvent({ id: 3, event: 'run.completed' }));
    expect(received.map((e) => e.id)).toEqual(['saga-3']);
    expect(stream.getLastEventId()).toBe(3);
  });

  it('reports a clean error when no transport exists at all', () => {
    const stream = new RunEventStream('run-1', { websocketImpl: null, eventSourceImpl: null });
    const errors: string[] = [];
    stream.subscribe({ onError: (e) => errors.push(e.message) });
    stream.start();
    // No transport at all: the stream must report it and not throw.
    expect(errors.length).toBeGreaterThan(0);
  });

  it('delivers named SSE frames through real event-type dispatch', () => {
    // A server that frames events as `event: <type>`: a browser dispatches such
    // a frame ONLY to a listener registered for that exact type. This is the
    // pre-fix failure mode — the client used to set only `onmessage`.
    const received: RunLogEvent[] = [];
    const stream = new RunEventStream('run-1', {
      websocketImpl: null,
      eventSourceImpl: FakeEventSource as unknown as typeof EventSource,
    });
    stream.subscribe({ onEvent: (e) => received.push(e) });

    stream.start();
    const source = FakeEventSource.instances[0];
    source.emitOpen();
    const event = sagaEvent({ id: 9, event: 'task.completed' });
    source.dispatchSse(`id: 9\nevent: task.completed\ndata: ${JSON.stringify(event)}\n\n`);

    expect(received.map((e) => e.id)).toEqual(['saga-9']);
    expect(stream.getLastEventId()).toBe(9);
  });

  it('delivers default-message SSE frames (current server framing)', () => {
    const received: RunLogEvent[] = [];
    const stream = new RunEventStream('run-1', {
      websocketImpl: null,
      eventSourceImpl: FakeEventSource as unknown as typeof EventSource,
    });
    stream.subscribe({ onEvent: (e) => received.push(e) });

    stream.start();
    const source = FakeEventSource.instances[0];
    source.emitOpen();
    const event = sagaEvent({ id: 4, event: 'run.launched' });
    source.dispatchSse(`id: 4\ndata: ${JSON.stringify(event)}\n\n`);

    expect(received.map((e) => e.id)).toEqual(['saga-4']);
  });

  it('stop() does not announce a closed status (user-initiated teardown)', () => {
    const statuses: string[] = [];
    const stream = new RunEventStream('run-1', {
      websocketImpl: FakeWebSocket as unknown as typeof WebSocket,
    });
    stream.subscribe({ onStatus: (s) => statuses.push(s) });
    stream.start();
    FakeWebSocket.instances[0].emitOpen();
    expect(stream.getStatus()).toBe('open');

    const beforeStop = [...statuses];
    stream.stop();
    // The internal status is terminal, but subscribers are not notified: a
    // run switch must not look like a fatal stream failure (B2).
    expect(stream.getStatus()).toBe('closed');
    expect(statuses).toEqual(beforeStop);
    expect(statuses).not.toContain('closed');
  });
});


describe('RunEventStream ticket mode', () => {
  it('requests a fresh WebSocket ticket without putting the long-lived key in the URL', async () => {
    const requested: Array<{ url: string; init: RequestInit }> = [];
    const fakeFetch = vi.fn(async (url: string, init: RequestInit) => {
      requested.push({ url, init });
      return { ok: true, json: async () => ({ ticket: 'short-lived-ws-ticket' }) } as Response;
    });
    const stream = new RunEventStream('run-1', {
      apiKey: 'long-lived-secret',
      streamTickets: true,
      fetchImpl: fakeFetch as unknown as typeof fetch,
      websocketImpl: FakeWebSocket as unknown as typeof WebSocket,
    });
    stream.start();
    await vi.waitFor(() => expect(FakeWebSocket.instances).toHaveLength(1));
    expect(requested).toHaveLength(1);
    expect(requested[0].init.method).toBe('POST');
    expect(requested[0].init.headers).toEqual({
      'Content-Type': 'application/json', 'X-API-Key': 'long-lived-secret',
    });
    expect(FakeWebSocket.instances[0].url).toContain('stream_ticket=short-lived-ws-ticket');
    expect(FakeWebSocket.instances[0].url).not.toContain('long-lived-secret');
    expect(FakeWebSocket.instances[0].url).not.toContain('api_key');
    stream.stop();
  });

  it('obtains independent SSE fallback ticket when WebSocket constructor throws', async () => {
    const issued: string[] = [];
    const fakeFetch = vi.fn(async (_url: string, init: RequestInit) => {
      const transport = JSON.parse(init.body as string).transport as string;
      issued.push(transport);
      return { ok: true, json: async () => ({ ticket: transport + '-ticket' }) } as Response;
    });
    class ThrowingSocket {
      constructor(url: string) { throw new Error(url); }
    }
    const stream = new RunEventStream('run-1', {
      apiKey: 'long-lived-secret',
      streamTickets: true,
      fetchImpl: fakeFetch as unknown as typeof fetch,
      websocketImpl: ThrowingSocket as unknown as typeof WebSocket,
      eventSourceImpl: FakeEventSource as unknown as typeof EventSource,
    });
    const errors: string[] = [];
    stream.subscribe({ onError: (error) => errors.push(error.message) });
    stream.start();
    await vi.waitFor(() => expect(FakeEventSource.instances).toHaveLength(1));
    expect(issued).toEqual(['websocket', 'sse']);
    expect(FakeEventSource.instances[0].url).toContain('stream_ticket=sse-ticket');
    expect(FakeEventSource.instances[0].url).not.toContain('long-lived-secret');
    expect(errors.join(' ')).not.toContain('long-lived-secret');
    stream.stop();
  });

  it('does not create a socket after stop while ticket issuance is pending', async () => {
    let finish!: (value: Response) => void;
    const fakeFetch = vi.fn(() => new Promise<Response>((resolve) => { finish = resolve; }));
    const stream = new RunEventStream('run-1', {
      streamTickets: true,
      fetchImpl: fakeFetch as unknown as typeof fetch,
      websocketImpl: FakeWebSocket as unknown as typeof WebSocket,
    });
    stream.start();
    stream.stop();
    finish({ ok: true, json: async () => ({ ticket: 'obsolete' }) } as Response);
    await Promise.resolve();
    await Promise.resolve();
    expect(FakeWebSocket.instances).toHaveLength(0);
  });
});


describe('RunEventStream asynchronous WebSocket fallback', () => {
  it('uses a fresh SSE ticket after a refused upgrade and on every SSE retry, preserving cursor', async () => {
    const scheduler = makeScheduler();
    const issued: string[] = [];
    const received: string[] = [];
    const fakeFetch = vi.fn(async (_url: string, init: RequestInit) => {
      const transport = JSON.parse(init.body as string).transport as string;
      issued.push(transport);
      return { ok: true, json: async () => ({ ticket: transport + '-' + issued.length }) } as Response;
    });
    const stream = new RunEventStream('run-1', {
      apiKey: 'private-api-key', streamTickets: true,
      fetchImpl: fakeFetch as unknown as typeof fetch,
      websocketImpl: FakeWebSocket as unknown as typeof WebSocket,
      eventSourceImpl: FakeEventSource as unknown as typeof EventSource,
      setTimeoutImpl: scheduler.setTimeout, clearTimeoutImpl: scheduler.clearTimeout,
    });
    stream.subscribe({ onEvent: (e) => received.push(e.id) });
    stream.start();
    await vi.waitFor(() => expect(FakeWebSocket.instances).toHaveLength(1));
    const failedSocket = FakeWebSocket.instances[0];
    // Most reverse proxies fail upgrades asynchronously; the constructor did NOT throw.
    failedSocket.emitError();
    failedSocket.emitClose();
    await vi.waitFor(() => expect(FakeEventSource.instances).toHaveLength(1));
    expect(issued).toEqual(['websocket', 'sse']);
    expect(FakeEventSource.instances[0].url).toContain('stream_ticket=sse-2');
    expect(FakeEventSource.instances[0].url).not.toContain('private-api-key');
    expect(FakeEventSource.instances[0].url).not.toContain('api_key');
    expect(failedSocket.closed).toBe(true);

    const firstSse = FakeEventSource.instances[0];
    firstSse.emitOpen();
    firstSse.emit(sagaEvent({ id: 10 }));
    firstSse.emit(sagaEvent({ id: 10 }));
    firstSse.emit(sagaEvent({ id: 11, run_id: 'another-run' }));
    firstSse.emit(sagaEvent({ id: 11 }));
    expect(received).toEqual(['saga-10', 'saga-11']);
    firstSse.emitError();
    expect(firstSse.closed).toBe(true);
    expect(scheduler.size).toBe(1);
    scheduler.flush();
    await vi.waitFor(() => expect(FakeEventSource.instances).toHaveLength(2));
    expect(issued).toEqual(['websocket', 'sse', 'sse']);
    expect(FakeWebSocket.instances).toHaveLength(1);
    expect(FakeEventSource.instances[1].url).toContain('stream_ticket=sse-3');
    expect(FakeEventSource.instances[1].url).toContain('after=11');
    // Already-torn-down EventSource callbacks must never race a new stream.
    firstSse.emit(sagaEvent({ id: 12 }));
    FakeEventSource.instances[1].emit(sagaEvent({ id: 11 }));
    FakeEventSource.instances[1].emit(sagaEvent({ id: 12 }));
    expect(received).toEqual(['saga-10', 'saga-11', 'saga-12']);
    stream.stop();
  });

  it('keeps retrying WebSocket if there is no SSE constructor, then fails closed', () => {
    const scheduler = makeScheduler();
    const stream = new RunEventStream('run-1', {
      websocketImpl: FakeWebSocket as unknown as typeof WebSocket,
      eventSourceImpl: null, maxRetries: 1,
      setTimeoutImpl: scheduler.setTimeout, clearTimeoutImpl: scheduler.clearTimeout,
    });
    stream.start();
    FakeWebSocket.instances[0].emitClose();
    expect(scheduler.size).toBe(1);
    scheduler.flush();
    expect(FakeWebSocket.instances).toHaveLength(2);
    FakeWebSocket.instances[1].emitClose();
    expect(stream.getStatus()).toBe('closed');
    stream.stop();
  });

  it('a new start retires SSE and returns to the preferred WebSocket transport', async () => {
    const scheduler = makeScheduler();
    const received: string[] = [];
    const stream = new RunEventStream('run-1', {
      websocketImpl: FakeWebSocket as unknown as typeof WebSocket,
      eventSourceImpl: FakeEventSource as unknown as typeof EventSource,
      setTimeoutImpl: scheduler.setTimeout, clearTimeoutImpl: scheduler.clearTimeout,
    });
    stream.subscribe({ onEvent: (e) => received.push(e.id) });
    stream.start();
    FakeWebSocket.instances[0].emitClose();
    await vi.waitFor(() => expect(FakeEventSource.instances).toHaveLength(1));
    const oldSse = FakeEventSource.instances[0];
    oldSse.emitError();
    expect(scheduler.size).toBe(1);
    stream.start();
    expect(scheduler.size).toBe(0);
    expect(FakeWebSocket.instances).toHaveLength(2);
    oldSse.emit(sagaEvent({ id: 99 }));
    expect(received).toEqual([]);
    scheduler.flush();
    expect(FakeEventSource.instances).toHaveLength(1);
    stream.stop();
  });

  it('halts on forbidden SSE ticket issuance without leaking a key or opening fallback', async () => {
    const scheduler = makeScheduler();
    const fakeFetch = vi.fn(async (_url: string, init: RequestInit) => {
      const transport = JSON.parse(init.body as string).transport as string;
      return transport === 'websocket'
        ? ({ ok: true, json: async () => ({ ticket: 'ws-only' }) } as Response)
        : ({ status: 403, ok: false } as Response);
    });
    const errors: string[] = [];
    const stream = new RunEventStream('run-1', {
      apiKey: 'private-api-key', streamTickets: true,
      fetchImpl: fakeFetch as unknown as typeof fetch,
      websocketImpl: FakeWebSocket as unknown as typeof WebSocket,
      eventSourceImpl: FakeEventSource as unknown as typeof EventSource,
      setTimeoutImpl: scheduler.setTimeout, clearTimeoutImpl: scheduler.clearTimeout,
    });
    stream.subscribe({ onError: (e) => errors.push(e.message) });
    stream.start();
    await vi.waitFor(() => expect(FakeWebSocket.instances).toHaveLength(1));
    FakeWebSocket.instances[0].emitClose();
    await vi.waitFor(() => expect(stream.getStatus()).toBe('closed'));
    expect(fakeFetch).toHaveBeenCalledTimes(2);
    expect(FakeEventSource.instances).toHaveLength(0);
    expect(scheduler.size).toBe(0);
    expect(errors).toEqual(['stream ticket authorization required']);
    stream.stop();
  });
});

describe('RunEventStream ticket authentication errors', () => {
  it('stops reconnecting after an unauthorized ticket issuance response', async () => {
    const fakeFetch = vi.fn(async () => ({ status: 401, ok: false }) as Response);
    const errors: string[] = [];
    const statuses: string[] = [];
    const stream = new RunEventStream('run-1', {
      streamTickets: true,
      fetchImpl: fakeFetch as unknown as typeof fetch,
      websocketImpl: FakeWebSocket as unknown as typeof WebSocket,
      baseDelayMs: 1,
    });
    stream.subscribe({
      onError: (error) => errors.push(error.message),
      onStatus: (status) => statuses.push(status),
    });
    stream.start();
    await vi.waitFor(() => expect(stream.getStatus()).toBe('closed'));
    expect(errors).toContain('stream ticket authorization required');
    expect(statuses).not.toContain('reconnecting');
    expect(fakeFetch).toHaveBeenCalledTimes(1);
    expect(FakeWebSocket.instances).toHaveLength(0);
    stream.stop();
  });
});


describe('RunEventStream ticket request generations', () => {
  it('ignores a stale success from an earlier start after stop and restart', async () => {
    const resolveTickets: Array<(response: Response) => void> = [];
    const fakeFetch = vi.fn(() => new Promise<Response>((resolve) => {
      resolveTickets.push(resolve);
    }));
    const stream = new RunEventStream('run-1', {
      streamTickets: true,
      fetchImpl: fakeFetch as unknown as typeof fetch,
      websocketImpl: FakeWebSocket as unknown as typeof WebSocket,
    });
    stream.start();
    stream.stop();
    stream.start();
    resolveTickets[0]({ ok: true, json: async () => ({ ticket: 'stale' }) } as Response);
    await Promise.resolve();
    await Promise.resolve();
    expect(FakeWebSocket.instances).toHaveLength(0);
    resolveTickets[1]({ ok: true, json: async () => ({ ticket: 'fresh' }) } as Response);
    await vi.waitFor(() => expect(FakeWebSocket.instances).toHaveLength(1));
    expect(FakeWebSocket.instances[0].url).toContain('stream_ticket=fresh');
    expect(FakeWebSocket.instances[0].url).not.toContain('stale');
    stream.stop();
  });
});

describe('RunEventStream application ticket provider', () => {
  it('reuses the API client rather than making an unauthenticated request', async () => {
    const fallback = vi.fn();
    const provider = vi.fn(async () => 'capability-from-existing-api-client');
    const stream = new RunEventStream('run-1', {
      apiKey: 'legacy-key',
      streamTickets: true,
      ticketProvider: provider,
      fetchImpl: fallback as unknown as typeof fetch,
      websocketImpl: FakeWebSocket as unknown as typeof WebSocket,
    });
    stream.start();
    await vi.waitFor(() => expect(FakeWebSocket.instances).toHaveLength(1));
    expect(provider).toHaveBeenCalledWith('websocket');
    expect(fallback).not.toHaveBeenCalled();
    expect(FakeWebSocket.instances[0].url).toContain('stream_ticket=capability-from-existing-api-client');
    expect(FakeWebSocket.instances[0].url).not.toContain('legacy-key');
    stream.stop();
  });

  it('does not retry authorization-denied API adapter requests', async () => {
    const provider = vi.fn(async () => { throw Object.assign(new Error('unauthorized'), { status: 401 }); });
    const stream = new RunEventStream('run-1', {
      streamTickets: true,
      ticketProvider: provider,
      websocketImpl: FakeWebSocket as unknown as typeof WebSocket,
    });
    const errors: string[] = [];
    stream.subscribe({ onError: (err) => errors.push(err.message) });
    stream.start();
    await vi.waitFor(() => expect(stream.getStatus()).toBe('closed'));
    expect(provider).toHaveBeenCalledTimes(1);
    expect(errors).toEqual(['stream ticket authorization required']);
    expect(FakeWebSocket.instances).toHaveLength(0);
    stream.stop();
  });
});

describe('run event log secret redaction', () => {
  it('removes proxy URL userinfo even without a query string', () => {
    const input = 'transport http://operator:SENSITIVE_PROXY_CANARY@proxy.invalid:8080 failed; ' +
      'wss://api-user:WS_SECRET_CANARY@stream.invalid/events';
    const result = sanitizeRunLogText(input);
    expect(result).not.toContain('SENSITIVE_PROXY_CANARY');
    expect(result).not.toContain('WS_SECRET_CANARY');
    expect(result).toContain('http://[REDACTED]@proxy.invalid:8080');
    expect(result).toContain('wss://[REDACTED]@stream.invalid/events');
  });

  it('removes WS/SSE query strings and API credentials from worker text', () => {
    const message = [
      'failed wss://example.net/api/v1/workflows/runs/r1/ws?api_key=very-secret&after=5',
      'Authorization: Bearer super-secret-token',
      'X-API-Key: header-secret',
      'stream_ticket=ephemeral-secret',
      'token=other-secret',
      '{"access_token":"json-secret"}',
    ].join(' ');
    const redacted = sanitizeRunLogText(message);
    for (const secret of ['very-secret', 'super-secret-token', 'header-secret',
      'ephemeral-secret', 'other-secret', 'json-secret']) {
      expect(redacted).not.toContain(secret);
    }
    expect(redacted).toContain('?[REDACTED]');
    expect(redacted).toContain('Authorization: [REDACTED]');
    expect(redacted).toContain('stream_ticket=[REDACTED]');
  });

  it('redacts server event messages while preserving lifecycle correlation', () => {
    const event = sagaEventToLogEvent({
      id: 12, run_id: 'run-1', aggregate_id: 'task-1',
      aggregate_type: 'task', event: 'task.failed',
      payload: {error: 'https://secret.dev/path?stream_ticket=bad-token&after=10'},
    });
    expect(event.id).toBe('saga-12');
    expect(event.run_id).toBe('run-1');
    expect(event.task_id).toBe('task-1');
    expect(event.level).toBe('error');
    expect(event.message).not.toContain('bad-token');
    expect(event.message).toContain('?[REDACTED]');
  });

  it('does not remove harmless transition and diagnostic context', () => {
    expect(sanitizeRunLogText('task.completed n3: summary ok')).toBe('task.completed n3: summary ok');
  });
});
