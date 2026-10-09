import { beforeEach, describe, expect, it, vi } from 'vitest';
import { act, cleanup, fireEvent, render, screen } from '@testing-library/react';
import NodePalette from './NodePalette';
import WorkflowCanvas from './WorkflowCanvas';
import { NODE_TYPES, useEditorStore } from './store';

// React Flow does real DOM measurement and is not suited to jsdom unit tests;
// mock it to a thin shell that forwards the interaction callbacks, while the
// store (the real behaviour under test) is exercised in full.
vi.mock('@xyflow/react', () => {
  const box: { current: unknown } = { current: null };
  (globalThis as Record<string, unknown>).__workflowCanvasProps = box;

  const ReactFlowMock = (props: Record<string, unknown>) => {
    box.current = props;
    return (
      <div
        data-testid="rf-canvas"
        onDrop={props.onDrop as never}
        onDragOver={props.onDragOver as never}
      />
    );
  };

  return {
    ReactFlow: ReactFlowMock,
    ReactFlowProvider: ({ children }: { children?: React.ReactNode }) => <>{children}</>,
    Handle: () => null,
    MiniMap: () => null,
    Controls: () => null,
    Background: () => null,
    Position: { Left: 'left', Right: 'right', Top: 'top', Bottom: 'bottom' },
    useReactFlow: () => ({
      screenToFlowPosition: (point: { x: number; y: number }) => point,
    }),
  };
});

function renderEditor() {
  return render(
    <>
      <NodePalette />
      <WorkflowCanvas />
    </>,
  );
}

function persistedState() {
  return useEditorStore.getState().definition;
}

function canvasProps() {
  return (globalThis as any).__workflowCanvasProps.current;
}

beforeEach(() => {
  cleanup();
  useEditorStore.getState().reset();
});

describe('node palette', () => {
  it('renders all 11 approved node types', () => {
    renderEditor();
    expect(screen.getByTestId('node-palette')).toBeInTheDocument();
    for (const type of NODE_TYPES) {
      expect(screen.getByTestId(`palette-item-${type}`)).toBeInTheDocument();
    }
    expect(NODE_TYPES).toHaveLength(11);
  });
});

describe('WorkflowCanvas store integration', () => {
  it('dropping an agent palette item onto the canvas adds exactly one agent node', () => {
    renderEditor();
    const canvas = screen.getByTestId('rf-canvas');
    fireEvent.drop(canvas, {
      dataTransfer: {
        setData: vi.fn(),
        getData: (key: string) => (key === 'application/workflow-node' ? 'agent' : ''),
      },
    });
    const definition = persistedState();
    expect(definition.nodes).toHaveLength(1);
    expect(definition.nodes[0].type).toBe('agent');
    expect(definition.nodes[0].label).toBe('Agent');
  });

  it('connecting two node handles creates one edge with the correct source/target ids', () => {
    renderEditor();
    act(() => {
      useEditorStore.getState().addNode('start', { x: 0, y: 0 });
      useEditorStore.getState().addNode('end', { x: 200, y: 0 });
    });
    const current = useEditorStore.getState();
    const startId = current.definition.nodes.find((n) => n.type === 'start')!.id;
    const endId = current.definition.nodes.find((n) => n.type === 'end')!.id;

    act(() => {
      canvasProps().onConnect({ source: startId, target: endId, sourceHandle: null, targetHandle: null });
    });

    const definition = persistedState();
    expect(definition.edges).toHaveLength(1);
    expect(definition.edges[0].source_node_id).toBe(startId);
    expect(definition.edges[0].target_node_id).toBe(endId);
    expect(definition.edges[0].on_error).toBe('fail');
    expect(definition.edges[0].max_retries).toBe(0);
  });

  it('deleting a node removes its incident edges', () => {
    renderEditor();
    let startId = '';
    let agentId = '';
    let endId = '';
    act(() => {
      const get = () => useEditorStore.getState();
      get().addNode('start', { x: 0, y: 0 });
      get().addNode('agent', { x: 200, y: 0 });
      get().addNode('end', { x: 400, y: 0 });
      const ids = get().definition.nodes;
      startId = ids.find((n) => n.type === 'start')!.id;
      agentId = ids.find((n) => n.type === 'agent')!.id;
      endId = ids.find((n) => n.type === 'end')!.id;
      get().addEdge(startId, agentId);
      get().addEdge(agentId, endId);
    });
    expect(persistedState().edges).toHaveLength(2);

    act(() => {
      useEditorStore.getState().deleteNode(agentId);
    });

    const definition = persistedState();
    expect(definition.nodes.find((n) => n.id === agentId)).toBeUndefined();
    expect(definition.nodes).toHaveLength(2);
    // Both the incoming (start->agent) and outgoing (agent->end) edges removed.
    expect(definition.edges).toHaveLength(0);
  });

  it('moves a node position through a position change', () => {
    renderEditor();
    let nodeId = '';
    act(() => {
      useEditorStore.getState().addNode('tool', { x: 0, y: 0 });
      nodeId = useEditorStore.getState().definition.nodes[0].id;
      canvasProps().onNodesChange?.([{ type: 'position', id: nodeId, position: { x: 50, y: 60 } }]);
    });
    const node = useEditorStore.getState().definition.nodes[0];
    expect(node.position).toEqual({ x: 50, y: 60 });
  });
});
