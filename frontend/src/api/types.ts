/**
 * Typed persistence API contract for the workflow editor.
 *
 * Mirrors the approved REST contract (base `/api/v1`) owned by the
 * orchestration server (t_52732c01):
 *
 *   GET    /workflows/definitions
 *   POST   /workflows/definitions
 *   GET    /workflows/definitions/{id}
 *   PUT    /workflows/definitions/{id}
 *   GET    /workflows/definitions/{id}/versions
 *   POST   /workflows/definitions/{id}/versions
 *   GET    /agents/definitions
 *   GET    /model-profiles
 *   GET    /tool-policies
 *
 * Auth is a Bearer (JWT) token. Errors use RFC 9457 Problem Details. List
 * endpoints support cursor-based pagination (`after`, `limit`).
 */

import type { WorkflowDefinition } from '../workflow/types';

export type WorkflowDefinitionId = string;

/** Response body for GET/POST/PUT /workflows/definitions (and its variants). */
export interface WorkflowDefinitionDTO {
  id: WorkflowDefinitionId;
  name: string;
  description?: string;
  /** The canonical workflow document (nodes/edges/metadata). */
  definition: WorkflowDefinition;
  is_active: boolean;
  created_at: string;
  updated_at: string;
  /** Optimistic-lock / revision counter on the mutable entity. */
  version: number;
}

export interface CreateWorkflowRequest {
  name: string;
  description?: string;
  definition: WorkflowDefinition;
}

export interface UpdateWorkflowRequest {
  name?: string;
  description?: string;
  definition?: WorkflowDefinition;
  is_active?: boolean;
}

/** Immutable snapshot returned by /workflows/definitions/{id}/versions. */
export interface WorkflowVersionDTO {
  id: string;
  workflow_definition_id: WorkflowDefinitionId;
  version_number: number;
  definition_snapshot: WorkflowDefinition;
  changelog?: string;
  created_by?: string;
  created_at: string;
}

export interface CreateVersionRequest {
  definition_snapshot: WorkflowDefinition;
  changelog?: string;
}

/** Reference summaries used to populate property-panel selectors (T3). */
export interface AgentDefinitionRef {
  id: string;
  name: string;
  description?: string;
}

export interface ModelProfileRef {
  id: string;
  name: string;
  provider_id?: string;
  model_id?: string;
  display_name?: string;
}

export interface ToolPolicyRef {
  id: string;
  name: string;
  description?: string;
}

/* -------------------------------------------------------------------------- *
 * Workflow-runtime DTOs (ADR-101 §5.3) — owned by the orchestration server.
 * Used to launch a run from a saved workflow definition and to monitor the
 * resulting run/task lifecycle from the Runs panel.
 * -------------------------------------------------------------------------- */

export interface TaskSpec {
  title: string;
  node_id?: string;
  description?: string;
  contract_id?: string;
  input_data?: Record<string, unknown>;
  priority?: number;
}

export interface RunCreateRequest {
  project_id: string;
  workspace_id?: string;
  name: string;
  triggered_by?: string;
  input_data?: Record<string, unknown>;
  retry_policy?: Record<string, unknown>;
  tasks: TaskSpec[];
}

export interface RunResponse {
  id: string;
  project_id: string;
  workspace_id?: string;
  name: string;
  status: string;
  input_data?: Record<string, unknown>;
  output_data?: Record<string, unknown>;
  triggered_by?: string;
  started_at?: string;
  completed_at?: string;
  version: number;
  created_at?: string;
}

export interface TaskResponse {
  id: string;
  workflow_run_id: string;
  node_id?: string;
  title: string;
  description?: string;
  status: string;
  contract_id?: string;
  input_data?: Record<string, unknown>;
  output_data?: Record<string, unknown>;
  priority: number;
  attempt_count: number;
  max_attempts: number;
  assigned_agent_id?: string;
  started_at?: string;
  completed_at?: string;
  version: number;
  created_at?: string;
}

/** Cursor-based pagination parameters: `?after=<cursor>&limit=<n>`. */
export interface CursorParams {
  after?: string;
  limit?: number;
}

export interface CursorPage<T> {
  items: T[];
  /** Opaque cursor for the next page; `null`/absent when there are no more. */
  next_cursor?: string | null;
}

/**
 * RFC 9457 Problem Details. `type`, `title`, `status`, `detail`, `instance`
 * are all optional by spec; servers may additionally include `errors` for
 * field-level validation details.
 */
export interface ProblemDetails {
  type?: string;
  title?: string;
  status?: number;
  detail?: string;
  instance?: string;
  errors?: Array<{ path?: string; message?: string }>;
}

/**
 * The persistence surface consumed by the editor. Both the in-memory mock
 * (offline dev) and the real HTTP adapter implement this interface, so the
 * UI, tests and T2/T3 modules never care which backend is wired in.
 */
export interface ApiAdapter {
  listWorkflows(params?: CursorParams): Promise<CursorPage<WorkflowDefinitionDTO>>;
  getWorkflow(id: WorkflowDefinitionId): Promise<WorkflowDefinitionDTO>;
  createWorkflow(request: CreateWorkflowRequest): Promise<WorkflowDefinitionDTO>;
  updateWorkflow(
    id: WorkflowDefinitionId,
    request: UpdateWorkflowRequest,
  ): Promise<WorkflowDefinitionDTO>;
  listVersions(
    id: WorkflowDefinitionId,
    params?: CursorParams,
  ): Promise<CursorPage<WorkflowVersionDTO>>;
  saveVersion(id: WorkflowDefinitionId, request: CreateVersionRequest): Promise<WorkflowVersionDTO>;
  listAgentDefinitions(params?: CursorParams): Promise<CursorPage<AgentDefinitionRef>>;
  listModelProfiles(params?: CursorParams): Promise<CursorPage<ModelProfileRef>>;
  listToolPolicies(params?: CursorParams): Promise<CursorPage<ToolPolicyRef>>;

  /* Workflow-runtime (ADR-101 §5.3) — launch & monitor runs. */
  launchRun(request: RunCreateRequest): Promise<RunResponse>;
  listRuns(params?: CursorParams): Promise<CursorPage<RunResponse>>;
  getRun(runId: string): Promise<RunResponse>;
  listRunTasks(runId: string, params?: CursorParams): Promise<CursorPage<TaskResponse>>;
}