import { afterEach, describe, expect, it, vi } from 'vitest';

import { createApiClient, HttpAdapter, MockAdapter, ProblemDetailsError } from './client';
import type { WorkflowDefinition } from '../workflow/types';

const BASE_URL = 'http://api.example/api/v1';

const WORKFLOW_ID = '00000000-0000-4000-8000-0000000000a1';

function validWorkflow(): WorkflowDefinition {
  return {
    schema_version: '1.0',
    metadata: { name: 'demo', version: 1, created_at: '2026-10-09T00:00:00Z' },
    nodes: [
      {
        id: 'n_start',
        type: 'start',
        label: 'Start',
        position: { x: 0, y: 0 },
        config: {},
      },
      {
        id: 'n_agent',
        type: 'agent',
        label: 'Agent',
        position: { x: 100, y: 0 },
        config: {
          agent_definition_id: '11111111-1111-4111-8111-111111111111',
          model_profile_id: '22222222-2222-4222-8222-222222222222',
          tool_policy_id: '33333333-3333-4333-8333-333333333333',
        },
      },
      {
        id: 'n_end',
        type: 'end',
        label: 'End',
        position: { x: 200, y: 0 },
        config: {},
      },
    ],
    edges: [
      { id: 'e1', source_node_id: 'n_start', target_node_id: 'n_agent', output_mapping: {}, on_error: 'fail', max_retries: 0 },
      { id: 'e2', source_node_id: 'n_agent', target_node_id: 'n_end', output_mapping: {}, on_error: 'fail', max_retries: 0 },
    ],
  };
}

interface CapturedRequest {
  url: string;
  method: string;
  headers: Record<string, string>;
  body: unknown;
}

const captured: CapturedRequest[] = [];

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

/** Build a fetch stub that records every call, then hands off to `handler`. */
function installFetch(handler: (req: CapturedRequest) => Response): void {
  vi.stubGlobal(
    'fetch',
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      captured.push({
        url: input.toString(),
        method: init?.method ?? 'GET',
        headers: (init?.headers as Record<string, string>) ?? {},
        body: init?.body ? JSON.parse(init.body as string) : undefined,
      });
      return handler(captured[captured.length - 1]);
    }),
  );
}

