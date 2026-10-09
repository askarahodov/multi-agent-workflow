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
  ApiAdapter,
  CreateVersionRequest,
  CreateWorkflowRequest,
  CursorPage,
  CursorParams,
  ModelProfileRef,
  ToolPolicyRef,
  UpdateWorkflowRequest,
  WorkflowDefinitionDTO,
  WorkflowDefinitionId,
  WorkflowVersionDTO,
} from './types';

const MS_AGENT_DEFINITION = '11111111-1111-4111-8111-111111111111';
const MS_MODEL_PROFILE = '22222222-2222-4222-8222-222222222222';
const MS_TOOL_POLICY = '33333333-3333-4333-8333-333333333333';

export class MockAdapter implements ApiAdapter {
  private readonly workflows = new Map<WorkflowDefinitionId, WorkflowDefinitionDTO>();
  private readonly versions = new Map<WorkflowDefinitionId, WorkflowVersionDTO[]>();
  private sequence = 0;

  private readonly agentDefinitions: AgentDefinitionRef[] = [
    { id: MS_AGENT_DEFINITION, name: 'Research Agent', description: 'Web research specialist.' },
    {
      id: '44444444-4444-4444-8444-444444444444',
      name: 'Drafting Agent',
      description: 'Writes documents.',
    },
    { id: '55555555-5555-4555-8555-555555555555', name: 'Review Agent', description: 'Quality gate reviewer.' },
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
    { id: '88888888-8888-4888-8888-888888888888', name: 'sandboxed', description: 'Scoped FS write, limited shell.' },
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