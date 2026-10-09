import { useMemo } from 'react';

import type { ApiAdapter } from '../api/types';
import { createApiClient } from '../api/client';
import type { WorkflowNode, WorkflowNodeConfig } from '../workflow/types';
import type { ValidationError } from '../workflow/validateGraph';
import { validateGraph } from '../workflow/validateGraph';
import { useEditorStore } from './store';
import AgentNodePanel from './panels/AgentNodePanel';
import EdgePanel from './panels/EdgePanel';
import { SelectField, TextField } from './panels/fields';

/** Approved gate_type enum (planner decision). */
const GATE_TYPES = ['automatic', 'manual_approval', 'quality_check'] as const;
/** Approved memory scope enum (planner decision). */
const MEMORY_SCOPES = ['project', 'workspace', 'conversation', 'agent'] as const;

export interface PropertyPanelProps {
  /** Optional ApiAdapter for reference selectors (defaults to the client mock). */
  api?: ApiAdapter;
}

/**
 * Extract field-level validation errors for the node at `index` from the full
 * validation result. Returns a map of config-field name -> message, plus a
 * `__node__` key for node-level (non-field) messages when present.
 */
function nodeFieldErrors(errors: ValidationError[], index: number): Record<string, string> {
  const map: Record<string, string> = {};
  const prefix = `nodes[${index}]`;
  for (const error of errors) {
    if (!error.path.startsWith(prefix)) continue;
    if (error.path === prefix) {
      map.__node__ ??= error.message;
      continue;
    }
    const suffix = error.path.slice(prefix.length + 1); // e.g. "config.agent_definition_id"
    if (suffix.startsWith('config.')) {
      const field = suffix.slice('config.'.length);
      map[field] ??= error.message;
    } else {
      map[suffix] ??= error.message;
    }
  }
  return map;
}

/** Extract field-level validation errors for the edge at `index`. */
function edgeFieldErrors(errors: ValidationError[], index: number): Record<string, string> {
  const map: Record<string, string> = {};
  const prefix = `edges[${index}]`;
  for (const error of errors) {
    if (!error.path.startsWith(prefix)) continue;
    if (error.path === prefix) {
      map.__edge__ ??= error.message;
    } else {
      map[error.path.slice(prefix.length + 1)] ??= error.message;
    }
  }
  return map;
}

export interface ConfigFieldsProps {
  node: WorkflowNode;
  fieldErrors: Record<string, string>;
  onConfigChange: (patch: WorkflowNodeConfig) => void;
}

/**
 * Configuration controls for every non-agent node type. The schema keeps node
 * `config` an open (`additionalProperties: true`) map, so each key below is a
 * documented convention shared between editor and saved definition; gate and
 * memory enums are fixed by the planner.
 */
function NodeConfigFields({ node, fieldErrors, onConfigChange }: ConfigFieldsProps) {
  const config = node.config ?? {};
  const str = (key: string): string =>
    typeof config[key] === 'string' ? (config[key] as string) : '';

  switch (node.type) {
    case 'gate':
      return (
        <>
          <TextField
            label="Contract id"
            value={str('contract_id')}
            onChange={(value) => onConfigChange({ contract_id: value || undefined })}
            fieldError={fieldErrors.contract_id}
            testId="contract_id"
          />
          <SelectField
            label="Gate type"
            testId="gate_type"
            value={str('gate_type')}
            onChange={(value) => onConfigChange({ gate_type: value || undefined })}
            options={GATE_TYPES}
            fieldError={fieldErrors.gate_type}
          />
        </>
      );
    case 'condition':
      return (
        <TextField
          label="Condition expression"
          value={str('expression')}
          onChange={(value) => onConfigChange({ expression: value || undefined })}
          placeholder="e.g. $result.verified === true"
          fieldError={fieldErrors.expression}
          testId="condition-expression"
        />
      );
    case 'tool':
      return (
        <>
          <TextField
            label="Tool name"
            value={str('tool_name')}
            onChange={(value) => onConfigChange({ tool_name: value || undefined })}
            fieldError={fieldErrors.tool_name}
            testId="tool_name"
          />
          <TextField
            label="Params (JSON)"
            value={str('params')}
            onChange={(value) => onConfigChange({ params: value || undefined })}
            placeholder='{"max_results": 5}'
            fieldError={fieldErrors.params}
            testId="params"
          />
        </>
      );
    case 'delay':
      return (
        <TextField
          label="Delay (ms)"
          type="number"
          value={str('delay_ms')}
          onChange={(value) =>
            onConfigChange({ delay_ms: value === '' ? undefined : Number(value) })
          }
          fieldError={fieldErrors.delay_ms}
          testId="delay_ms"
        />
      );
    case 'memory':
      return (
        <SelectField
          label="Memory scope"
          testId="memory_scope"
          value={str('scope')}
          onChange={(value) => onConfigChange({ scope: value || undefined })}
          options={MEMORY_SCOPES}
          fieldError={fieldErrors.scope}
        />
      );
    case 'start':
    case 'end':
    case 'parallel':
    case 'join':
    case 'human_approval':
      return (
        <p className="panel-hint" style={{ color: '#555', fontSize: 13 }}>
          This node type has no configuration fields.
        </p>
      );
    default:
      return null;
  }
}

