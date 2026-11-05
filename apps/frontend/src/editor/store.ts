import { create } from 'zustand';
import type { Node } from '@xyflow/react';
import type {
  NodeType,
  Position,
  WorkflowDefinition,
  WorkflowEdge,
  WorkflowNode,
  WorkflowNodeConfig,
} from '../workflow/types';
import { SCHEMA_VERSION } from '../workflow/types';

/**
 * The editor's canonical document is the exact SCHEMA `WorkflowDefinition`
 * (nodes with {id,type,label,position,config}, edges with
 * {id,source_node_id,target_node_id,output_mapping,on_error,max_retries}).
 * The canvas derives React Flow nodes/edges from this document on every
 * render, mapping `position` <-> {x,y}, so React Flow ids are always the
 * schema ids and there is a single source of truth.
 */

/** Human labels for the 11 approved node types. */
export const DEFAULT_NODE_LABELS: Record<NodeType, string> = {
  start: 'Start',
  agent: 'Agent',
  condition: 'Condition',
  gate: 'Gate',
  parallel: 'Parallel',
  join: 'Join',
  human_approval: 'Human Approval',
  tool: 'Tool',
  memory: 'Memory',
  delay: 'Delay',
  end: 'End',
};

/** Ordered list of every placeable node type (must match the schema enum). */
export const NODE_TYPES: NodeType[] = [
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
];

/** MIME key used to carry a node type through HTML5 drag-and-drop. */
export const PALETTE_DRAG_TYPE = 'application/workflow-node';

/** Extra payload carried on a React Flow node (kept out of the schema doc). */
export interface CanvasNodeData {
  [key: string]: unknown;
  label: string;
  nodeType: NodeType;
}

export type CanvasNode = Node<CanvasNodeData>;

let idCounter = 0;

/** Unique id generator (works in the browser, jsdom and node). */
function uniqueId(prefix: string): string {
  idCounter += 1;
  const random = Math.random().toString(36).slice(2, 10);
  return `${prefix}_${Date.now().toString(36)}_${random}${idCounter}`;
}

function emptyDefinition(): WorkflowDefinition {
  return {
    schema_version: SCHEMA_VERSION,
    metadata: {
      name: 'Untitled workflow',
      description: '',
      version: 1,
      created_at: new Date().toISOString(),
    },
    nodes: [],
    edges: [],
  };
}

export interface EditorState {
  past: WorkflowDefinition[];
  future: WorkflowDefinition[];
  undo: () => void;
  redo: () => void;
  /** Canonical workflow document held by the editor. */
  definition: WorkflowDefinition;
  selectedNodeId: string | null;
  selectedEdgeId: string | null;
  /** Place a new node of the given type at `position` (from a palette drop). */
  addNode: (type: NodeType, position: Position) => void;
  /** Move an existing node to `position` (React Flow drag). */
  moveNode: (id: string, position: Position) => void;
  /** Delete a node and every incident edge. */
  deleteNode: (id: string) => void;
  /** Create a new edge between two existing nodes. */
  addEdge: (sourceNodeId: string, targetNodeId: string) => void;
  deleteEdge: (id: string) => void;
  selectNode: (id: string | null) => void;
  selectEdge: (id: string | null) => void;
  /** Merge keys into a node's `config` (property-panel edits). */
  updateNodeConfig: (id: string, config: WorkflowNodeConfig) => void;
  /** Set a node's display label. */
  updateNodeLabel: (id: string, label: string) => void;
  /** Merge fields into an edge (property-panel edits). */
  updateEdge: (id: string, patch: Partial<Omit<WorkflowEdge, 'id'>>) => void;
  /** Replace the whole document (used by import / initial load). */
  load: (definition: WorkflowDefinition) => void;
  /** Reset to an empty document (new document / test isolation). */
  reset: () => void;
  updateMetadata: (patch: Partial<WorkflowDefinition['metadata']>) => void;
}


