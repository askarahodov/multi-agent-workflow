/**
 * Canonical entry point for the frontend data layer.
 *
 * Import everything from `@/api` (or `../api`): the adapter factory, the
 * `ApiAdapter` interface and its DTOs, and the run-stream helpers. Do not
 * import `./client`, `./httpAdapter`, `./mockAdapter` or `./runStream`
 * directly from feature code — they are implementation modules of this barrel.
 *
 *   const api = createApiAdapter();          // live HTTP backend
 *   const api = createApiAdapter({ mock: true });  // offline / unit tests
 */

export {
  createApiClient as createApiAdapter,
  DEFAULT_BASE_URL,
  ProblemDetailsError,
} from './client';

export type { ApiClientOptions as ApiAdapterOptions } from './client';
export type { ApiAdapter } from './types';

/**
 * Test-only escape hatches.
 *
 * `MockAdapter` and `HttpAdapter` are concrete implementations. Prefer
 * `createApiAdapter({ mock: true })` / `createApiAdapter({ fetchImpl })`;
 * these exports exist so existing tests can assert on instances and seeds.
 */
export { MockAdapter } from './mockAdapter';
export { HttpAdapter } from './httpAdapter';

export {
  RunEventStream,
  StreamAuthenticationError,
  runWebSocketUrl,
  runEventSourceUrl,
  sagaEventToLogEvent,
  parseWebSocketFrame,
  parseSseData,
  toWebSocketBase,
  sanitizeRunLogText,
} from './runStream';
export type {
  SagaRunEvent,
  StreamStatus,
  RunStreamOptions,
  RunStreamListener,
} from './runStream';

export type * from './types';
