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

/* -------------------------------------------------------------------------- *
 * MVP v1 platform domain (ADR-101 §5.3): projects, workspaces, contracts,
 * runtime agents and task attempts. These mirror the orchestration-server
 * OpenAPI contract so the Runs / Board / Conveyor / Task-card / Agent-log
 * sections can operate against the real backend (or the mock in dev).
 * -------------------------------------------------------------------------- */

export interface ProjectCreate {
  name: string;
  description?: string;
  settings?: Record<string, unknown>;
}

export interface ProjectResponse {
  id: string;
  name: string;
  description?: string;
  settings?: Record<string, unknown>;
  version: number;
  created_at?: string;
  updated_at?: string;
}

export interface WorkspaceCreate {
  project_id: string;
  name: string;
  path?: string;
  settings?: Record<string, unknown>;
}

export interface WorkspaceResponse {
  id: string;
  project_id: string;
  name: string;
  path?: string;
  settings?: Record<string, unknown>;
  version: number;
  created_at?: string;
}

export interface ContractCreate {
  project_id?: string;
  name: string;
  schema: Record<string, unknown>;
  description?: string;
}

export interface ContractResponse {
  id: string;
  project_id?: string;
  name: string;
  schema: Record<string, unknown>;
  description?: string;
  version: number;
  created_at?: string;
}

/** A runtime agent registered with the orchestration server (`/agents`). */
export interface AgentResponse {
  id: string;
  name: string;
  status: string;
  agent_metadata?: Record<string, unknown>;
  version: number;
  created_at?: string;
}

export interface AgentRegister {
  name: string;
  metadata?: Record<string, unknown>;
}

export interface AttemptResponse {
  id: string;
  task_id: string;
  attempt_number: number;
  agent_id?: string;
  status: string;
  input_data?: Record<string, unknown>;
  output_data?: Record<string, unknown>;
  verification_result?: Record<string, unknown>;
  error?: string;
  started_at?: string;
  completed_at?: string;
  version: number;
}

export interface ClaimRequest {
  agent_id: string;
}

export interface SubmitRequest {
  output: Record<string, unknown>;
}

export interface FailRequest {
  error: string;
}

export interface BlockRequest {
  reason: string;
}

/** Admin-only recovery API: no old-attempt replay capability is exposed. */
export type ReconciliationDecision =
  | 'UNKNOWN'
  | 'CONFIRMED_SIDE_EFFECT'
  | 'CONFIRMED_NO_SIDE_EFFECT';

export interface ReconciliationRequest {
  decision: ReconciliationDecision;
  evidence_ref: string;
  evidence_sha256: string;
}

export interface ReconciliationResponse extends ReconciliationRequest {
  task_id: string;
  operator_subject: string;
  decided_at: string;
}

export interface InterruptedToolLedgerEntry {
  call_ref: string;
  tool: string;
  state: 'CLAIMED' | 'SUCCEEDED' | 'DENIED';
}

export interface InterruptedAttemptLedger {
  attempt_id: string;
  record_status: 'RECORDS' | 'NO_RECORDS';
  entries: InterruptedToolLedgerEntry[];
}

export interface RecoveryLedgerReport {
  task_id: string;
  ledger_status: 'AVAILABLE';
  attempts: InterruptedAttemptLedger[];
}

/** Combined run + task snapshot used by the live agent log (polling diff). */
export interface RunSnapshot {
  run: RunResponse;
  tasks: TaskResponse[];
}

/**
 * A single live-log event derived by diffing consecutive `RunSnapshot`s.
 * The MVP live log uses short-interval polling of the existing
 * `getRun` / `listRunTasks` / `getTask` endpoints (no dedicated SSE stream
 * endpoint exists yet — ADR-101 §8 migration allows polling); this type
 * normalises run/task lifecycle transitions into one event shape.
 */
export interface RunLogEvent {
  id: string;
  at: string;
  kind: 'run' | 'task' | 'attempt' | 'info';
  level: 'info' | 'success' | 'warn' | 'error';
  message: string;
  run_id: string;
  task_id?: string;
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
  listRuns(
    params?: CursorParams & { projectId?: string; status?: string },
  ): Promise<CursorPage<RunResponse>>;
  getRun(runId: string): Promise<RunResponse>;
  listRunTasks(runId: string, params?: CursorParams): Promise<CursorPage<TaskResponse>>;

  /* MVP v1 platform domain — projects / workspaces / agents / attempts. */
  listProjects(): Promise<ProjectResponse[]>;
  createProject(request: ProjectCreate): Promise<ProjectResponse>;
  listWorkspaces(projectId?: string): Promise<WorkspaceResponse[]>;
  createWorkspace(request: WorkspaceCreate): Promise<WorkspaceResponse>;
  listAgents(): Promise<AgentResponse[]>;
  registerAgent(request: AgentRegister): Promise<AgentResponse>;
  getTask(taskId: string): Promise<TaskResponse>;
  listTaskAttempts(taskId: string): Promise<AttemptResponse[]>;
  claimTask(taskId: string, request: ClaimRequest): Promise<AttemptResponse>;
  submitTask(
    taskId: string,
    attemptId: string,
    request: SubmitRequest,
    agentId: string,
  ): Promise<AttemptResponse>;
  failTask(
    taskId: string,
    attemptId: string,
    request: FailRequest,
    agentId: string,
  ): Promise<AttemptResponse>;
  blockTask(taskId: string, request: BlockRequest, agentId: string): Promise<TaskResponse>;

  /** Requires admin access on the orchestration server. */
  listRecoveryQuarantine(): Promise<TaskResponse[]>;
  getRecoveryReconciliation(taskId: string): Promise<ReconciliationResponse>;
  getRecoveryLedger(taskId: string): Promise<RecoveryLedgerReport>;
  attestRecovery(taskId: string, request: ReconciliationRequest): Promise<ReconciliationResponse>;

  /** Snapshot the run and its tasks (used by the live agent log poller). */
  getRunSnapshot(runId: string): Promise<RunSnapshot>;
}
