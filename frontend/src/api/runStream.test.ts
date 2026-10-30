import { afterEach, describe, expect, it, vi } from 'vitest';

import {
  RunEventStream,
  parseSseData,
  parseWebSocketFrame,
  runEventSourceUrl,
  runWebSocketUrl,
  sagaEventToLogEvent,
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
