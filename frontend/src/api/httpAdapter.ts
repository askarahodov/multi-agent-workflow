/**
 * Real HTTP adapter implementing the approved REST contract against the
 * orchestration server (t_52732c01), base path `/api/v1`.
 *
 * Errors are surfaced as RFC 9457 Problem Details via `ProblemDetailsError`
 * (a typed `Error` subclass carrying the full problem document, so callers can
 * branch on `status`, inspect `title`/`detail`, and render field-level details
 * from `problem.errors`).
 */

import type {
  AgentRegister,
  AgentResponse,
  AgentDefinitionRef,
  ApiAdapter,
  AttemptResponse,
  BlockRequest,
  ClaimRequest,
  CreateVersionRequest,
  CreateWorkflowRequest,
  CursorPage,
  CursorParams,
  FailRequest,
  ModelProfileRef,
  ProblemDetails,
  ProjectCreate,
  ProjectResponse,
  ReconciliationRequest,
  ReconciliationResponse,
  RecoveryLedgerReport,
  RunCreateRequest,
  RunResponse,
  RunSnapshot,
  SubmitRequest,
  TaskResponse,
  ToolPolicyRef,
  UpdateWorkflowRequest,
  WorkflowDefinitionDTO,
  WorkflowDefinitionId,
  WorkflowVersionDTO,
  WorkspaceCreate,
  WorkspaceResponse,
} from './types';

/** Thrown by the HTTP adapter for any non-2xx response carrying RFC 9457 body. */
export class ProblemDetailsError extends Error {
  readonly problem: ProblemDetails;
  readonly status: number;

  constructor(problem: ProblemDetails) {
    super(problem.detail ?? problem.title ?? `Request failed (HTTP ${problem.status ?? '?'})`);
    this.name = 'ProblemDetailsError';
    this.problem = problem;
    this.status = problem.status ?? 0;
  }
}

export interface HttpAdapterOptions {
  /** e.g. `/api/v1` or `https://host/api/v1`. */
  baseUrl: string;
  /** Optional Bearer token; set as `Authorization: Bearer <token>`. */
  token?: string;
  /** Injectable fetch (also used by tests to mock the network). */
  fetchImpl?: typeof fetch;
}

export class HttpAdapter implements ApiAdapter {
  private readonly baseUrl: string;
  private readonly token?: string;
  private readonly fetchImpl: typeof fetch;

  constructor(options: HttpAdapterOptions) {
    this.baseUrl = options.baseUrl.replace(/\/$/, '');
    this.token = options.token;
    this.fetchImpl = options.fetchImpl ?? globalThis.fetch;
  }

  listWorkflows(params?: CursorParams): Promise<CursorPage<WorkflowDefinitionDTO>> {
    return this.request<CursorPage<WorkflowDefinitionDTO>>(
      'GET',
      '/workflows/definitions',
      undefined,
      params,
    );
  }

  getWorkflow(id: WorkflowDefinitionId): Promise<WorkflowDefinitionDTO> {
    return this.request<WorkflowDefinitionDTO>('GET', `/workflows/definitions/${id}`);
  }

  createWorkflow(request: CreateWorkflowRequest): Promise<WorkflowDefinitionDTO> {
    return this.request<WorkflowDefinitionDTO>('POST', '/workflows/definitions', request);
  }

  updateWorkflow(
    id: WorkflowDefinitionId,
    request: UpdateWorkflowRequest,
  ): Promise<WorkflowDefinitionDTO> {
    return this.request<WorkflowDefinitionDTO>('PUT', `/workflows/definitions/${id}`, request);
  }

  listVersions(
    id: WorkflowDefinitionId,
    params?: CursorParams,
  ): Promise<CursorPage<WorkflowVersionDTO>> {
    return this.request<CursorPage<WorkflowVersionDTO>>(
      'GET',
      `/workflows/definitions/${id}/versions`,
      undefined,
      params,
    );
  }

  saveVersion(
    id: WorkflowDefinitionId,
    request: CreateVersionRequest,
  ): Promise<WorkflowVersionDTO> {
    return this.request<WorkflowVersionDTO>(
      'POST',
      `/workflows/definitions/${id}/versions`,
      request,
    );
  }

  listAgentDefinitions(params?: CursorParams): Promise<CursorPage<AgentDefinitionRef>> {
    return this.request<CursorPage<AgentDefinitionRef>>(
      'GET',
      '/agents/definitions',
      undefined,
      params,
    );
  }

  listModelProfiles(params?: CursorParams): Promise<CursorPage<ModelProfileRef>> {
    return this.request<CursorPage<ModelProfileRef>>('GET', '/model-profiles', undefined, params);
  }

  listToolPolicies(params?: CursorParams): Promise<CursorPage<ToolPolicyRef>> {
    return this.request<CursorPage<ToolPolicyRef>>('GET', '/tool-policies', undefined, params);
  }

  /* ---------------- workflow-runtime (ADR-101 §5.3) ---------------- */

  launchRun(request: RunCreateRequest): Promise<RunResponse> {
    return this.request<RunResponse>('POST', '/workflows/runs', request);
  }

  listRuns(params?: CursorParams): Promise<CursorPage<RunResponse>> {
    return this.request<CursorPage<RunResponse>>('GET', '/workflows/runs', undefined, params);
  }

  getRun(runId: string): Promise<RunResponse> {
    return this.request<RunResponse>('GET', `/workflows/runs/${runId}`);
  }

  listRunTasks(runId: string, params?: CursorParams): Promise<CursorPage<TaskResponse>> {
    return this.request<CursorPage<TaskResponse>>(
      'GET',
      `/workflows/runs/${runId}/tasks`,
      undefined,
      params,
    );
  }

