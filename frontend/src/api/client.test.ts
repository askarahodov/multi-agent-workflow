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
});