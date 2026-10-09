import { useCallback, useMemo, type DragEvent } from 'react';
import {
  Background,
  Controls,
  MiniMap,
  ReactFlow,
  ReactFlowProvider,
  useReactFlow,
  type Connection,
  type Edge,
  type EdgeChange,
  type Node,
  type NodeChange,
  type NodeTypes,
} from '@xyflow/react';
import '@xyflow/react/dist/style.css';

import type { Position, NodeType } from '../workflow/types';
import AgentNode from './nodes/AgentNode';
import GenericNode from './nodes/GenericNode';
import StartNode from './nodes/StartNode';
import { PALETTE_DRAG_TYPE, useEditorStore, type CanvasNodeData } from './store';

/** Map every schema node type to its React Flow renderer. */
const nodeTypes: NodeTypes = {
  start: StartNode,
  agent: AgentNode,
  condition: GenericNode,
  gate: GenericNode,
  parallel: GenericNode,
  join: GenericNode,
  human_approval: GenericNode,
  tool: GenericNode,
  memory: GenericNode,
  delay: GenericNode,
  end: GenericNode,
};

const PLACEABLE_TYPES = new Set<string>(Object.keys(nodeTypes));

function CanvasInner() {
  const { screenToFlowPosition } = useReactFlow();
  const nodes = useEditorStore((s) => s.definition.nodes);
  const edges = useEditorStore((s) => s.definition.edges);
  const selectedNodeId = useEditorStore((s) => s.selectedNodeId);
  const selectedEdgeId = useEditorStore((s) => s.selectedEdgeId);
  const addNode = useEditorStore((s) => s.addNode);
  const moveNode = useEditorStore((s) => s.moveNode);
  const deleteNode = useEditorStore((s) => s.deleteNode);
  const addEdge = useEditorStore((s) => s.addEdge);
  const deleteEdge = useEditorStore((s) => s.deleteEdge);
  const selectNode = useEditorStore((s) => s.selectNode);
  const selectEdge = useEditorStore((s) => s.selectEdge);

  // Derive React Flow nodes/edges from the canonical document. React Flow ids
  // are the schema ids; schema position is {x,y} which is exactly React Flow's.
  const rfNodes = useMemo<Node<CanvasNodeData>[]>(
    () =>
      nodes.map((node) => ({
        id: node.id,
        type: node.type,
        data: { label: node.label, nodeType: node.type } as CanvasNodeData,
        position: { x: node.position.x, y: node.position.y },
        selected: node.id === selectedNodeId,
      })),
    [nodes, selectedNodeId],
  );

  const rfEdges = useMemo<Edge[]>(
    () =>
      edges.map((edge) => ({
        id: edge.id,
        source: edge.source_node_id,
        target: edge.target_node_id,
        selected: edge.id === selectedEdgeId,
      })),
    [edges, selectedEdgeId],
  );

  const onNodesChange = useCallback(
    (changes: NodeChange[]) => {
      for (const change of changes) {
        if (change.type === 'position' && change.position) {
          moveNode(change.id, { x: change.position.x, y: change.position.y });
        } else if (change.type === 'remove') {
          deleteNode(change.id);
        }
      }
    },
    [moveNode, deleteNode],
  );

  const onEdgesChange = useCallback(
    (changes: EdgeChange[]) => {
      for (const change of changes) {
        if (change.type === 'remove') {
          deleteEdge(change.id);
        }
      }
    },
    [deleteEdge],
  );

  const onConnect = useCallback(
    (connection: Connection) => {
      if (connection.source && connection.target) {
        addEdge(connection.source, connection.target);
      }
    },
    [addEdge],
  );

  const onDragOver = useCallback((event: DragEvent) => {
    event.preventDefault();
    event.dataTransfer.dropEffect = 'move';
  }, []);

  const onDrop = useCallback(
    (event: DragEvent) => {
      event.preventDefault();
      const type = event.dataTransfer.getData(PALETTE_DRAG_TYPE) as NodeType;
      if (!type || !PLACEABLE_TYPES.has(type)) return;
      const position: Position = screenToFlowPosition({ x: event.clientX, y: event.clientY });
      addNode(type, position);
    },
    [addNode, screenToFlowPosition],
  );

  return (
    <ReactFlow
      nodes={rfNodes}
      edges={rfEdges}
      nodeTypes={nodeTypes}
      onNodesChange={onNodesChange}
      onEdgesChange={onEdgesChange}
      onConnect={onConnect}
      onDrop={onDrop}
      onDragOver={onDragOver}
      onNodeClick={(_, node) => selectNode(node.id)}
      onEdgeClick={(_, edge) => selectEdge(edge.id)}
      onPaneClick={() => {
        selectNode(null);
        selectEdge(null);
      }}
      fitView
      proOptions={{ hideAttribution: false }}
    >
      <Background />
      <Controls />
      <MiniMap />
    </ReactFlow>
  );
}

/**
 * Drag-and-drop canvas editor. Wrapped in a ReactFlowProvider so the inner
 * component can convert screen (drop) coordinates into flow coordinates via
 * `useReactFlow`. Pan/zoom, node dragging and edge creation are all native
 * React Flow behaviours fed back into the Zustand store.
 */
export default function WorkflowCanvas() {
  return (
    <ReactFlowProvider>
      <CanvasInner />
    </ReactFlowProvider>
  );
}
