/**
 * In-memory mock adapter for fully offline development and testing.
 *
 * Implements `ApiAdapter` with a per-instance store so TASK-004/005/006 remain
 * runnable without the orchestration server (t_52732c01). It mirrors the real
 * API's observable behaviour (create persists, get returns identical JSON,
 * updates bump the revision, versions snapshot on save) and surfaces the same
 * RFC 9457 `ProblemDetailsError` for missing resources, so the UI layer can
 * swap mock<->HTTP with no code change.
 */

import { ProblemDetailsError } from './httpAdapter';
import type {
  AgentDefinitionRef,
  AgentRegister,
  AgentResponse,
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
  ProjectCreate,
  ProjectResponse,
  ReconciliationRequest,
  ReconciliationResponse,
  RecoveryLedgerReport,
  RunCreateRequest,
  RunLogEvent,
  RunResponse,
  RunSnapshot,
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

const MS_AGENT_DEFINITION = '11111111-1111-4111-8111-111111111111';
const MS_MODEL_PROFILE = '22222222-2222-4222-8222-222222222222';
const MS_TOOL_POLICY = '33333333-3333-4333-8333-333333333333';

export class MockAdapter implements ApiAdapter {
  private readonly workflows = new Map<WorkflowDefinitionId, WorkflowDefinitionDTO>();
  private readonly versions = new Map<WorkflowDefinitionId, WorkflowVersionDTO[]>();
  private readonly runs = new Map<string, RunResponse>();
  private readonly runTasks: Record<string, TaskResponse[]> = {};
  private readonly attempts: Record<string, AttemptResponse[]> = {};
  private readonly projects = new Map<string, ProjectResponse>();
  private readonly workspaces: WorkspaceResponse[] = [];
  private readonly agents: AgentResponse[] = [];
  private sequence = 0;
  private runSequence = 0;
  private taskSequence = 0;
  private attemptSequence = 0;
  private projectSequence = 0;
  private workspaceSequence = 0;
  private agentSequence = 0;

  constructor() {
    // Seed a default project + workspace so the MVP UI has something to show
    // immediately in offline dev, and a couple of runtime agents.
    this.projects.set('proj_seed', {
      id: 'proj_seed',
      name: 'Default Project',
      description: 'Seeded MVP demo project (offline mock).',
      version: 1,
      created_at: new Date().toISOString(),
      updated_at: new Date().toISOString(),
    });
    this.workspaces.push({
      id: 'ws_seed',
      project_id: 'proj_seed',
      name: 'Default Workspace',
      version: 1,
      created_at: new Date().toISOString(),
    });
    this.agents.push(
      {
        id: 'ag_1',
        name: 'Research Agent',
        status: 'idle',
        version: 1,
        created_at: new Date().toISOString(),
      },
      {
        id: 'ag_2',
        name: 'Drafting Agent',
        status: 'idle',
        version: 1,
        created_at: new Date().toISOString(),
      },
      {
        id: 'ag_3',
        name: 'Review Agent',
        status: 'idle',
        version: 1,
        created_at: new Date().toISOString(),
      },
    );
  }

  private readonly agentDefinitions: AgentDefinitionRef[] = [
    { id: MS_AGENT_DEFINITION, name: 'Research Agent', description: 'Web research specialist.' },
    {
      id: '44444444-4444-4444-8444-444444444444',
      name: 'Drafting Agent',
      description: 'Writes documents.',
    },
    {
      id: '55555555-5555-4555-8555-555555555555',
      name: 'Review Agent',
      description: 'Quality gate reviewer.',
    },
  ];

  private readonly modelProfiles: ModelProfileRef[] = [
    {
      id: MS_MODEL_PROFILE,
      name: 'default-fast',
      provider_id: '66666666-6666-4666-8666-666666666666',
      model_id: 'fast-1',
      display_name: 'Fast / Cheap',
    },
    {
      id: '77777777-7777-4777-8777-777777777777',
      name: 'reasoning',
      provider_id: '66666666-6666-4666-8666-666666666666',
      model_id: 'reasoner-1',
      display_name: 'Reasoning',
    },
  ];

  private readonly toolPolicies: ToolPolicyRef[] = [
    { id: MS_TOOL_POLICY, name: 'read-only', description: 'FS read, no network.' },
    {
      id: '88888888-8888-4888-8888-888888888888',
      name: 'sandboxed',
      description: 'Scoped FS write, limited shell.',
    },
  ];

  static readonly seed = {
    agentDefinitionId: MS_AGENT_DEFINITION,
    modelProfileId: MS_MODEL_PROFILE,
    toolPolicyId: MS_TOOL_POLICY,
  };

  async listWorkflows(params?: CursorParams): Promise<CursorPage<WorkflowDefinitionDTO>> {
    const items = [...this.workflows.values()].sort((a, b) =>
      a.created_at.localeCompare(b.created_at),
    );
    return this.paginate(items, params);
  }

  async getWorkflow(id: WorkflowDefinitionId): Promise<WorkflowDefinitionDTO> {
    const entry = this.workflows.get(id);
    if (!entry) {
      throw new ProblemDetailsError({
        type: 'https://example.com/problems/workflow-not-found',
        title: 'Workflow not found',
        status: 404,
        detail: `No workflow definition with id "${id}".`,
      });
    }
    return entry;
  }

  async createWorkflow(request: CreateWorkflowRequest): Promise<WorkflowDefinitionDTO> {
    const now = new Date().toISOString();
    const dto: WorkflowDefinitionDTO = {
      id: `wf_${++this.sequence}`,
      name: request.name,
      description: request.description,
      definition: request.definition,
      is_active: true,
      created_at: now,
      updated_at: now,
      version: 1,
    };
    this.workflows.set(dto.id, dto);
    return dto;
  }

  async updateWorkflow(
    id: WorkflowDefinitionId,
    request: UpdateWorkflowRequest,
  ): Promise<WorkflowDefinitionDTO> {
    const current = this.workflows.get(id);
    if (!current) {
      throw new ProblemDetailsError({
        title: 'Workflow not found',
        status: 404,
        detail: `No workflow definition with id "${id}".`,
      });
    }
    const next: WorkflowDefinitionDTO = {
      ...current,
      name: request.name ?? current.name,
      description: request.description !== undefined ? request.description : current.description,
      definition: request.definition ?? current.definition,
      is_active: request.is_active ?? current.is_active,
      updated_at: new Date().toISOString(),
      version: current.version + 1,
    };
    this.workflows.set(id, next);
    return next;
  }

  async listVersions(
    id: WorkflowDefinitionId,
    params?: CursorParams,
  ): Promise<CursorPage<WorkflowVersionDTO>> {
    const items = [...(this.versions.get(id) ?? [])].sort(
      (a, b) => a.version_number - b.version_number,
    );
    return this.paginate(items, params);
  }

  async saveVersion(
    id: WorkflowDefinitionId,
    request: CreateVersionRequest,
  ): Promise<WorkflowVersionDTO> {
    if (!this.workflows.has(id)) {
      throw new ProblemDetailsError({
        title: 'Workflow not found',
        status: 404,
        detail: `No workflow definition with id "${id}".`,
      });
    }
    const existing = this.versions.get(id) ?? [];
    const record: WorkflowVersionDTO = {
      id: `ver_${++this.sequence}`,
      workflow_definition_id: id,
      version_number: existing.length + 1,
      definition_snapshot: request.definition_snapshot,
      changelog: request.changelog,
      created_at: new Date().toISOString(),
    };
    existing.push(record);
    this.versions.set(id, existing);
    return record;
  }

  async listAgentDefinitions(params?: CursorParams): Promise<CursorPage<AgentDefinitionRef>> {
    return this.paginate([...this.agentDefinitions], params);
  }

  async listModelProfiles(params?: CursorParams): Promise<CursorPage<ModelProfileRef>> {
    return this.paginate([...this.modelProfiles], params);
  }

  async listToolPolicies(params?: CursorParams): Promise<CursorPage<ToolPolicyRef>> {
    return this.paginate([...this.toolPolicies], params);
  }

  /* ---------------- workflow-runtime (mock, mirrors orchestration) ---------------- */

  async launchRun(request: RunCreateRequest): Promise<RunResponse> {
    const now = new Date().toISOString();
    const id = `run_${++this.runSequence}`;
    const run: RunResponse = {
      id,
      project_id: request.project_id,
      workspace_id: request.workspace_id,
      name: request.name,
      status: 'running',
      input_data: request.input_data,
      triggered_by: request.triggered_by,
      started_at: now,
      version: 1,
      created_at: now,
    };
    this.runs.set(id, run);
    this.runTasks[id] = request.tasks.map((spec) => ({
      id: `task_${++this.taskSequence}`,
      workflow_run_id: id,
      node_id: spec.node_id,
      title: spec.title,
      description: spec.description,
      status: 'pending',
      contract_id: spec.contract_id,
      input_data: spec.input_data,
      priority: spec.priority ?? 0,
      attempt_count: 0,
      max_attempts: 1,
      version: 1,
      created_at: now,
    }));
    // Seed a claim attempt for the first task so the task card + live log show
    // an attempt lifecycle immediately in the offline mock.
    const first = this.runTasks[id][0];
    if (first) {
      const agent = this.agents[0];
      this.attempts[first.id] = [
        {
          id: `attempt_${++this.attemptSequence}`,
          task_id: first.id,
          attempt_number: 1,
          agent_id: agent?.id,
          status: 'in_progress',
          started_at: now,
          version: 1,
        },
      ];
      first.status = 'in_progress';
      first.attempt_count = 1;
      first.assigned_agent_id = agent?.id;
      first.started_at = now;
    }
    return run;
  }

  async listRuns(params?: CursorParams): Promise<CursorPage<RunResponse>> {
    const items = [...this.runs.values()].sort((a, b) =>
      (a.created_at ?? '').localeCompare(b.created_at ?? ''),
    );
    return this.paginate(items, params);
  }

  async getRun(runId: string): Promise<RunResponse> {
    const entry = this.runs.get(runId);
    if (!entry) {
      throw new ProblemDetailsError({
        title: 'Run not found',
        status: 404,
        detail: `No workflow run with id "${runId}".`,
      });
    }
    return entry;
  }

  async listRunTasks(runId: string, params?: CursorParams): Promise<CursorPage<TaskResponse>> {
    if (!this.runs.has(runId)) {
      throw new ProblemDetailsError({
        title: 'Run not found',
        status: 404,
        detail: `No workflow run with id "${runId}".`,
      });
    }
    return this.paginate([...(this.runTasks[runId] ?? [])], params);
  }

  /* ---------------- MVP v1 platform domain (mock) ---------------- */

  async listProjects(): Promise<ProjectResponse[]> {
    return [...this.projects.values()];
  }

  async createProject(request: ProjectCreate): Promise<ProjectResponse> {
    const now = new Date().toISOString();
    const project: ProjectResponse = {
      id: `proj_${++this.projectSequence}`,
      name: request.name,
      description: request.description,
      settings: request.settings,
      version: 1,
      created_at: now,
      updated_at: now,
    };
    this.projects.set(project.id, project);
    return project;
  }

  async listWorkspaces(projectId?: string): Promise<WorkspaceResponse[]> {
    return this.workspaces.filter((ws) => projectId === undefined || ws.project_id === projectId);
  }

  async createWorkspace(request: WorkspaceCreate): Promise<WorkspaceResponse> {
    const workspace: WorkspaceResponse = {
      id: `ws_${++this.workspaceSequence}`,
      project_id: request.project_id,
      name: request.name,
      path: request.path,
      settings: request.settings,
      version: 1,
      created_at: new Date().toISOString(),
    };
    this.workspaces.push(workspace);
    return workspace;
  }

  async listAgents(): Promise<AgentResponse[]> {
    return [...this.agents];
  }

  async registerAgent(request: AgentRegister): Promise<AgentResponse> {
    const agent: AgentResponse = {
      id: `ag_${++this.agentSequence}`,
      name: request.name,
      status: 'idle',
      agent_metadata: request.metadata,
      version: 1,
      created_at: new Date().toISOString(),
    };
    this.agents.push(agent);
    return agent;
  }

  async getTask(taskId: string): Promise<TaskResponse> {
    for (const tasks of Object.values(this.runTasks)) {
      const task = tasks.find((t) => t.id === taskId);
      if (task) return task;
    }
    throw new ProblemDetailsError({
      title: 'Task not found',
      status: 404,
      detail: `No task with id "${taskId}".`,
    });
  }

  async getTaskQaStatus(taskId: string): Promise<TaskQaStatus> {
    await this.getTask(taskId);
    return { task_id: taskId, status: 'disabled' };
  }

  async listTaskGitEvidence(_taskId: string): Promise<GitEvidenceResponse[]> {
    return [];
  }

  async listTaskAttempts(taskId: string): Promise<AttemptResponse[]> {
    return [...(this.attempts[taskId] ?? [])];
  }

  async claimTask(taskId: string, request: ClaimRequest): Promise<AttemptResponse> {
    const task = await this.getTask(taskId);
    const existing = this.attempts[taskId] ?? [];
    const attempt: AttemptResponse = {
      id: `attempt_${++this.attemptSequence}`,
      task_id: taskId,
      attempt_number: existing.length + 1,
      agent_id: request.agent_id,
      status: 'in_progress',
      started_at: new Date().toISOString(),
      version: 1,
    };
    existing.push(attempt);
    this.attempts[taskId] = existing;
    task.status = 'in_progress';
    task.attempt_count = existing.length;
    task.assigned_agent_id = request.agent_id;
    task.started_at = new Date().toISOString();
    return attempt;
  }

  async submitTask(
    taskId: string,
    attemptId: string,
    request: SubmitRequest,
  ): Promise<AttemptResponse> {
    const task = await this.getTask(taskId);
    const attempt = this.findAttempt(taskId, attemptId);
    attempt.status = 'completed';
    attempt.output_data = request.output;
    attempt.completed_at = new Date().toISOString();
    task.status = 'completed';
    task.output_data = request.output;
    task.completed_at = new Date().toISOString();
    return attempt;
  }

  async failTask(
    taskId: string,
    attemptId: string,
    request: FailRequest,
  ): Promise<AttemptResponse> {
    const task = await this.getTask(taskId);
    const attempt = this.findAttempt(taskId, attemptId);
    attempt.status = 'failed';
    attempt.error = request.error;
    attempt.completed_at = new Date().toISOString();
    task.status = 'failed';
    task.completed_at = new Date().toISOString();
    return attempt;
  }

  async blockTask(taskId: string, _request: BlockRequest): Promise<TaskResponse> {
    const task = await this.getTask(taskId);
    task.status = 'blocked';
    task.completed_at = new Date().toISOString();
    return task;
  }

  /* Admin recovery requires an actual privileged server, never offline simulation. */
  async listRecoveryQuarantine(): Promise<TaskResponse[]> {
    return [];
  }

  async getRecoveryReconciliation(_taskId: string): Promise<ReconciliationResponse> {
    throw new ProblemDetailsError({ status: 404, title: 'Reconciliation not found' });
  }

  async getRecoveryLedger(_taskId: string): Promise<RecoveryLedgerReport> {
    throw new ProblemDetailsError({
      status: 503, title: 'Trusted ledger inspection unavailable in offline mock',
    });
  }

  async attestRecovery(
    _taskId: string, _request: ReconciliationRequest,
  ): Promise<ReconciliationResponse> {
    throw new ProblemDetailsError({
      status: 403, title: 'Reconciliation requires a real administrator session',
    });
  }

  async getRunSnapshot(runId: string): Promise<RunSnapshot> {
    const run = await this.getRun(runId);
    const tasks = await this.listRunTasks(runId);
    return { run, tasks: tasks.items };
  }

  /** Build a derived live-log from the current run snapshot (idempotent over
   * stable state; used by the live log section's poller via diff helper). */
  deriveLog(runId: string): RunLogEvent[] {
    const { run, tasks } = this.snapshotUnsafe(runId);
    const events: RunLogEvent[] = [];
    const base = `ev_${runId}`;
    let i = 0;
    const push = (
      kind: RunLogEvent['kind'],
      level: RunLogEvent['level'],
      message: string,
      taskId?: string,
    ): void => {
      events.push({
        id: `${base}_${i++}`,
        at: new Date().toISOString(),
        kind,
        level,
        message,
        run_id: runId,
        task_id: taskId,
      });
    };
    push(
      'run',
      run.status === 'completed' ? 'success' : run.status === 'failed' ? 'error' : 'info',
      `run "${run.name}" ${run.status}`,
    );
    for (const task of tasks) {
      const level: RunLogEvent['level'] =
        task.status === 'completed'
          ? 'success'
          : task.status === 'failed'
            ? 'error'
            : task.status === 'blocked'
              ? 'warn'
              : 'info';
      push('task', level, `task "${task.title}" ${task.status}`, task.id);
    }
    return events;
  }

  private snapshotUnsafe(runId: string): RunSnapshot {
    const run = this.runs.get(runId);
    if (!run) {
      throw new ProblemDetailsError({
        title: 'Run not found',
        status: 404,
        detail: `No workflow run with id "${runId}".`,
      });
    }
    return { run, tasks: this.runTasks[runId] ?? [] };
  }

  private findAttempt(taskId: string, attemptId: string): AttemptResponse {
    const attempt = (this.attempts[taskId] ?? []).find((a) => a.id === attemptId);
    if (!attempt) {
      throw new ProblemDetailsError({
        title: 'Attempt not found',
        status: 404,
        detail: `No attempt with id "${attemptId}" on task "${taskId}".`,
      });
    }
    return attempt;
  }

  private paginate<T>(items: T[], params?: CursorParams): CursorPage<T> {
    let start = 0;
    if (params?.after !== undefined) {
      const index = items.findIndex((item) => (item as { id?: string }).id === params.after);
      if (index >= 0) start = index + 1;
    }
    const limit = params?.limit ?? items.length;
    const page = items.slice(start, start + limit);
    const next_cursor =
      start + page.length < items.length && page.length > 0
        ? (page[page.length - 1] as { id?: string }).id
        : null;
    return { items: page, next_cursor };
  }
}
