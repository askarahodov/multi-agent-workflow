import type { WorkflowDefinition } from './types';

export interface ValidationError {
  /** JSON-Pointer-like path to the offending field, e.g. `nodes[1].id`. */
  path: string;
  message: string;
}

export interface ValidationResult {
  isValid: boolean;
  errors: ValidationError[];
}

/**
 * Matches RFC 4122 / RFC 9562 UUIDs (v1..v8 all allowed). The approved schema
 * references agent definitions, model profiles and tool policies by UUID.
 */
const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

const AGENT_REF_FIELDS = ['agent_definition_id', 'model_profile_id', 'tool_policy_id'] as const;

/**
 * Pure graph validator for the canonical Workflow Definition document.
 *
 * Enforces the graph-level invariants from the approved schema:
 *  - unique node ids
 *  - edge endpoints must exist
 *  - exactly one `start` node
 *  - at least one `end` node
 *  - no cycles (the graph must be a DAG)
 *  - every node reachable from the start node
 *  - every node co-reachable to an end node
 *  - `agent` nodes require agent_definition_id, model_profile_id, tool_policy_id
 *    as valid UUIDs
 *
 * The function is pure and side-effect free; it makes no assumptions about the
 * host environment and can be used from the browser, server, or tests.
 */
export function validateGraph(workflow: WorkflowDefinition): ValidationResult {
  const errors: ValidationError[] = [];
  const { nodes, edges } = workflow;

  const seen = new Set<string>();
  const nodeById = new Map<string, { type: string }>();
  nodes.forEach((node, index) => {
    if (seen.has(node.id)) {
      errors.push({
        path: `nodes[${index}].id`,
        message: `duplicate node id "${node.id}"`,
      });
      return;
    }
    seen.add(node.id);
    nodeById.set(node.id, { type: node.type });
  });

  edges.forEach((edge, index) => {
    if (!seen.has(edge.source_node_id)) {
      errors.push({
        path: `edges[${index}].source_node_id`,
        message: `edge references unknown source node "${edge.source_node_id}"`,
      });
    }
    if (!seen.has(edge.target_node_id)) {
      errors.push({
        path: `edges[${index}].target_node_id`,
        message: `edge references unknown target node "${edge.target_node_id}"`,
      });
    }
  });

  const startNodes = nodes.filter((node) => node.type === 'start');
  if (startNodes.length === 0) {
    errors.push({ path: 'nodes', message: 'exactly one start node is required (found 0)' });
  } else if (startNodes.length > 1) {
    errors.push({
      path: 'nodes',
      message: `exactly one start node is required (found ${startNodes.length})`,
    });
  }

  const endNodes = nodes.filter((node) => node.type === 'end');
  if (endNodes.length === 0) {
    errors.push({ path: 'nodes', message: 'at least one end node is required (found 0)' });
  }

  nodes.forEach((node, index) => {
    if (node.type !== 'agent') return;
    const config = node.config ?? {};
    for (const field of AGENT_REF_FIELDS) {
      const value = config[field];
      if (typeof value !== 'string' || value.length === 0) {
        errors.push({
          path: `nodes[${index}].config.${field}`,
          message: `agent node requires "${field}" as a UUID reference`,
        });
      } else if (!UUID_RE.test(value)) {
        errors.push({
          path: `nodes[${index}].config.${field}`,
          message: `agent node field "${field}" must be a valid UUID`,
        });
      }
    }
  });

  // Only build graph structure over nodes/edges whose endpoints exist so the
  // reachability and cycle checks do not crash on malformed inputs.
  const outAdj = new Map<string, string[]>();
  const inAdj = new Map<string, string[]>();
  for (const id of seen) {
    outAdj.set(id, []);
    inAdj.set(id, []);
  }
  for (const edge of edges) {
    if (seen.has(edge.source_node_id) && seen.has(edge.target_node_id)) {
      outAdj.get(edge.source_node_id)!.push(edge.target_node_id);
      inAdj.get(edge.target_node_id)!.push(edge.source_node_id);
    }
  }

  // Cycle detection via iterative DFS (white/grey/black).
  const WHITE = 0;
  const GRAY = 1;
  const BLACK = 2;
  const color = new Map<string, number>();
  for (const id of seen) color.set(id, WHITE);

  let hasCycle = false;
  const dfsStack: Array<{ id: string; next: number }> = [];
  for (const start of seen) {
    if (color.get(start) !== WHITE || hasCycle) break;
    color.set(start, GRAY);
    dfsStack.push({ id: start, next: 0 });
    while (dfsStack.length > 0 && !hasCycle) {
      const top = dfsStack[dfsStack.length - 1];
      const neighbors = outAdj.get(top.id)!;
      let descended = false;
      while (top.next < neighbors.length) {
        const neighbor = neighbors[top.next++];
        if (color.get(neighbor) === GRAY) {
          hasCycle = true;
          break;
        }
        if (color.get(neighbor) === WHITE) {
          color.set(neighbor, GRAY);
          dfsStack.push({ id: neighbor, next: 0 });
          descended = true;
          break;
        }
      }
      if (!descended) {
        color.set(top.id, BLACK);
        dfsStack.pop();
      }
    }
  }
  if (hasCycle) {
    errors.push({ path: 'edges', message: 'workflow graph must be acyclic (no cycles allowed)' });
  }

  // Every node must be reachable from the (single) start node.
  if (startNodes.length === 1) {
    const reachable = new Set<string>();
    const stack = [startNodes[0].id];
    while (stack.length > 0) {
      const current = stack.pop()!;
      if (reachable.has(current)) continue;
      reachable.add(current);
      for (const neighbor of outAdj.get(current)!) stack.push(neighbor);
    }
    for (const node of nodes) {
      if (!reachable.has(node.id)) {
        errors.push({
          path: `nodes[${node.id}]`,
          message: `node "${node.id}" is not reachable from the start node`,
        });
      }
    }
  }

  // Every node must be co-reachable to an end node (reverse traversal from all
  // end nodes).
  const endIds = new Set(endNodes.map((node) => node.id));
  const coReachable = new Set<string>();
  const reverseStack = [...endIds];
  while (reverseStack.length > 0) {
    const current = reverseStack.pop()!;
    if (coReachable.has(current)) continue;
    coReachable.add(current);
    for (const parent of inAdj.get(current)!) reverseStack.push(parent);
  }
  for (const node of nodes) {
    if (!coReachable.has(node.id)) {
      errors.push({
        path: `nodes[${node.id}]`,
        message: `node "${node.id}" is not co-reachable to an end node`,
      });
    }
  }

  return { isValid: errors.length === 0, errors };
}