describe('HttpAdapter (fetch mocked)', () => {

  it('preserves the native Window receiver when no fetch transport is injected', async () => {
    vi.stubGlobal('fetch', function browserFetch(this: unknown) {
      if (this !== globalThis) {
        throw new TypeError("Failed to execute 'fetch' on 'Window': Illegal invocation");
      }
      return Promise.resolve(jsonResponse(200, []));
    });
    const client = createApiClient();
    expect(await client.listProjects()).toEqual([]);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    captured.length = 0;
  });

  it('createWorkflow issues POST /workflows/definitions with the correct body and headers', async () => {
    const definition = validWorkflow();
    installFetch(() =>
      jsonResponse(201, {
        id: WORKFLOW_ID,
        name: 'demo',
        description: 'desc',
        definition,
        is_active: true,
        created_at: '2026-10-09T00:00:00Z',
        updated_at: '2026-10-09T00:00:00Z',
        version: 1,
      }),
    );

    const client = createApiClient({
      mock: false,
      baseUrl: BASE_URL,
      token: 'secret-token',
    });
    const result = await client.createWorkflow({ name: 'demo', description: 'desc', definition });

    expect(captured).toHaveLength(1);
    expect(captured[0].method).toBe('POST');
    expect(captured[0].url).toBe(`${BASE_URL}/workflows/definitions`);
    expect(captured[0].headers.Authorization).toBe('Bearer secret-token');
    expect(captured[0].headers['Content-Type']).toBe('application/json');
    expect(captured[0].body).toEqual({ name: 'demo', description: 'desc', definition });
    expect(result.id).toBe(WORKFLOW_ID);
    expect(result.version).toBe(1);
  });

  it('getWorkflow issues GET /workflows/definitions/{id}', async () => {
    installFetch(() =>
      jsonResponse(200, {
        id: WORKFLOW_ID,
        name: 'demo',
        definition: validWorkflow(),
        is_active: true,
        created_at: '2026-10-09T00:00:00Z',
        updated_at: '2026-10-09T00:00:00Z',
        version: 2,
      }),
    );
    const client = createApiClient({ mock: false, baseUrl: BASE_URL });

    await client.getWorkflow(WORKFLOW_ID);

    expect(captured[0].method).toBe('GET');
    expect(captured[0].url).toBe(`${BASE_URL}/workflows/definitions/${WORKFLOW_ID}`);
  });

  it('updateWorkflow issues PUT /workflows/definitions/{id} with the body', async () => {
    installFetch(() =>
      jsonResponse(200, {
        id: WORKFLOW_ID,
        name: 'renamed',
        definition: validWorkflow(),
        is_active: true,
        created_at: '2026-10-09T00:00:00Z',
        updated_at: '2026-10-09T01:00:00Z',
        version: 3,
      }),
    );
    const client = createApiClient({ mock: false, baseUrl: BASE_URL });

    await client.updateWorkflow(WORKFLOW_ID, { name: 'renamed' });

    expect(captured[0].method).toBe('PUT');
    expect(captured[0].url).toBe(`${BASE_URL}/workflows/definitions/${WORKFLOW_ID}`);
    expect(captured[0].body).toEqual({ name: 'renamed' });
  });

  it('listWorkflows appends cursor query params after & limit', async () => {
    installFetch(() => jsonResponse(200, { items: [], next_cursor: null }));
    const client = createApiClient({ mock: false, baseUrl: BASE_URL });

    await client.listWorkflows({ after: 'cursor-1', limit: 25 });

    expect(captured[0].method).toBe('GET');
    expect(captured[0].url).toBe(`${BASE_URL}/workflows/definitions?after=cursor-1&limit=25`);
  });

  it('listVersions issues GET /workflows/definitions/{id}/versions', async () => {
    installFetch(() => jsonResponse(200, { items: [], next_cursor: null }));
    const client = createApiClient({ mock: false, baseUrl: BASE_URL });

    await client.listVersions(WORKFLOW_ID);

    expect(captured[0].url).toBe(`${BASE_URL}/workflows/definitions/${WORKFLOW_ID}/versions`);
  });

  it('saveVersion issues POST /workflows/definitions/{id}/versions with the snapshot body', async () => {
    const snapshot = validWorkflow();
    installFetch(() =>
      jsonResponse(201, {
        id: 'v-1',
        workflow_definition_id: WORKFLOW_ID,
        version_number: 2,
        definition_snapshot: snapshot,
        changelog: 'initial',
        created_at: '2026-10-09T00:00:00Z',
      }),
    );
    const client = createApiClient({ mock: false, baseUrl: BASE_URL });

    const result = await client.saveVersion(WORKFLOW_ID, { definition_snapshot: snapshot, changelog: 'initial' });

    expect(captured[0].method).toBe('POST');
    expect(captured[0].url).toBe(`${BASE_URL}/workflows/definitions/${WORKFLOW_ID}/versions`);
    expect(captured[0].body).toEqual({ definition_snapshot: snapshot, changelog: 'initial' });
    expect(result.version_number).toBe(2);
  });

  it('reference endpoints hit the approved paths', async () => {
    installFetch((req) => {
      if (req.url.endsWith('/agents/definitions')) return jsonResponse(200, { items: [], next_cursor: null });
      if (req.url.endsWith('/model-profiles')) return jsonResponse(200, { items: [], next_cursor: null });
      return jsonResponse(200, { items: [], next_cursor: null });
    });
    const client = createApiClient({ mock: false, baseUrl: BASE_URL });

    await client.listAgentDefinitions();
    await client.listModelProfiles();
    await client.listToolPolicies();

    expect(captured.map((c) => c.url)).toEqual([
      `${BASE_URL}/agents/definitions`,
      `${BASE_URL}/model-profiles`,
      `${BASE_URL}/tool-policies`,
    ]);
  });

  it('launchRun issues POST /workflows/runs with the run body and 201 payload', async () => {
    installFetch(() =>
      jsonResponse(201, {
        id: 'run-1',
        project_id: 'p1',
        name: 'demo-run',
        status: 'pending',
        version: 1,
        created_at: '2026-10-09T00:00:00Z',
      }),
    );
    const client = createApiClient({ mock: false, baseUrl: BASE_URL });

    const result = await client.launchRun({ project_id: 'p1', name: 'demo-run', tasks: [{ title: 't1' }] });

    expect(captured[0].method).toBe('POST');
    expect(captured[0].url).toBe(`${BASE_URL}/workflows/runs`);
    expect(captured[0].body).toEqual({ project_id: 'p1', name: 'demo-run', tasks: [{ title: 't1' }] });
    expect(result.status).toBe('pending');
  });

  it('getRun issues GET /workflows/runs/{id} and listRunTasks GET /workflows/runs/{id}/tasks', async () => {
    installFetch(() => jsonResponse(200, { items: [], next_cursor: null }));
    const client = createApiClient({ mock: false, baseUrl: BASE_URL });

    await client.getRun('run-1');
    await client.listRunTasks('run-1', { after: 'c', limit: 25 });

    expect(captured[0].method).toBe('GET');
    expect(captured[0].url).toBe(`${BASE_URL}/workflows/runs/run-1`);
    expect(captured[1].url).toBe(`${BASE_URL}/workflows/runs/run-1/tasks?after=c&limit=25`);
  });

  it('surfaces a 422 Problem Details response as a typed error', async () => {
    installFetch(() =>
      jsonResponse(422, {
        type: 'https://example.com/problems/validation',
        title: 'Unprocessable Entity',
        status: 422,
        detail: 'Workflow definition violates business rules.',
        instance: '/api/v1/workflows/definitions',
        errors: [{ path: 'nodes', message: 'exactly one start node is required (found 2)' }],
      }),
    );
    const client = createApiClient({ mock: false, baseUrl: BASE_URL });

    await expect(client.createWorkflow({ name: 'x', definition: validWorkflow() })).rejects.toBeInstanceOf(
      ProblemDetailsError,
    );
    try {
      await client.createWorkflow({ name: 'x', definition: validWorkflow() });
    } catch (error) {
      const typed = error as ProblemDetailsError;
      expect(typed.status).toBe(422);
      expect(typed.problem.title).toBe('Unprocessable Entity');
      expect(typed.problem.detail).toContain('business rules');
      expect(typed.problem.errors?.[0]?.path).toBe('nodes');
      expect(typed.message).toContain('business rules');
    }
  });
});

