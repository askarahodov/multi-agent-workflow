import { beforeEach, describe, expect, it } from 'vitest';
import { act, cleanup, fireEvent, render, screen, within } from '@testing-library/react';

import PropertyPanel from './PropertyPanel';
import { useEditorStore } from './store';
import { createApiClient } from '../api/client';
import { MockAdapter } from '../api/mockAdapter';
import type { WorkflowNode } from '../workflow/types';

/** The panels' offline test client: property-panel selectors run against the
 * in-memory mock so the unit tests stay hermetic (no backend required). */
function mockApi() {
  return createApiClient({ mock: true });
}

function addNode(type: WorkflowNode['type']): string {
  let id = '';
  act(() => {
    const get = () => useEditorStore.getState();
    get().addNode(type, { x: 0, y: 0 });
    id = get().definition.nodes.find((n) => n.type === type)!.id;
  });
  return id;
}

function addEdge(sourceId: string, targetId: string): string {
  let id = '';
  act(() => {
    const get = () => useEditorStore.getState();
    get().addEdge(sourceId, targetId);
    id = get().definition.edges[get().definition.edges.length - 1].id;
  });
  return id;
}

function selectNode(id: string) {
  act(() => {
    useEditorStore.getState().selectNode(id);
  });
}

function selectEdge(id: string) {
  act(() => {
    useEditorStore.getState().selectEdge(id);
  });
}

function definition() {
  return useEditorStore.getState().definition;
}

beforeEach(() => {
  cleanup();
  useEditorStore.getState().reset();
});

describe('PropertyPanel node inspector', () => {
  it('T003-AT1: agent node renders agent/model/tool-policy selectors sourced from the api client', async () => {
    const api = mockApi();
    const agentId = addNode('agent');
    selectNode(agentId);
    render(<PropertyPanel api={api} />);

    // Reference selectors appear and are populated by the mock adapter.
    const agentSelect = await screen.findByTestId('agent_definition_id-select');
    await screen.findByRole('option', { name: 'Research Agent' });
    expect(within(agentSelect).getAllByRole('option').length).toBeGreaterThan(1);

    expect(screen.getByTestId('model_profile_id-select')).toBeInTheDocument();
    expect(screen.getByTestId('tool_policy_id-select')).toBeInTheDocument();
  });

  it('T003-AT1: edits to the reference selectors update the store node config', async () => {
    const api = mockApi();
    const agentId = addNode('agent');
    selectNode(agentId);
    render(<PropertyPanel api={api} />);

    const agentSelect = await screen.findByTestId('agent_definition_id-select');
    await screen.findByRole('option', { name: 'Research Agent' });

    act(() => {
      fireEvent.change(agentSelect, { target: { value: MockAdapter.seed.agentDefinitionId } });
      fireEvent.change(screen.getByTestId('model_profile_id-select'), {
        target: { value: MockAdapter.seed.modelProfileId },
      });
      fireEvent.change(screen.getByTestId('tool_policy_id-select'), {
        target: { value: MockAdapter.seed.toolPolicyId },
      });
    });

    const node = definition().nodes.find((n) => n.id === agentId)!;
    expect(node.config.agent_definition_id).toBe(MockAdapter.seed.agentDefinitionId);
    expect(node.config.model_profile_id).toBe(MockAdapter.seed.modelProfileId);
    expect(node.config.tool_policy_id).toBe(MockAdapter.seed.toolPolicyId);
  });

  it('T003-AT1: a missing required agent reference shows a field-level validation error', async () => {
    const agentId = addNode('agent');
    selectNode(agentId);
    render(<PropertyPanel api={mockApi()} />);

    // Await the reference lists loading so their post-mount setState settles
    // inside act, then assert the field errors (config is still empty).
    await screen.findByRole('option', { name: 'Research Agent' });

    expect(screen.getByTestId('agent_definition_id-error')).toHaveTextContent(
      /requires "agent_definition_id"/,
    );
    expect(screen.getByTestId('model_profile_id-error')).toHaveTextContent(
      /requires "model_profile_id"/,
    );
    expect(screen.getByTestId('tool_policy_id-error')).toHaveTextContent(
      /requires "tool_policy_id"/,
    );
  });

  it('renders non-agent node config controls by type (gate, tool, memory, delay, condition)', async () => {
    const gateId = addNode('gate');
    selectNode(gateId);
    render(<PropertyPanel api={mockApi()} />);

    expect(screen.getByTestId('contract_id-input')).toBeInTheDocument();
    const gateType = screen.getByTestId('gate_type-select');
    const gateOptions = within(gateType)
      .getAllByRole('option')
      .map((o) => o.textContent);
    expect(gateOptions).toEqual(['— select —', 'automatic', 'manual_approval', 'quality_check']);

    act(() => {
      fireEvent.change(gateType, { target: { value: 'manual_approval' } });
      fireEvent.change(screen.getByTestId('contract_id-input'), { target: { value: 'KYC-42' } });
    });
    const gate = definition().nodes.find((n) => n.id === gateId)!;
    expect(gate.config.gate_type).toBe('manual_approval');
    expect(gate.config.contract_id).toBe('KYC-42');

    cleanup();
    useEditorStore.getState().reset();
    const toolId = addNode('tool');
    selectNode(toolId);
    render(<PropertyPanel api={mockApi()} />);
    act(() => {
      fireEvent.change(screen.getByTestId('tool_name-input'), { target: { value: 'search' } });
      fireEvent.change(screen.getByTestId('params-input'), { target: { value: '{"n":2}' } });
    });
    const tool = definition().nodes.find((n) => n.id === toolId)!;
    expect(tool.config.tool_name).toBe('search');
    expect(tool.config.params).toBe('{"n":2}');

    cleanup();
    useEditorStore.getState().reset();
    const delayId = addNode('delay');
    selectNode(delayId);
    render(<PropertyPanel api={mockApi()} />);
    act(() => {
      fireEvent.change(screen.getByTestId('delay_ms-input'), { target: { value: '1500' } });
    });
    expect(definition().nodes.find((n) => n.id === delayId)!.config.delay_ms).toBe(1500);

    cleanup();
    useEditorStore.getState().reset();
    const memoryId = addNode('memory');
    selectNode(memoryId);
    render(<PropertyPanel api={mockApi()} />);
    act(() => {
      fireEvent.change(screen.getByTestId('memory_scope-select'), {
        target: { value: 'workspace' },
      });
    });
    expect(definition().nodes.find((n) => n.id === memoryId)!.config.scope).toBe('workspace');
  });

  it('editing the node label updates the store', async () => {
    const agentId = addNode('agent');
    selectNode(agentId);
    render(<PropertyPanel api={mockApi()} />);

    const labelInput = await screen.findByTestId('node-label-input');
    act(() => {
      fireEvent.change(labelInput, { target: { value: 'Research' } });
    });
    expect(definition().nodes.find((n) => n.id === agentId)!.label).toBe('Research');
  });
});

