import { describe, expect, it } from 'vitest';
import type { WorkflowDefinition } from './types';
import { validateGraph } from './validateGraph';

const UUID = {
  agentDef: '11111111-1111-4111-8111-111111111111',
  modelProfile: '22222222-2222-4222-8222-222222222222',
  toolPolicy: '33333333-3333-4333-8333-333333333333',
};

function agentConfig(): Record<string, unknown> {
  return {
    agent_definition_id: UUID.agentDef,
    model_profile_id: UUID.modelProfile,
    tool_policy_id: UUID.toolPolicy,
  };
}

function baseWorkflow(): WorkflowDefinition {
  return {
    schema_version: '1.0',
    metadata: { name: 'test', version: 1, created_at: '2026-10-09T00:00:00Z' },
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
        config: agentConfig(),
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
      {
        id: 'e1',
        source_node_id: 'n_start',
        target_node_id: 'n_agent',
        output_mapping: { start: 'input' },
        on_error: 'fail',
        max_retries: 0,
      },
      {
        id: 'e2',
        source_node_id: 'n_agent',
        target_node_id: 'n_end',
        output_mapping: { result: 'output' },
        on_error: 'fail',
        max_retries: 0,
      },
    ],
  };
}

function findError(result: { errors: Array<{ path: string; message: string }> }, needle: string) {
  return result.errors.find(
    (error) => error.message.includes(needle) || error.path.includes(needle),
  );
}

describe('validateGraph', () => {
  it('passes a valid multi-node DAG', () => {
    const result = validateGraph(baseWorkflow());
    expect(result.isValid).toBe(true);
    expect(result.errors).toEqual([]);
  });

  it('rejects a workflow with a cycle', () => {
    const workflow = baseWorkflow();
    workflow.edges.push({
      id: 'e3',
      source_node_id: 'n_end',
      target_node_id: 'n_start',
      output_mapping: {},
      on_error: 'skip',
      max_retries: 1,
    });
    const result = validateGraph(workflow);
    expect(result.isValid).toBe(false);
    expect(findError(result, 'acyclic')).toBeDefined();
  });

  it('rejects a workflow with a self-loop on a node', () => {
    const workflow = baseWorkflow();
    workflow.edges.push({
      id: 'e4',
      source_node_id: 'n_agent',
      target_node_id: 'n_agent',
      output_mapping: {},
      on_error: 'retry',
      max_retries: 2,
    });
    const result = validateGraph(workflow);
    expect(result.isValid).toBe(false);
    expect(findError(result, 'acyclic')).toBeDefined();
  });

  it('rejects a workflow with no start node', () => {
    const workflow = baseWorkflow();
    workflow.nodes = workflow.nodes.filter((node) => node.type !== 'start');
    workflow.edges = workflow.edges.filter((edge) => edge.source_node_id !== 'n_start');
    const result = validateGraph(workflow);
    expect(result.isValid).toBe(false);
    expect(findError(result, 'start node is required')).toBeDefined();
  });

  it('rejects a workflow with no end node', () => {
    const workflow = baseWorkflow();
    workflow.nodes = workflow.nodes.filter((node) => node.type !== 'end');
    workflow.edges = workflow.edges.filter((edge) => edge.target_node_id !== 'n_end');
    const result = validateGraph(workflow);
    expect(result.isValid).toBe(false);
    expect(findError(result, 'end node is required')).toBeDefined();
  });

  it('rejects a dangling edge endpoint', () => {
    const workflow = baseWorkflow();
    workflow.edges[1].source_node_id = 'n_missing';
    const result = validateGraph(workflow);
    expect(result.isValid).toBe(false);
    expect(findError(result, 'unknown source node')).toBeDefined();
  });

  it('rejects a duplicate node id', () => {
    const workflow = baseWorkflow();
    workflow.nodes.push({
      id: 'n_agent',
      type: 'condition',
      label: 'Dup Agent',
      position: { x: 0, y: 200 },
      config: {},
    });
    const result = validateGraph(workflow);
    expect(result.isValid).toBe(false);
    expect(findError(result, 'duplicate node id')).toBeDefined();
  });

  it('rejects an agent node missing required config references', () => {
    const workflow = baseWorkflow();
    workflow.nodes[1].config = {};
    const result = validateGraph(workflow);
    expect(result.isValid).toBe(false);
    expect(findError(result, 'agent_definition_id')).toBeDefined();
    expect(findError(result, 'model_profile_id')).toBeDefined();
    expect(findError(result, 'tool_policy_id')).toBeDefined();
  });

  it('rejects an agent node with a malformed UUID reference', () => {
    const workflow = baseWorkflow();
    workflow.nodes[1].config = {
      ...agentConfig(),
      model_profile_id: 'not-a-uuid',
    };
    const result = validateGraph(workflow);
    expect(result.isValid).toBe(false);
    expect(findError(result, 'must be a valid UUID')).toBeDefined();
  });

  it('rejects a node that is unreachable from the start', () => {
    const workflow = baseWorkflow();
    workflow.nodes.push({
      id: 'n_orphan',
      type: 'tool',
      label: 'Orphan',
      position: { x: 400, y: 0 },
      config: {},
    });
    workflow.edges.push({
      id: 'e5',
      source_node_id: 'n_orphan',
      target_node_id: 'n_end',
      output_mapping: {},
      on_error: 'fail',
      max_retries: 0,
    });
    const result = validateGraph(workflow);
    expect(result.isValid).toBe(false);
    expect(findError(result, 'not reachable from the start node')).toBeDefined();
  });

  it('rejects a node that is not co-reachable to an end', () => {
    const workflow = baseWorkflow();
    workflow.nodes.push({
      id: 'n_deadend',
      type: 'delay',
      label: 'Dead End',
      position: { x: 400, y: 100 },
      config: {},
    });
    workflow.edges.push({
      id: 'e6',
      source_node_id: 'n_agent',
      target_node_id: 'n_deadend',
      output_mapping: {},
      on_error: 'fail',
      max_retries: 0,
    });
    const result = validateGraph(workflow);
    expect(result.isValid).toBe(false);
    expect(findError(result, 'not co-reachable to an end node')).toBeDefined();
  });

  it('accepts all eleven node types in a converged graph', () => {
    const types = [
      'start',
      'agent',
      'condition',
      'gate',
      'parallel',
      'join',
      'human_approval',
      'tool',
      'memory',
      'delay',
      'end',
    ] as const;
    const workflow: WorkflowDefinition = {
      schema_version: '1.0',
      metadata: { name: 'all-types', version: 1, created_at: '2026-10-09T00:00:00Z' },
      nodes: types.map((type, index) => ({
        id: `n_${index}`,
        type,
        label: type,
        position: { x: index * 100, y: 0 },
        config: type === 'agent' ? agentConfig() : {},
      })),
      edges: types.slice(0, -1).map((_, index) => ({
        id: `e_${index}`,
        source_node_id: `n_${index}`,
        target_node_id: `n_${index + 1}`,
        output_mapping: {},
        on_error: 'fail',
        max_retries: 0,
      })),
    };
    const result = validateGraph(workflow);
    expect(result.isValid).toBe(true);
    expect(result.errors).toEqual([]);
  });
});