describe('HttpAdapter — MVP v1 platform endpoints', () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    captured.length = 0;
  });

  it('listProjects GETs /projects and returns the array', async () => {
    installFetch(() =>
      jsonResponse(200, [{ id: 'p1', name: 'Alpha', version: 1, created_at: '2026-10-09T00:00:00Z' }]),
    );
    const client = createApiClient({ mock: false, baseUrl: BASE_URL });
    const projects = await client.listProjects();
    expect(captured[0].method).toBe('GET');
    expect(captured[0].url).toBe(`${BASE_URL}/projects`);
    expect(projects[0].name).toBe('Alpha');
  });

  it('createProject POSTs /projects with the body', async () => {
    installFetch(() => jsonResponse(201, { id: 'p2', name: 'Beta', version: 1 }));
    const client = createApiClient({ mock: false, baseUrl: BASE_URL });
    await client.createProject({ name: 'Beta', description: 'desc' });
    expect(captured[0].method).toBe('POST');
    expect(captured[0].url).toBe(`${BASE_URL}/projects`);
    expect(captured[0].body).toEqual({ name: 'Beta', description: 'desc' });
  });

  it('listWorkspaces supports the project filter query param', async () => {
    installFetch(() => jsonResponse(200, []));
    const client = createApiClient({ mock: false, baseUrl: BASE_URL });
    await client.listWorkspaces('p1');
    expect(captured[0].url).toBe(`${BASE_URL}/workspaces?project_id=p1`);
  });

  it('listAgents GETs /agents and registerAgent POSTs /agents/register', async () => {
    installFetch(() => jsonResponse(200, [{ id: 'a1', name: 'A', status: 'idle', version: 1 }]));
    const client = createApiClient({ mock: false, baseUrl: BASE_URL });
    await client.listAgents();
    expect(captured[0].url).toBe(`${BASE_URL}/agents`);
    await client.registerAgent({ name: 'New Agent' });
    expect(captured[1].method).toBe('POST');
    expect(captured[1].url).toBe(`${BASE_URL}/agents/register`);
    expect(captured[1].body).toEqual({ name: 'New Agent' });
  });

  it('getTask GETs /tasks/{id} and listTaskAttempts GETs /tasks/{id}/attempts', async () => {
    installFetch(() => jsonResponse(200, []));
    const client = createApiClient({ mock: false, baseUrl: BASE_URL });
    await client.getTask('task-1');
    expect(captured[0].url).toBe(`${BASE_URL}/tasks/task-1`);
    await client.listTaskAttempts('task-1');
    expect(captured[1].url).toBe(`${BASE_URL}/tasks/task-1/attempts`);
  });

  it('claimTask POSTs /tasks/{id}/claim with agent_id', async () => {
    installFetch(() => jsonResponse(201, { id: 'att-1', task_id: 't1', attempt_number: 1, status: 'in_progress', version: 1 }));
    const client = createApiClient({ mock: false, baseUrl: BASE_URL });
    await client.claimTask('t1', { agent_id: 'ag-1' });
    expect(captured[0].method).toBe('POST');
    expect(captured[0].url).toBe(`${BASE_URL}/tasks/t1/claim`);
    expect(captured[0].body).toEqual({ agent_id: 'ag-1' });
  });

  it('submitTask / failTask / blockTask hit the attempt endpoints with agent_id query and body', async () => {
    installFetch(() => jsonResponse(200, { id: 'att-1', status: 'completed', version: 1 }));
    const client = createApiClient({ mock: false, baseUrl: BASE_URL });
    await client.submitTask('t1', 'att-1', { output: { ok: true } }, 'ag-1');
    expect(captured[0].url).toBe(`${BASE_URL}/tasks/t1/attempts/att-1/submit?agent_id=ag-1`);
    expect(captured[0].body).toEqual({ output: { ok: true } });
    await client.failTask('t1', 'att-1', { error: 'boom' }, 'ag-1');
    expect(captured[1].url).toBe(`${BASE_URL}/tasks/t1/attempts/att-1/fail?agent_id=ag-1`);
    expect(captured[1].body).toEqual({ error: 'boom' });
    await client.blockTask('t1', { reason: 'why' }, 'ag-1');
    expect(captured[2].url).toBe(`${BASE_URL}/tasks/t1/block?agent_id=ag-1`);
    expect(captured[2].body).toEqual({ reason: 'why' });
  });

  it('listRuns forwards project_id and status filters', async () => {
    installFetch(() => jsonResponse(200, { items: [], next_cursor: null }));
    const client = createApiClient({ mock: false, baseUrl: BASE_URL });
    await client.listRuns({ projectId: 'p1', status: 'running' });
    expect(captured[0].url).toBe(`${BASE_URL}/workflows/runs?project_id=p1&status=running`);
  });

  it('getRunSnapshot combines getRun and listRunTasks', async () => {
    installFetch((req) => {
      if (req.url.endsWith('/workflows/runs/run-1')) {
        return jsonResponse(200, { id: 'run-1', project_id: 'p1', name: 'R', status: 'running', version: 1 });
      }
      return jsonResponse(200, { items: [{ id: 'task-1', title: 'T', status: 'pending', priority: 0, attempt_count: 0, max_attempts: 1, version: 1 }], next_cursor: null });
    });
    const client = createApiClient({ mock: false, baseUrl: BASE_URL });
    const snapshot = await client.getRunSnapshot('run-1');
    expect(snapshot.run.id).toBe('run-1');
    expect(snapshot.tasks).toHaveLength(1);
    expect(snapshot.tasks[0].id).toBe('task-1');
  });
});