describe('PropertyPanel edge inspector', () => {
  it('T003-AT2: exposes output_mapping, condition, on_error (fail|retry|skip) and max_retries and persists changes', async () => {
    const startId = addNode('start');
    const endId = addNode('end');
    const edgeId = addEdge(startId, endId);
    selectEdge(edgeId);
    render(<PropertyPanel api={mockApi()} />);

    // output_mapping editor
    expect(screen.getByTestId('output_mapping')).toBeInTheDocument();
    act(() => {
      fireEvent.click(screen.getByTestId('output-mapping-add'));
    });
    act(() => {
      fireEvent.change(screen.getByTestId('output-mapping-key-0'), { target: { value: 'result' } });
      fireEvent.change(screen.getByTestId('output-mapping-value-0'), {
        target: { value: '$.answer' },
      });
    });

    const onError = screen.getByTestId('on_error-select');
    const errorOptions = within(onError)
      .getAllByRole('option')
      .map((o) => o.textContent);
    expect(errorOptions).toEqual(['— select —', 'fail', 'retry', 'skip']);

    act(() => {
      fireEvent.change(onError, { target: { value: 'retry' } });
      fireEvent.change(screen.getByTestId('condition-input'), {
        target: { value: '$ok === true' },
      });
      fireEvent.change(screen.getByTestId('max_retries-input'), { target: { value: '3' } });
    });

    const edge = definition().edges.find((e) => e.id === edgeId)!;
    expect(edge.output_mapping).toEqual({ result: '$.answer' });
    expect(edge.on_error).toBe('retry');
    expect(edge.condition).toBe('$ok === true');
    expect(edge.max_retries).toBe(3);
  });
});
