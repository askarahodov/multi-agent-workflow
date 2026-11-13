/**
 * Live run-event stream (WebSocket-first, SSE fallback) for the agent log and
 * run/task monitor.
 *
 * The orchestration server publishes every run/task/attempt state transition to
 * a run-scoped channel (ADR-101 §5.3, ADR-106):
 *
 *   WS   /api/v1/workflows/runs/{run_id}/ws?after=<id>
 *   SSE  /api/v1/workflows/runs/{run_id}/events?after=<id>
 *
 * Delivery is ordered and resumable from the last seen integer event id, so a
 * client that drops its connection (network blip, laptop sleep, agent crash) can
 * reconnect and continue exactly where it left off — never missing an event and
 * never replaying a duplicate.
 *
 * This module owns the transport concerns (URL building, framing, resume,
 * exponential-backoff reconnect, SSE fallback) and maps the raw saga events
 * into the UI's `RunLogEvent` shape. It is deliberately free of React so the
 * reconnect / resume logic can be unit-tested against injected transports.
 */

import type { RunLogEvent } from './types';

export type StreamStatus = 'idle' | 'connecting' | 'open' | 'reconnecting' | 'closed';

export class StreamAuthenticationError extends Error {}

/** A serialized saga event, exactly as delivered by the server transports. */
export interface SagaRunEvent {
  id: number;
  run_id: string;
  event: string;
  aggregate_type?: string;
  aggregate_id?: string;
  payload?: Record<string, unknown>;
  created_at?: string;
}

export interface RunStreamOptions {
  /** Base API path, e.g. `/api/v1` (default) or an absolute URL. */
  baseUrl?: string;
  /**
   * API key. Browsers cannot attach custom headers to a WebSocket handshake, so
   * this is sent as the `api_key` query parameter (matching the server's
   * `_ws_read_authorized`); the SSE transport sends the same query parameter.
   */
  apiKey?: string;
  /** Opt-in: use fresh server-issued one-time capabilities for streaming. */
  streamTickets?: boolean;
  /** Injectable fetch for standalone ticket issuance. */
  fetchImpl?: typeof fetch;
  /** Use the application's already-authenticated REST client when supplied. */
  ticketProvider?: (transport: 'sse' | 'websocket') => Promise<string>;
  /** Injectable transport constructors (tests / non-browser runtimes). */
  websocketImpl?: (typeof WebSocket) | null;
  eventSourceImpl?: (typeof EventSource) | null;
  /** Resume from this safe monotonically increasing server event ID (manual reconnect). */
  afterEventId?: number;
  /** Set false to open a single connection with no automatic reconnect. */
  reconnect?: boolean;
  /** Max consecutive reconnect attempts before the stream gives up (default 6). */
  maxRetries?: number;
  /** Backoff base and cap in milliseconds. */
  baseDelayMs?: number;
  maxDelayMs?: number;
  /** Deterministic jitter source (tests); defaults to `Math.random`. */
  random?: () => number;
  /** Injectable timers (tests). */
  setTimeoutImpl?: (handler: () => void, timeout: number) => number;
  clearTimeoutImpl?: (handle: number) => void;
}

export interface RunStreamListener {
  onEvent?(event: RunLogEvent): void;
  onStatus?(status: StreamStatus): void;
  onError?(error: Error): void;
}

/* -------------------------------------------------------------------------- *
 * URL + framing helpers (pure, unit-tested directly).
 * -------------------------------------------------------------------------- */

