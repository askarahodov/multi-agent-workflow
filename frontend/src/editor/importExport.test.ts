import { describe, expect, it, vi } from 'vitest';

import {
  buildExport,
  downloadWorkflow,
  importWorkflow,
  parseWorkflowText,
  validateWorkflowDocument,
} from './importExport';
import type { WorkflowDefinition } from '../workflow/types';

function validWorkflow(): WorkflowDefinition {
  return {
    schema_version: '1.0',
    metadata: { name: 'demo flow', version: 1, created_at: '2026-10-09T00:00:00Z' },
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

describe('export', () => {
  it('produces a JSON blob that validates against workflow.schema.json', async () => {
    const workflow = validWorkflow();
    const { blob, json, filename } = buildExport(workflow);

    expect(blob.type).toBe('application/json');
    expect(filename).toBe('demo_flow.json');
    expect(() => JSON.parse(json)).not.toThrow();

    const parsed = JSON.parse(json);
    const result = validateWorkflowDocument(parsed);
    expect(result.isValid).toBe(true);
  });

  it('serialises the exact definition (pretty-printed, round-trippable)', async () => {
    const workflow = validWorkflow();
    const { json } = buildExport(workflow);
    expect(JSON.parse(json)).toEqual(workflow);
  });

  it('downloadWorkflow triggers a DOM anchor download', () => {
    const click = vi.fn();
    const createObjectURL = vi.fn(() => 'blob:mock');
    const revokeObjectURL = vi.fn();

    const cloneAnchor = (): HTMLAnchorElement =>
      ({ click, download: '', href: '' }) as unknown as HTMLAnchorElement;

    vi.stubGlobal('URL', { createObjectURL, revokeObjectURL });
    const createElement = vi
      .spyOn(document, 'createElement')
      .mockReturnValueOnce(cloneAnchor() as unknown as HTMLElement);
    const appendChild = vi.spyOn(document.body, 'appendChild').mockImplementation(() => document.body);
    const removeChild = vi.spyOn(document.body, 'removeChild').mockImplementation(() => document.body);

    try {
      downloadWorkflow(validWorkflow());
    } finally {
      createElement.mockRestore();
      appendChild.mockRestore();
      removeChild.mockRestore();
      vi.unstubAllGlobals();
    }

    expect(click).toHaveBeenCalledTimes(1);
    expect(createObjectURL).toHaveBeenCalledTimes(1);
    expect(revokeObjectURL).toHaveBeenCalledWith('blob:mock');
  });
});

describe('import', () => {
  it('round-trips a valid file back to the identical workflow', async () => {
    const workflow = validWorkflow();
    const outcome = parseWorkflowText(JSON.stringify(workflow, null, 2));

    expect(outcome.ok).toBe(true);
    expect(outcome.workflow).toEqual(workflow);
    expect(outcome.errors).toEqual([]);
  });

  it('importWorkflow reads a File and returns the parsed workflow', async () => {
    const workflow = validWorkflow();
    const file = {
      text: () => Promise.resolve(JSON.stringify(workflow)),
      type: 'application/json',
      name: 'demo.json',
      size: JSON.stringify(workflow).length,
    } as unknown as File;
    const outcome = await importWorkflow(file);

    expect(outcome.ok).toBe(true);
    expect(outcome.workflow).toEqual(workflow);
  });

  it('rejects malformed JSON with a parse error and no store mutation', () => {
    const outcome = parseWorkflowText('{ not valid json');

    expect(outcome.ok).toBe(false);
    expect(outcome.workflow).toBeUndefined();
    expect(outcome.errors[0]?.message).toContain('invalid JSON');
  });

  it('rejects a document that fails the JSON Schema (missing edges)', () => {
    const bad = { ...validWorkflow() };
    delete (bad as Partial<WorkflowDefinition>).edges;

    const outcome = parseWorkflowText(JSON.stringify(bad));

    expect(outcome.ok).toBe(false);
    expect(outcome.workflow).toBeUndefined();
    expect(outcome.errors.length).toBeGreaterThan(0);
  });

  it('rejects a graph-invalid document (cycle) with path-specific errors', () => {
    const cycle = validWorkflow();
    cycle.edges.push({ id: 'e3', source_node_id: 'n_end', target_node_id: 'n_start', output_mapping: {}, on_error: 'skip', max_retries: 1 });

    const outcome = parseWorkflowText(JSON.stringify(cycle));

    expect(outcome.ok).toBe(false);
    expect(outcome.workflow).toBeUndefined();
    expect(outcome.errors.some((e) => e.message.includes('acyclic'))).toBe(true);
  });

  it('rejects a schema-invalid document (bad node type) via JSON Schema', () => {
    const bad = validWorkflow();
    (bad.nodes[0] as { type: string }).type = 'not-a-node';

    const outcome = parseWorkflowText(JSON.stringify(bad));

    expect(outcome.ok).toBe(false);
    expect(outcome.workflow).toBeUndefined();
    expect(outcome.errors.length).toBeGreaterThan(0);
  });
});