  /* ---------------- MVP v1 platform domain ---------------- */

  listProjects(): Promise<ProjectResponse[]> {
    return this.request<ProjectResponse[]>('GET', '/projects');
  }

  createProject(request: ProjectCreate): Promise<ProjectResponse> {
    return this.request<ProjectResponse>('POST', '/projects', request);
  }

  listWorkspaces(projectId?: string): Promise<WorkspaceResponse[]> {
    const path =
      projectId !== undefined
        ? `/workspaces?project_id=${encodeURIComponent(projectId)}`
        : '/workspaces';
    return this.request<WorkspaceResponse[]>('GET', path);
  }

  createWorkspace(request: WorkspaceCreate): Promise<WorkspaceResponse> {
    return this.request<WorkspaceResponse>('POST', '/workspaces', request);
  }

  listAgents(): Promise<AgentResponse[]> {
    return this.request<AgentResponse[]>('GET', '/agents');
  }

  registerAgent(request: AgentRegister): Promise<AgentResponse> {
    return this.request<AgentResponse>('POST', '/agents/register', request);
  }

  getTask(taskId: string): Promise<TaskResponse> {
    return this.request<TaskResponse>('GET', `/tasks/${taskId}`);
  }

  listTaskAttempts(taskId: string): Promise<AttemptResponse[]> {
    return this.request<AttemptResponse[]>('GET', `/tasks/${taskId}/attempts`);
  }

  claimTask(taskId: string, request: ClaimRequest): Promise<AttemptResponse> {
    return this.request<AttemptResponse>('POST', `/tasks/${taskId}/claim`, request);
  }

  submitTask(
    taskId: string,
    attemptId: string,
    request: SubmitRequest,
    agentId: string,
  ): Promise<AttemptResponse> {
    return this.request<AttemptResponse>(
      'POST',
      `/tasks/${taskId}/attempts/${attemptId}/submit?agent_id=${encodeURIComponent(agentId)}`,
      request,
    );
  }

  failTask(
    taskId: string,
    attemptId: string,
    request: FailRequest,
    agentId: string,
  ): Promise<AttemptResponse> {
    return this.request<AttemptResponse>(
      'POST',
      `/tasks/${taskId}/attempts/${attemptId}/fail?agent_id=${encodeURIComponent(agentId)}`,
      request,
    );
  }

  blockTask(taskId: string, request: BlockRequest, agentId: string): Promise<TaskResponse> {
    return this.request<TaskResponse>(
      'POST',
      `/tasks/${taskId}/block?agent_id=${encodeURIComponent(agentId)}`,
      request,
    );
  }

  /* ---------------- admin-only reconciliation (#38) ---------------- */

  listRecoveryQuarantine(): Promise<TaskResponse[]> {
    return this.request<TaskResponse[]>('GET', '/admin/recovery-quarantine');
  }

  getRecoveryReconciliation(taskId: string): Promise<ReconciliationResponse> {
    return this.request<ReconciliationResponse>(
      'GET', `/admin/tasks/${encodeURIComponent(taskId)}/reconciliation`,
    );
  }

  getRecoveryLedger(taskId: string): Promise<RecoveryLedgerReport> {
    return this.request<RecoveryLedgerReport>(
      'GET', `/admin/tasks/${encodeURIComponent(taskId)}/tool-ledger`,
    );
  }

  attestRecovery(
    taskId: string,
    request: ReconciliationRequest,
  ): Promise<ReconciliationResponse> {
    return this.request<ReconciliationResponse>(
      'POST', `/admin/tasks/${encodeURIComponent(taskId)}/reconciliation`, request,
    );
  }

  async getRunSnapshot(runId: string): Promise<RunSnapshot> {
    const [run, tasks] = await Promise.all([this.getRun(runId), this.listRunTasks(runId)]);
    return { run, tasks: tasks.items };
  }

  private async request<T>(
    method: string,
    path: string,
    body?: unknown,
    params?: CursorParams,
  ): Promise<T> {
    const headers: Record<string, string> = { Accept: 'application/json' };
    if (this.token) headers.Authorization = `Bearer ${this.token}`;
    if (body !== undefined) headers['Content-Type'] = 'application/json';

    const response = await this.fetchImpl(this.buildUrl(path, params), {
      method,
      headers,
      body: body !== undefined ? JSON.stringify(body) : undefined,
    });

    if (!response.ok) {
      let problem: ProblemDetails = { type: 'about:blank', status: response.status };
      try {
        const parsed = (await response.json()) as ProblemDetails;
        if (parsed && typeof parsed === 'object') {
          problem = { ...problem, ...parsed };
          // Never let the server override a status it did not actually send.
          problem.status = problem.status ?? response.status;
        }
      } catch {
        // Non-JSON error body; keep the minimal fallback problem document.
      }
      throw new ProblemDetailsError(problem);
    }

    if (response.status === 204) return undefined as T;
    return (await response.json()) as T;
  }

  private buildUrl(path: string, params?: CursorParams): string {
    const search = new URLSearchParams();
    if (params?.after !== undefined) search.set('after', params.after);
    if (params?.limit !== undefined) search.set('limit', String(params.limit));
    const extended = params as CursorParams & { projectId?: string; status?: string };
    if (extended?.projectId !== undefined) search.set('project_id', extended.projectId);
    if (extended?.status !== undefined) search.set('status', extended.status);
    const query = search.toString();
    return query ? `${this.baseUrl}${path}?${query}` : `${this.baseUrl}${path}`;
  }
}
