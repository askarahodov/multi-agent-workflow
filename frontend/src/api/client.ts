/**
 * Typed persistence API client.
 *
 * `createApiClient` is the single entry point: it returns an `ApiAdapter`
 * wired to either the in-memory mock (offline dev, default) or the real HTTP
 * adapter (live orchestration server). Callers (T2 canvas, T3 panels, tests)
 * depend only on the `ApiAdapter` surface, never on the concrete backend.
 */

import { HttpAdapter } from './httpAdapter';
import { MockAdapter } from './mockAdapter';
import type { ApiAdapter } from './types';

export const DEFAULT_BASE_URL = '/api/v1';

export type { ApiAdapter } from './types';
export { ProblemDetailsError } from './httpAdapter';
export { MockAdapter } from './mockAdapter';
export { HttpAdapter } from './httpAdapter';
export type {
  AgentDefinitionRef,
  CreateVersionRequest,
  CreateWorkflowRequest,
  CursorPage,
  CursorParams,
  ModelProfileRef,
  ProblemDetails,
  RunCreateRequest,
  RunResponse,
  TaskResponse,
  ToolPolicyRef,
  UpdateWorkflowRequest,
  WorkflowDefinitionDTO,
  WorkflowDefinitionId,
  WorkflowVersionDTO,
} from './types';

export interface ApiClientOptions {
  /**
   * Use the in-memory mock adapter (offline dev / unit tests).
   *
   * Defaults to `false`: the live application talks to the real backend over
   * HTTP (the integration path). Opt into the mock explicitly for offline
   * development and offline/runtime-less tests (ADR-101 §8).
   */
  mock?: boolean;
  /** Base path e.g. `/api/v1` (used by the HTTP adapter). */
  baseUrl?: string;
  /** Optional Bearer token (used by the HTTP adapter). */
  token?: string;
  /** Injectable fetch (HTTP adapter; used to mock the network in tests). */
  fetchImpl?: typeof fetch;
  /** Provide a fully custom adapter; overrides every other option. */
  adapter?: ApiAdapter;
}

export function createApiClient(options: ApiClientOptions = {}): ApiAdapter {
  if (options.adapter) return options.adapter;
  if (options.mock === true) return new MockAdapter();
  return new HttpAdapter({
    baseUrl: options.baseUrl ?? DEFAULT_BASE_URL,
    token: options.token,
    fetchImpl: options.fetchImpl,
  });
}