/**
 * Right-hand property inspector. Reads the selection from the store, runs the
 * graph validator over the whole document, and routes to the agent node panel,
 * the generic node-config fields, or the edge panel — surfacing the validator's
 * errors inline under the offending field.
 */
export default function PropertyPanel({ api: apiProp }: PropertyPanelProps) {
  const api = useMemo(() => apiProp ?? createApiClient(), [apiProp]);
  const definition = useEditorStore((s) => s.definition);
  const selectedNodeId = useEditorStore((s) => s.selectedNodeId);
  const selectedEdgeId = useEditorStore((s) => s.selectedEdgeId);
  const updateNodeConfig = useEditorStore((s) => s.updateNodeConfig);
  const updateNodeLabel = useEditorStore((s) => s.updateNodeLabel);
  const updateEdge = useEditorStore((s) => s.updateEdge);

  const validation = useMemo(() => validateGraph(definition), [definition]);

  const selectedNodeIndex =
    selectedNodeId != null ? definition.nodes.findIndex((node) => node.id === selectedNodeId) : -1;
  const selectedNode = selectedNodeIndex >= 0 ? definition.nodes[selectedNodeIndex] : null;
  const nodeErrors = useMemo(
    () => (selectedNodeIndex >= 0 ? nodeFieldErrors(validation.errors, selectedNodeIndex) : {}),
    [validation, selectedNodeIndex],
  );

  const selectedEdgeIndex =
    selectedEdgeId != null ? definition.edges.findIndex((edge) => edge.id === selectedEdgeId) : -1;
  const selectedEdge = selectedEdgeIndex >= 0 ? definition.edges[selectedEdgeIndex] : null;
  const edgeErrors = useMemo(
    () => (selectedEdgeIndex >= 0 ? edgeFieldErrors(validation.errors, selectedEdgeIndex) : {}),
    [validation, selectedEdgeIndex],
  );

  return (
    <aside
      className="property-panel"
      data-testid="property-panel"
      style={{
        width: 320,
        borderLeft: '1px solid #d1d5db',
        background: '#fafafa',
        padding: 16,
        overflowY: 'auto',
        height: '100%',
        boxSizing: 'border-box',
      }}
    >
      {!selectedNode && !selectedEdge ? (
        <p className="panel-hint" style={{ color: '#666', fontSize: 13 }}>
          Select a node or edge to edit its properties.
        </p>
      ) : selectedNode ? (
        <>
          <h3 style={{ margin: '0 0 12px', fontSize: 15 }}>Node · {selectedNode.type}</h3>
          {nodeErrors.__node__ ? (
            <span
              className="panel-node-error"
              data-testid="node-level-error"
              style={{ display: 'block', color: '#b91c1c', fontSize: 12, marginBottom: 8 }}
            >
              {nodeErrors.__node__}
            </span>
          ) : null}
          {selectedNode.type === 'agent' ? (
            <AgentNodePanel
              node={selectedNode}
              fieldErrors={nodeErrors}
              api={api}
              onLabelChange={(label) => updateNodeLabel(selectedNode.id, label)}
              onConfigChange={(patch) => updateNodeConfig(selectedNode.id, patch)}
            />
          ) : (
            <>
              <TextField
                label="Label"
                value={selectedNode.label ?? ''}
                onChange={(label) => updateNodeLabel(selectedNode.id, label)}
                testId="node-label"
              />
              <NodeConfigFields
                node={selectedNode}
                fieldErrors={nodeErrors}
                onConfigChange={(patch) => updateNodeConfig(selectedNode.id, patch)}
              />
            </>
          )}
        </>
      ) : selectedEdge ? (
        <>
          <h3 style={{ margin: '0 0 12px', fontSize: 15 }}>Edge</h3>
          {edgeErrors.__edge__ ? (
            <span
              className="panel-node-error"
              data-testid="edge-level-error"
              style={{ display: 'block', color: '#b91c1c', fontSize: 12, marginBottom: 8 }}
            >
              {edgeErrors.__edge__}
            </span>
          ) : null}
          <EdgePanel
            edge={selectedEdge}
            fieldErrors={edgeErrors}
            onChangeEdge={(patch) => updateEdge(selectedEdge.id, patch)}
          />
        </>
      ) : null}
    </aside>
  );
}
