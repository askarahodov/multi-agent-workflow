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
  GitEvidenceResponse,
  ModelProfileRef,
  ProblemDetails,
  PublishedRunCreate,
  PublishedRunPreflight,
  ProjectCreate,
  ContractCreate,
  ContractResponse,
  ProjectResponse,
  ReconciliationRequest,
  ReconciliationResponse,
  RecoveryLedgerReport,
  RunCreateRequest,
  RunResponse,
  RunSnapshot,
  StreamTicketTransport,
  SubmitRequest,
  TaskResponse,
  TaskQaStatus,
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
  /** Static token only for explicitly provisioned clients. */
  token?: string;
  /** Trusted runtime credential provider, invoked for each request. */
  tokenProvider?: () => string | undefined | Promise<string | undefined>;
  /** Injectable fetch (also used by tests to mock the network). */
  fetchImpl?: typeof fetch;
}

export class HttpAdapter implements ApiAdapter {
  private readonly baseUrl: string;
  private readonly token?: string;
  private readonly tokenProvider?: () => string | undefined | Promise<string | undefined>;
  private readonly fetchImpl: typeof fetch;

  constructor(options: HttpAdapterOptions) {
    this.baseUrl = options.baseUrl.replace(/\/$/, '');
    if (options.token !== undefined && options.tokenProvider !== undefined) {
      throw new Error('Choose either token or tokenProvider, not both');
    }
    this.token = options.token;
    this.tokenProvider = options.tokenProvider;
    // Browser Window.fetch is a Web IDL method that requires its Window receiver.
    // Calling an unbound reference via this.fetchImpl(...) passes HttpAdapter as
    // "this", causing Chromium's "Illegal invocation" on every UI API request.
    // Preserve injected test transports, but bind the native fallback.
    this.fetchImpl = options.fetchImpl ?? globalThis.fetch.bind(globalThis);
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

  preflightPublishedRun(definitionId: string, versionId: string, projectId: string): Promise<PublishedRunPreflight> {
    return this.request<PublishedRunPreflight>(
      'GET',
      `/workflows/definitions/${encodeURIComponent(definitionId)}/versions/${encodeURIComponent(versionId)}/preflight`,
      undefined,
      { projectId },
    );
  }

  launchPublishedRun(definitionId: string, versionId: string, request: PublishedRunCreate): Promise<RunResponse> {
    return this.request<RunResponse>(
      'POST', `/workflows/definitions/${encodeURIComponent(definitionId)}/versions/${encodeURIComponent(versionId)}/runs`, request,
    );
  }

  launchRun(request: RunCreateRequest): Promise<RunResponse> {
    return this.request<RunResponse>('POST', '/workflows/runs', request);
  }

  listRuns(params?: CursorParams): Promise<CursorPage<RunResponse>> {
    return this.request<CursorPage<RunResponse>>('GET', '/workflows/runs', undefined, params);
  }

  getRun(runId: string): Promise<RunResponse> {
    return this.request<RunResponse>('GET', `/workflows/runs/${runId}`);
  }

  async issueStreamTicket(runId: string, transport: StreamTicketTransport): Promise<string> {
    const payload = await this.request<{ ticket?: unknown }>(
      'POST',
      `/workflows/runs/${encodeURIComponent(runId)}/stream-tickets`,
      { transport },
    );
    if (typeof payload?.ticket !== 'string' || !payload.ticket) {
      throw new Error('Invalid stream ticket response');
    }
    return payload.ticket;
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

  listContracts(): Promise<ContractResponse[]> {
    return this.request<ContractResponse[]>('GET', '/contracts');
  }

  createContract(request: ContractCreate): Promise<ContractResponse> {
    return this.request<ContractResponse>('POST', '/contracts', request);
  }

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

  getTaskQaStatus(taskId: string): Promise<TaskQaStatus> {
    return this.request<TaskQaStatus>('GET', `/tasks/${taskId}/qa-attestation`);
  }

  listTaskGitEvidence(taskId: string): Promise<GitEvidenceResponse[]> {
    return this.request<GitEvidenceResponse[]>('GET', `/tasks/${taskId}/git-evidence`);
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

  listRecoveryQuarantine(runId?: string): Promise<TaskResponse[]> {
    return this.request<TaskResponse[]>(
      'GET', '/admin/recovery-quarantine', undefined,
      runId ? {runId, limit: 200} : undefined,
    );
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
    params?: CursorParams & { projectId?: string; status?: string; runId?: string },
  ): Promise<T> {
    const headers: Record<string, string> = { Accept: 'application/json' };
    const token = await this.resolveToken();
    if (token) headers.Authorization = `Bearer ${token}`;
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
          problem.status = response.status;
        }
      } catch {
        // Non-JSON error body; keep the minimal fallback problem document.
      }
      throw new ProblemDetailsError(problem);
    }

    if (response.status === 204) return undefined as T;
    return (await response.json()) as T;
  }

  private async resolveToken(): Promise<string | undefined> {
    if (!this.tokenProvider) return this.token;
    try {
      const current = await this.tokenProvider();
      if (typeof current !== 'string' || !current.trim()) {
        throw new Error('missing credential');
      }
      return current;
    } catch {
      // Never propagate a provider exception that could contain credentials.
      // Do not fall back to an anonymous HTTP request or a stale static token.
      throw new ProblemDetailsError({
        type: 'urn:auth:error:unauthorized',
        title: 'Authentication required',
        status: 401,
      });
    }
  }

  private buildUrl(path: string, params?: CursorParams): string {
    const search = new URLSearchParams();
    if (params?.after !== undefined) search.set('after', params.after);
    if (params?.limit !== undefined) search.set('limit', String(params.limit));
    const extended = params as CursorParams & { projectId?: string; status?: string; runId?: string };
    if (extended?.projectId !== undefined) search.set('project_id', extended.projectId);
    if (extended?.status !== undefined) search.set('status', extended.status);
    if (extended?.runId !== undefined) search.set('run_id', extended.runId);
    const query = search.toString();
    return query ? `${this.baseUrl}${path}?${query}` : `${this.baseUrl}${path}`;
  }
}