/** Convert an http(s) base URL to its ws(s) equivalent, preserving the path. */
export function toWebSocketBase(baseUrl: string, origin?: string): string {
  if (/^wss?:\/\//i.test(baseUrl)) return baseUrl.replace(/\/$/, '');
  if (/^https?:\/\//i.test(baseUrl)) {
    return baseUrl.replace(/^http/i, 'ws').replace(/\/$/, '');
  }
  // Relative base: resolve against the current origin.
  const base = origin ?? (typeof location !== 'undefined' ? location.origin : '');
  const wsOrigin = base.replace(/^http/i, 'ws');
  const path = baseUrl.startsWith('/') ? baseUrl : `/${baseUrl}`;
  return `${wsOrigin}${path}`.replace(/\/$/, '');
}

export interface StreamUrlParams {
  after?: number;
  apiKey?: string;
  streamTicket?: string;
}

/** Build the run-scoped WebSocket URL (resumable from `after`). */
export function runWebSocketUrl(
  baseUrl: string,
  runId: string,
  params: StreamUrlParams = {},
  origin?: string,
): string {
  const url = new URL(
    `${toWebSocketBase(baseUrl, origin)}/workflows/runs/${encodeURIComponent(runId)}/ws`,
  );
  if (params.after && params.after > 0) url.searchParams.set('after', String(params.after));
  if (params.apiKey) url.searchParams.set('api_key', params.apiKey);
  if (params.streamTicket) url.searchParams.set('stream_ticket', params.streamTicket);
  return url.toString();
}

/** Build the run-scoped SSE URL (resumable from `after`). */
export function runEventSourceUrl(
  baseUrl: string,
  runId: string,
  params: StreamUrlParams = {},
): string {
  const path = `${baseUrl.replace(/\/$/, '')}/workflows/runs/${encodeURIComponent(runId)}/events`;
  const query = new URLSearchParams();
  if (params.after && params.after > 0) query.set('after', String(params.after));
  if (params.apiKey) query.set('api_key', params.apiKey);
  if (params.streamTicket) query.set('stream_ticket', params.streamTicket);
  const qs = query.toString();
  return qs ? `${path}?${qs}` : path;
}

/**
 * Parse one WebSocket text frame. Returns the saga event, `null` for a
 * keep-alive ping, or `undefined` for anything unrecognised (ignored).
 */
export function parseWebSocketFrame(raw: unknown): SagaRunEvent | null | undefined {
  let frame: Record<string, unknown>;
  if (typeof raw === 'string') {
    try {
      frame = JSON.parse(raw) as Record<string, unknown>;
    } catch {
      return undefined;
    }
  } else if (raw && typeof raw === 'object') {
    frame = raw as Record<string, unknown>;
  } else {
    return undefined;
  }
  if (frame.type === 'ping') return null;
  if (frame.type === 'run_event' && typeof frame.event === 'string') {
    return frame as unknown as SagaRunEvent;
  }
  return undefined;
}

/** Parse one SSE `data:` payload into a saga event (null when unparseable). */
export function parseSseData(raw: string): SagaRunEvent | null {
  try {
    const parsed = JSON.parse(raw) as SagaRunEvent;
    return typeof parsed.event === 'string' ? parsed : null;
  } catch {
    return null;
  }
}

/* -------------------------------------------------------------------------- *
 * Saga event → UI log event mapping (pure, unit-tested).
 * -------------------------------------------------------------------------- */

interface EventMapping {
  kind: RunLogEvent['kind'];
  level: RunLogEvent['level'];
}

const EVENT_MAP: Record<string, EventMapping> = {
  'run.launched': { kind: 'run', level: 'info' },
  'run.completed': { kind: 'run', level: 'success' },
  'run.failed': { kind: 'run', level: 'error' },
  'run.release_approved': { kind: 'run', level: 'success' },
  'task.created': { kind: 'task', level: 'info' },
  'task.claimed': { kind: 'task', level: 'info' },
  'task.completed': { kind: 'task', level: 'success' },
  'task.failed': { kind: 'task', level: 'error' },
  'task.blocked': { kind: 'task', level: 'warn' },
  'task.retry_scheduled': { kind: 'task', level: 'warn' },
  'task.retry_window_opened': { kind: 'task', level: 'warn' },
  'task.qa_attested': { kind: 'task', level: 'success' },
  'task.upstream_verified': { kind: 'task', level: 'success' },
  'task.recovery_quarantined': { kind: 'task', level: 'warn' },
  'attempt.started': { kind: 'attempt', level: 'info' },
  'attempt.completed': { kind: 'attempt', level: 'success' },
  'attempt.failed': { kind: 'attempt', level: 'error' },
  'attempt.verification_failed': { kind: 'attempt', level: 'error' },
  'attempt.git_reported': { kind: 'attempt', level: 'success' },
  'workspace.created': { kind: 'info', level: 'info' },
};

/**
 * Every saga event type the client knows how to render. Servers may frame an
 * SSE event with an ``event: <type>`` line, which browsers dispatch only to
 * listeners registered for that exact type — never to ``onmessage``.
 */
export const SAGA_EVENT_TYPES: readonly string[] = Object.keys(EVENT_MAP);

/**
 * Log events are not a trusted secret-free input: worker errors can contain
 * request URLs and copied Authorization headers. Strip credentials at the
 * presentation boundary, including in events received after reconnect.
 * The raw structured event is never persisted in UI state.
 */
export function sanitizeRunLogText(value: string): string {
  return value
    // A proxy/transport error may contain a URL with user:password@host
    // even if there is no query string. Never let Basic proxy credentials
    // reach the stream/log UI or a React error boundary.
    .replace(/((?:https?|wss?):\\/\\/)[^\\s/"'<>?@]*@/gi, '$1[REDACTED]@')
    // Query strings are routinely copied from failed WS/SSE requests. Remove
    // the whole query rather than guessing which parameter may be sensitive.
    .replace(/(https?:\/\/[^\s"'<>?]+)\?[^\s"'<>]*/gi, '$1?[REDACTED]')
    .replace(/(wss?:\/\/[^\s"'<>?]+)\?[^\s"'<>]*/gi, '$1?[REDACTED]')
    // JSON credential fields from tools and provider errors.
    .replace(/(["'](?:api_key|stream_ticket|access_token|refresh_token|authorization|x-api-key|password|secret|token)["']\s*:\s*["'])[^"']*(["'])/gi, '$1[REDACTED]$2')
    .replace(/\b(Authorization|X-API-Key)\s*[:=]\s*(?:Bearer\s+)?[^\s,;]+/gi, '$1: [REDACTED]')
    .replace(/\bBearer\s+[A-Za-z0-9._~+\x2f=:-]+/gi, 'Bearer [REDACTED]')
    .replace(/\b(api_key|stream_ticket|access_token|refresh_token|password|secret|token)\s*=\s*[^\s&;,\]}"']+/gi, '$1=[REDACTED]');
}

/** A short human-readable suffix drawn from the event payload (may be empty). */
export function eventDetail(event: SagaRunEvent): string {
  const payload = event.payload ?? {};
  const candidate = payload.summary ?? payload.message ?? payload.reason ?? payload.error;
  return typeof candidate === 'string' ? sanitizeRunLogText(candidate) : '';
}

/**
 * Map a raw saga event to the UI's `RunLogEvent`. Always returns a value so no
 * lifecycle transition is silently dropped from the live feed.
 */
export function sagaEventToLogEvent(event: SagaRunEvent): RunLogEvent {
  const mapping = EVENT_MAP[event.event] ?? { kind: 'info', level: 'info' };
  const detail = eventDetail(event);
  const subject = event.aggregate_id ? ` ${event.aggregate_id}` : '';
  const message = detail
    ? `${event.event}${subject}: ${detail}`
    : `${event.event}${subject}`;
  return {
    id: `saga-${event.id}`,
    at: event.created_at ?? new Date().toISOString(),
    kind: mapping.kind,
    level: mapping.level,
    message: sanitizeRunLogText(message),
    run_id: event.run_id,
    task_id: event.aggregate_type === 'task' ? event.aggregate_id : undefined,
  };
}

/* -------------------------------------------------------------------------- *
 * The stream itself.
 * -------------------------------------------------------------------------- */

/**
 * Connects to a run's event channel, mapping every transition into a
 * `RunLogEvent` and reconnecting (resuming from the last seen id) after a drop.
 *
 * Transport selection: WebSocket when available, otherwise Server-Sent Events.
 * The chosen transport is recorded in `transport` for the UI and tests.
 */
export class RunEventStream {
  private readonly runId: string;
  private readonly opts: Required<
    Pick<
      RunStreamOptions,
      | 'baseUrl'
      | 'reconnect'
      | 'maxRetries'
      | 'baseDelayMs'
      | 'maxDelayMs'
      | 'random'
      | 'setTimeoutImpl'
      | 'clearTimeoutImpl'
    >
  > &
    RunStreamOptions;

  private socket: WebSocket | null = null;
  private source: EventSource | null = null;
  /** Named SSE listeners registered on the current EventSource (for teardown). */
  private sourceListeners: Array<{ type: string; handler: EventListener }> = [];
  private listener: RunStreamListener = {};
  private status: StreamStatus = 'idle';
  private lastEventId = 0;
  private retries = 0;
  private stopped = true;
  /** Invalidates outstanding asynchronous ticket requests after stop/start. */
  private generation = 0;
  private retryTimer: number | null = null;
  /** A failed WebSocket handshake pins retries to fresh-ticket SSE until restart. */
  private preferSse = false;

  /** Which transport is actually in use (`websocket` | `sse` | `none`). */
  transport: 'websocket' | 'sse' | 'none' = 'none';

  constructor(runId: string, options: RunStreamOptions = {}) {
    this.runId = runId;
    this.lastEventId = Number.isSafeInteger(options.afterEventId) && (options.afterEventId ?? 0) > 0
      ? options.afterEventId!
      : 0;
    this.opts = {
      baseUrl: options.baseUrl ?? '/api/v1',
      reconnect: options.reconnect ?? true,
      maxRetries: options.maxRetries ?? 6,
      baseDelayMs: options.baseDelayMs ?? 500,
      maxDelayMs: options.maxDelayMs ?? 15_000,
      random: options.random ?? Math.random,
      setTimeoutImpl:
        options.setTimeoutImpl ??
        ((handler, timeout) => globalThis.setTimeout(handler, timeout) as unknown as number),
      clearTimeoutImpl:
        options.clearTimeoutImpl ??
        ((handle) => globalThis.clearTimeout(handle)),
      ...options,
    };
  }

  getStatus(): StreamStatus {
    return this.status;
  }

  getLastEventId(): number {
    return this.lastEventId;
  }

  /** Register (or replace) the listener. */
  subscribe(listener: RunStreamListener): void {
    this.listener = listener;
  }

  /** Open (or reopen) the stream from the current resume cursor. */
  start(): void {
    this.generation++;
    this.stopped = false;
    this.retries = 0;
    this.preferSse = false;
    if (this.retryTimer !== null) {
      this.opts.clearTimeoutImpl(this.retryTimer);
      this.retryTimer = null;
    }
    this.teardownTransport();
    void this.openWebSocket();
  }

  /**
   * Detach from every transport and stop reconnecting.
   *
   * This is a **user-initiated** teardown (switching runs, unmounting the
   * page), so it is deliberately not announced through ``onStatus``: consumers
   * map the terminal ``closed`` status to a degraded polling fallback, and
   * broadcasting it here would drop the live feed on every run switch. Genuine
   * failures still emit ``closed`` via ``scheduleReconnect``.
   */
  stop(): void {
    this.generation++;
    this.stopped = true;
    if (this.retryTimer !== null) {
      this.opts.clearTimeoutImpl(this.retryTimer);
      this.retryTimer = null;
    }
    this.teardownTransport();
    // Terminal state without a listener notification (see docstring above).
    this.status = 'closed';
  }

  private setStatus(status: StreamStatus): void {
    if (this.status !== status) {
      this.status = status;
      this.listener.onStatus?.(status);
    }
  }

  private teardownTransport(): void {
    if (this.socket) {
      const socket = this.socket;
      this.socket = null;
      socket.onopen = null;
      socket.onmessage = null;
      socket.onerror = null;
      socket.onclose = null;
      try {
        socket.close();
      } catch {
        // Already closed / never opened.
      }
    }
    if (this.source) {
      const source = this.source;
      this.source = null;
      if (typeof source.removeEventListener === 'function') {
        for (const { type, handler } of this.sourceListeners) {
          source.removeEventListener(type, handler);
        }
      }
      this.sourceListeners = [];
      source.onopen = null;
      source.onmessage = null;
      source.onerror = null;
      try {
        source.close();
      } catch {
        // Already closed.
      }
    }
  }

  private websocketCtor(): typeof WebSocket | undefined {
    const injected = this.opts.websocketImpl;
    if (injected !== undefined) return injected ?? undefined;
    return (globalThis as { WebSocket?: typeof WebSocket }).WebSocket;
  }

  private eventSourceCtor(): typeof EventSource | undefined {
    const injected = this.opts.eventSourceImpl;
    if (injected !== undefined) return injected ?? undefined;
    return (globalThis as { EventSource?: typeof EventSource }).EventSource;
  }

  private async obtainStreamTicket(transport: 'sse' | 'websocket'): Promise<string> {
    if (this.opts.ticketProvider) {
      try {
        const ticket = await this.opts.ticketProvider(transport);
        if (typeof ticket !== 'string' || !ticket) {
          throw new Error('invalid stream ticket response');
        }
        return ticket;
      } catch (error) {
        // ProblemDetailsError from HttpAdapter exposes status but not secrets.
        if (error instanceof StreamAuthenticationError ||
            (typeof error === 'object' && error !== null && 'status' in error &&
             (error.status === 401 || error.status === 403))) {
          throw new StreamAuthenticationError('stream ticket authorization required');
        }
        throw error;
      }
    }
    const fetchTicket = this.opts.fetchImpl ?? globalThis.fetch.bind(globalThis);
    const response = await fetchTicket(
      `${this.opts.baseUrl.replace(/\/$/, '')}/workflows/runs/${encodeURIComponent(this.runId)}/stream-tickets`,
      {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          ...(this.opts.apiKey ? { 'X-API-Key': this.opts.apiKey } : {}),
        },
        body: JSON.stringify({ transport }),
        cache: 'no-store',
      },
    );
    if (response.status === 401 || response.status === 403) {
      throw new StreamAuthenticationError('stream ticket authorization required');
    }
    if (!response.ok) throw new Error('stream ticket issuance failed');
    const body = await response.json() as { ticket?: unknown };
    if (typeof body.ticket !== 'string' || !body.ticket) {
      throw new Error('invalid stream ticket response');
    }
    return body.ticket;
  }

  private async openWebSocket(): Promise<void> {
    const generation = this.generation;
    const Ctor = this.websocketCtor();
    if (!Ctor) {
      // No WebSocket in this runtime — fall back to SSE.
      this.preferSse = true;
      void this.openEventSource();
      return;
    }
    this.teardownTransport();
    this.transport = 'websocket';
    this.setStatus(this.retries > 0 ? 'reconnecting' : 'connecting');
    let ticket: string | undefined;
    if (this.opts.streamTickets) {
      try {
        ticket = await this.obtainStreamTicket('websocket');
        if (this.stopped || generation !== this.generation) return;
      } catch (error) {
        if (this.stopped || generation !== this.generation) return;
        if (error instanceof StreamAuthenticationError) {
          this.listener.onError?.(error);
          this.setStatus('closed');
          return;
        }
        this.listener.onError?.(new Error('stream ticket issuance failed'));
        this.scheduleReconnect();
        return;
      }
    }
    const url = runWebSocketUrl(this.opts.baseUrl, this.runId, {
      after: this.lastEventId,
      apiKey: this.opts.streamTickets ? undefined : this.opts.apiKey,
      streamTicket: ticket,
    });
    let socket: WebSocket;
    try {
      socket = new Ctor(url);
    } catch {
      this.listener.onError?.(new Error('run event stream WebSocket connection failed'));
      if (this.eventSourceCtor()) {
        this.preferSse = true;
        void this.openEventSource();
      } else {
        this.scheduleReconnect();
      }
      return;
    }
    this.socket = socket;
    let opened = false;
    socket.onopen = () => {
      if (this.stopped || this.socket !== socket) return;
      opened = true;
      this.retries = 0;
      this.setStatus('open');
    };
    socket.onmessage = (message: MessageEvent) => {
      if (this.stopped || this.socket !== socket) return;
      const event = parseWebSocketFrame(message.data);
      if (!event) return; // ping or unrecognised frame
      this.deliver(event);
    };
    socket.onerror = () => {
      if (this.stopped || this.socket !== socket) return;
      // `onclose` always follows `onerror`; reconnect is handled there so a
      // single drop never schedules two retries.
      this.listener.onError?.(new Error('run event stream error'));
    };
    socket.onclose = () => {
      if (this.stopped || this.socket !== socket) return;
      this.teardownTransport();
      if (!opened && this.eventSourceCtor()) {
        // Proxies often reject the WebSocket upgrade asynchronously. A browser
        // does not throw from new WebSocket(url) in that case. Switch to SSE
        // with its OWN freshly issued capability, never reuse the WS ticket.
        this.preferSse = true;
        void this.openEventSource();
      } else {
        this.scheduleReconnect();
      }
    };
  }

  private async openEventSource(): Promise<void> {
    const generation = this.generation;
    const Ctor = this.eventSourceCtor();
    if (!Ctor) {
      // Neither transport exists in this runtime (e.g. jsdom without polyfills).
      this.transport = 'none';
      this.listener.onError?.(new Error('no streaming transport available'));
      this.setStatus('closed');
      return;
    }
    this.teardownTransport();
    this.transport = 'sse';
    this.setStatus(this.retries > 0 ? 'reconnecting' : 'connecting');
    let ticket: string | undefined;
    if (this.opts.streamTickets) {
      try {
        ticket = await this.obtainStreamTicket('sse');
        if (this.stopped || generation !== this.generation) return;
      } catch (error) {
        if (this.stopped || generation !== this.generation) return;
        if (error instanceof StreamAuthenticationError) {
          this.listener.onError?.(error);
          this.setStatus('closed');
          return;
        }
        this.listener.onError?.(new Error('stream ticket issuance failed'));
        this.scheduleReconnect();
        return;
      }
    }
    const url = runEventSourceUrl(this.opts.baseUrl, this.runId, {
      after: this.lastEventId,
      apiKey: this.opts.streamTickets ? undefined : this.opts.apiKey,
      streamTicket: ticket,
    });
    let source: EventSource;
    try {
      source = new Ctor(url);
    } catch {
      this.listener.onError?.(new Error('run event stream SSE connection failed'));
      this.scheduleReconnect();
      return;
    }
    this.source = source;
    source.onopen = () => {
      if (this.stopped || this.source !== source) return;
      this.retries = 0;
      this.setStatus('open');
    };
    const handleMessage = (message: MessageEvent) => {
      if (this.stopped || this.source !== source) return;
      const event = parseSseData(typeof message.data === 'string' ? message.data : '');
      if (event) this.deliver(event);
    };
    // Default `message` frames (the current server framing) reach `onmessage`.
    source.onmessage = handleMessage;
    // Legacy/alternate servers may name the frame (`event: <type>`); a named
    // frame is dispatched ONLY to listeners for that exact type, never to
    // `onmessage`. Registering per-type listeners keeps the fallback working
    // across a rolling upgrade where client and server frames disagree.
    if (typeof source.addEventListener === 'function') {
      for (const type of SAGA_EVENT_TYPES) {
        source.addEventListener(type, handleMessage as EventListener);
        this.sourceListeners.push({ type, handler: handleMessage as EventListener });
      }
    }
    source.onerror = () => {
      if (this.stopped || this.source !== source) return;
      // EventSource would otherwise silently reconnect with the CONSUMED
      // one-time ticket; close and obtain a new SSE ticket for every attempt.
      this.teardownTransport();
      this.scheduleReconnect();
    };
  }

  private scheduleReconnect(): void {
    if (!this.opts.reconnect) {
      this.setStatus('closed');
      return;
    }
    if (this.retries >= this.opts.maxRetries) {
      this.listener.onError?.(new Error('run event stream exhausted reconnect attempts'));
      this.setStatus('closed');
      return;
    }
    const attempt = this.retries++;
    const exponential = Math.min(this.opts.baseDelayMs * 2 ** attempt, this.opts.maxDelayMs);
    // Full jitter keeps a fleet of reconnecting UIs from stampeding the server.
    const delay = Math.round(exponential * (0.5 + 0.5 * this.opts.random()));
    this.setStatus('reconnecting');
    this.retryTimer = this.opts.setTimeoutImpl(() => {
      this.retryTimer = null;
      if (this.stopped) return;
      if (this.preferSse) {
        void this.openEventSource();
      } else {
        void this.openWebSocket();
      }
    }, delay);
  }

  private deliver(event: SagaRunEvent): void {
    // Transports may replay the resume boundary after reconnect, or a stale
    // connection may deliver buffered frames. Never emit duplicate, out-of-order,
    // cross-run, or malformed IDs to the monitor and never move the cursor back.
    if (event.run_id !== this.runId ||
        !Number.isSafeInteger(event.id) || event.id <= this.lastEventId) return;
    this.lastEventId = event.id;
    this.listener.onEvent?.(sagaEventToLogEvent(event));
  }
}