describe('MockAdapter (offline end-to-end path)', () => {
  it('create then get returns an identical definition JSON', async () => {
    const adapter = new MockAdapter();
    const definition = validWorkflow();

    const created = await adapter.createWorkflow({ name: 'demo', description: 'desc', definition });
    const fetched = await adapter.getWorkflow(created.id);

    expect(fetched.definition).toEqual(definition);
    expect(fetched.name).toBe('demo');
    expect(fetched.version).toBe(1);
  });

  it('a missing workflow rejects with a typed ProblemDetailsError', async () => {
    const adapter = new MockAdapter();
    await expect(adapter.getWorkflow('does-not-exist')).rejects.toBeInstanceOf(ProblemDetailsError);
  });

  it('saveVersion creates an incrementing immutable snapshot', async () => {
    const adapter = new MockAdapter();
    const created = await adapter.createWorkflow({ name: 'demo', definition: validWorkflow() });

    const v1 = await adapter.saveVersion(created.id, { definition_snapshot: created.definition, changelog: 'initial' });
    const v2 = await adapter.saveVersion(created.id, { definition_snapshot: created.definition, changelog: 'revision' });
    const page = await adapter.listVersions(created.id);

    expect(v1.version_number).toBe(1);
    expect(v2.version_number).toBe(2);
    expect(page.items.map((v) => v.version_number)).toEqual([1, 2]);
    expect(page.items[1].changelog).toBe('revision');
    expect(page.items[1].definition_snapshot).toEqual(created.definition);
  });

  it('updateWorkflow bumps the revision and persists the new definition', async () => {
    const adapter = new MockAdapter();
    const created = await adapter.createWorkflow({ name: 'demo', definition: validWorkflow() });

    const updated = await adapter.updateWorkflow(created.id, { name: 'renamed' });
    const fetched = await adapter.getWorkflow(created.id);

    expect(updated.version).toBe(2);
    expect(fetched.version).toBe(2);
    expect(fetched.name).toBe('renamed');
  });

  it('createApiClient() defaults to the real HTTP adapter (integration path)', async () => {
    const client = createApiClient();
    expect(client).toBeInstanceOf(HttpAdapter);
  });

  it('createApiClient({ mock: true }) returns the offline mock adapter', async () => {
    const client = createApiClient({ mock: true });
    const created = await client.createWorkflow({ name: 'demo', definition: validWorkflow() });
    const fetched = await client.getWorkflow(created.id);
    expect(fetched.definition).toEqual(validWorkflow());
    expect(client).toBeInstanceOf(MockAdapter);
  });

  it('exposes seeded reference lists for property-panel selectors', async () => {
    const client = createApiClient({ mock: true });
    const agents = await client.listAgentDefinitions();
    const models = await client.listModelProfiles();
    const tools = await client.listToolPolicies();

    expect(agents.items.length).toBeGreaterThanOrEqual(1);
    expect(agents.items[0].id).toBe(MockAdapter.seed.agentDefinitionId);
    expect(models.items[0].id).toBe(MockAdapter.seed.modelProfileId);
    expect(tools.items[0].id).toBe(MockAdapter.seed.toolPolicyId);
  });

  it('creates and lists projects; createWorkspace scopes by project', async () => {
    const adapter = new MockAdapter();
    const project = await adapter.createProject({ name: 'Demo', description: 'd' });
    const projects = await adapter.listProjects();
    expect(projects.map((p) => p.id)).toContain(project.id);
    expect(projects.map((p) => p.name)).toContain('Demo');

    const ws = await adapter.createWorkspace({ project_id: project.id, name: 'ws1' });
    const scoped = await adapter.listWorkspaces(project.id);
    expect(scoped.map((w) => w.id)).toContain(ws.id);
    // The seeded workspace belongs to proj_seed, not the new project.
    expect(scoped.every((w) => w.project_id === project.id)).toBe(true);
  });

  it('launching a run seeds tasks and an in-progress attempt, then claim/submit completes', async () => {
    const adapter = new MockAdapter();
    const run = await adapter.launchRun({
      project_id: 'proj_seed',
      name: 'Pipeline 1',
      tasks: [{ title: 'Research', node_id: 'n1' }, { title: 'Draft', node_id: 'n2' }],
    });
    expect(run.status).toBe('running');

    const tasks = (await adapter.listRunTasks(run.id)).items;
    expect(tasks).toHaveLength(2);

    // First task already has an in-progress attempt seeded by the mock.
    const first = tasks[0];
    const attempts = await adapter.listTaskAttempts(first.id);
    expect(attempts.length).toBe(1);
    expect(attempts[0].status).toBe('in_progress');

    // Submit completes the task and surfaces output.
    const submitted = await adapter.submitTask(first.id, attempts[0].id, { output: { ok: true } });
    expect(submitted.status).toBe('completed');
    const refreshed = await adapter.getTask(first.id);
    expect(refreshed.status).toBe('completed');
    expect(refreshed.output_data).toEqual({ ok: true });
  });

  it('claimTask/failTask/blockTask mutate task state in the mock', async () => {
    const adapter = new MockAdapter();
    const run = await adapter.launchRun({
      project_id: 'proj_seed',
      name: 'P',
      tasks: [{ title: 'T' }],
    });
    const task = (await adapter.listRunTasks(run.id)).items[0];
    const claimed = await adapter.claimTask(task.id, { agent_id: 'ag-9' });
    expect(claimed.agent_id).toBe('ag-9');
    const failed = await adapter.failTask(task.id, claimed.id, { error: 'boom' });
    expect(failed.status).toBe('failed');
    expect((await adapter.getTask(task.id)).status).toBe('failed');

    const run2 = await adapter.launchRun({ project_id: 'proj_seed', name: 'P2', tasks: [{ title: 'T' }] });
    const task2 = (await adapter.listRunTasks(run2.id)).items[0];
    await adapter.blockTask(task2.id, { reason: 'why' });
    expect((await adapter.getTask(task2.id)).status).toBe('blocked');
  });

  it('getRunSnapshot + deriveLog produce a coherent lifecycle log', async () => {
    const adapter = new MockAdapter();
    const run = await adapter.launchRun({
      project_id: 'proj_seed',
      name: 'Live',
      tasks: [{ title: 'T1' }],
    });
    const snapshot = await adapter.getRunSnapshot(run.id);
    expect(snapshot.run.id).toBe(run.id);
    expect(snapshot.tasks.length).toBeGreaterThanOrEqual(1);

    const log = adapter.deriveLog(run.id);
    expect(log.length).toBeGreaterThanOrEqual(1);
    expect(log.some((e) => e.kind === 'run')).toBe(true);
    expect(log.every((e) => e.run_id === run.id)).toBe(true);
  });
});