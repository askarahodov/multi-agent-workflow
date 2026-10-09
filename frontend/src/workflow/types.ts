/**
 * Canonical Workflow Definition types (schema_version "1.0").
 *
 * These mirror `workflow.schema.json` (Draft 2020-12). Graph-level invariants
 * that JSON Schema cannot express alone (single start, >=1 end, acyclicity,
 * reachability, unique ids, dangling endpoints, required agent references) are
 * enforced by `validateGraph`.
 */

export type NodeType =
  | 'start'
  | 'agent'
  | 'condition'
  | 'gate'
  | 'parallel'
  | 'join'
  | 'human_approval'
  | 'tool'
  | 'memory'
  | 'delay'
  | 'end';

export type ErrorAction = 'fail' | 'retry' | 'skip';

export const SCHEMA_VERSION = '1.0' as const;

export interface WorkflowMetadata {
  name: string;
  description?: string;
  version: number;
  created_at: string;
}

/**
 * Free-form configuration payload attached to a node. For `agent` nodes the
 * three reference fields below are required (as valid UUIDs) — enforced by
 * `validateGraph`.
 */
export interface WorkflowNodeConfig {
  [key: string]: unknown;
  agent_definition_id?: string;
  model_profile_id?: string;
  tool_policy_id?: string;
}

export interface Position {
  x: number;
  y: number;
}

export interface WorkflowNode {
  id: string;
  type: NodeType;
  label: string;
  position: Position;
  config: WorkflowNodeConfig;
}

export interface WorkflowEdge {
  id: string;
  source_node_id: string;
  target_node_id: string;
  output_mapping: Record<string, string>;
  condition?: string;
  on_error: ErrorAction;
  max_retries: number;
}

export interface WorkflowDefinition {
  schema_version: typeof SCHEMA_VERSION;
  metadata: WorkflowMetadata;
  nodes: WorkflowNode[];
  edges: WorkflowEdge[];
}