/** Bounded, document-local history. No undo across distinct loaded workflows. */
const HISTORY_LIMIT = 60;
function edited(state: EditorState, definition: WorkflowDefinition, extra: Partial<EditorState> = {}): Partial<EditorState> {
  if (JSON.stringify(state.definition) === JSON.stringify(definition)) return extra;
  return {
    definition,
    past: [...state.past, state.definition].slice(-HISTORY_LIMIT),
    future: [],
    ...extra,
  };
}

export const useEditorStore = create<EditorState>()((set) => ({
  past: [],
  future: [],
  undo: () => set((state) => {
    if (!state.past.length) return state;
    const previous = state.past[state.past.length - 1];
    return {definition:previous,past:state.past.slice(0,-1),
      future:[state.definition,...state.future].slice(0,HISTORY_LIMIT),
      selectedNodeId:null,selectedEdgeId:null};
  }),
  redo: () => set((state) => {
    if (!state.future.length) return state;
    const next = state.future[0];
    return {definition:next,past:[...state.past,state.definition].slice(-HISTORY_LIMIT),
      future:state.future.slice(1),selectedNodeId:null,selectedEdgeId:null};
  }),
  definition: emptyDefinition(),
  selectedNodeId: null,
  selectedEdgeId: null,

  addNode: (type, position) =>
    set((state) => {
      const node: WorkflowNode = {
        id: uniqueId(type),
        type,
        label: DEFAULT_NODE_LABELS[type],
        position,
        config: {},
      };
      return {
        ...edited(state, { ...state.definition, nodes: [...state.definition.nodes, node] }),
      };
    }),

  moveNode: (id, position) =>
    set((state) => edited(state, {
      ...state.definition,
      nodes: state.definition.nodes.map((node) =>
        node.id === id ? { ...node, position } : node,
      ),
    })),

  deleteNode: (id) =>
    set((state) => {
      const nodes = state.definition.nodes.filter((node) => node.id !== id);
      const edges = state.definition.edges.filter(
        (edge) => edge.source_node_id !== id && edge.target_node_id !== id,
      );
      return edited(state, { ...state.definition, nodes, edges }, {
        selectedNodeId: state.selectedNodeId === id ? null : state.selectedNodeId,
      });
    }),

  addEdge: (sourceNodeId, targetNodeId) =>
    set((state) => {
      const edge: WorkflowEdge = {
        id: uniqueId('edge'),
        source_node_id: sourceNodeId,
        target_node_id: targetNodeId,
        output_mapping: {},
        on_error: 'fail',
        max_retries: 0,
      };
      return edited(state, { ...state.definition, edges: [...state.definition.edges, edge] });
    }),

  deleteEdge: (id) =>
    set((state) => edited(state, {
      ...state.definition,
      edges: state.definition.edges.filter((edge) => edge.id !== id),
    }, {selectedEdgeId: state.selectedEdgeId === id ? null : state.selectedEdgeId})),

  selectNode: (id) => set({ selectedNodeId: id, selectedEdgeId: null }),
  selectEdge: (id) => set({ selectedEdgeId: id, selectedNodeId: null }),

  updateNodeConfig: (id, config) =>
    set((state) => edited(state, {
      ...state.definition,
      nodes: state.definition.nodes.map((node) =>
        node.id === id ? { ...node, config: { ...node.config, ...config } } : node,
      ),
    })),

  updateNodeLabel: (id, label) =>
    set((state) => edited(state, {
      ...state.definition,
      nodes: state.definition.nodes.map((node) => node.id === id ? { ...node, label } : node),
    })),

  updateEdge: (id, patch) =>
    set((state) => edited(state, {
      ...state.definition,
      edges: state.definition.edges.map((edge) =>
        edge.id === id ? { ...edge, ...patch } : edge,
      ),
    })),

  load: (definition) => set({ definition, selectedNodeId: null, selectedEdgeId: null, past: [], future: [] }),
  reset: () => set({ definition: emptyDefinition(), selectedNodeId: null, selectedEdgeId: null, past: [], future: [] }),
  updateMetadata: (patch) => set((state) => edited(state, {
    ...state.definition, metadata: { ...state.definition.metadata, ...patch },
  })),
}));
