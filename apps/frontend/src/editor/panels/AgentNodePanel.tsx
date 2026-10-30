import type { ApiAdapter } from '../../api/types';
import { createApiClient } from '../../api/client';
import type { WorkflowNode, WorkflowNodeConfig } from '../../workflow/types';
import { TextField } from './fields';
import {
  ReferenceSelect,
  useAgentDefinitions,
  useModelProfiles,
  useToolPolicies,
} from './referenceSelectors';

export interface AgentNodePanelProps {
  node: WorkflowNode;
  /** Inline field-level validation errors keyed by config field name. */
  fieldErrors: Record<string, string>;
  api?: ApiAdapter;
  onLabelChange: (label: string) => void;
  onConfigChange: (patch: WorkflowNodeConfig) => void;
}

/**
 * Inspector for `agent` nodes. Provides editable label plus the three required
 * reference selectors (agent definition, model profile, tool policy) populated
 * from the ApiAdapter. Required-agent-reference validation errors from the
 * graph validator surface inline under their respective selector.
 */
export default function AgentNodePanel({
  node,
  fieldErrors,
  api,
  onLabelChange,
  onConfigChange,
}: AgentNodePanelProps) {
  const client = api ?? createApiClient();
  const agents = useAgentDefinitions(client);
  const models = useModelProfiles(client);
  const tools = useToolPolicies(client);
  const config = node.config ?? {};

  const agentValue =
    typeof config.agent_definition_id === 'string' ? config.agent_definition_id : '';
  const modelValue = typeof config.model_profile_id === 'string' ? config.model_profile_id : '';
  const toolValue = typeof config.tool_policy_id === 'string' ? config.tool_policy_id : '';

  return (
    <div className="agent-node-panel" data-testid="agent-node-panel">
      <TextField
        label="Label"
        value={node.label ?? ''}
        onChange={onLabelChange}
        testId="node-label"
      />
      <ReferenceSelect
        label="Agent definition"
        required
        testId="agent_definition_id"
        value={agentValue}
        options={agents.items.map((item) => ({ id: item.id, label: item.name }))}
        loading={agents.loading}
        loadError={agents.error}
        fieldError={fieldErrors.agent_definition_id}
        onChange={(value) => onConfigChange({ agent_definition_id: value || undefined })}
      />
      <ReferenceSelect
        label="Model profile"
        required
        testId="model_profile_id"
        value={modelValue}
        options={models.items.map((item) => ({
          id: item.id,
          label: item.display_name ?? item.name,
        }))}
        loading={models.loading}
        loadError={models.error}
        fieldError={fieldErrors.model_profile_id}
        onChange={(value) => onConfigChange({ model_profile_id: value || undefined })}
      />
      <ReferenceSelect
        label="Tool policy"
        required
        testId="tool_policy_id"
        value={toolValue}
        options={tools.items.map((item) => ({ id: item.id, label: item.name }))}
        loading={tools.loading}
        loadError={tools.error}
        fieldError={fieldErrors.tool_policy_id}
        onChange={(value) => onConfigChange({ tool_policy_id: value || undefined })}
      />
    </div>
  );
}
