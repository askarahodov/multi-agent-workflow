import { useState } from 'react';
import type { ApiAdapter } from '../../api/types';
import { createApiClient } from '../../api/client';
import type { WorkflowNode, WorkflowNodeConfig } from '../../workflow/types';
import { TextField } from './fields';
import { validProfileRevision, PROFILE_VERSION_FIELDS } from '../../workflow/validateGraph';
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

  const pin = config.profile_revision;
  const pinned = pin !== undefined;
  const [draft, setDraft] = useState({ nodeId: '', value: '' });
  const raw = draft.nodeId === node.id ? draft.value : '';
  let parsed: unknown;
  try { parsed = JSON.parse(raw); } catch { parsed = null; }
  const validDraft = validProfileRevision(parsed);

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
        disabled={pinned}
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
        disabled={pinned}
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
        disabled={pinned}
        onChange={(value) => onConfigChange({ tool_policy_id: value || undefined })}
      />
      <section aria-label="Версии профиля" data-testid="profile-revision">
        {pinned ? (
          <>
            <p>Версии закреплены. Смена ссылок требует явного снятия закрепления.</p>
            {validProfileRevision(pin) ? (
              <p>Роль: {pin.agent_role}; {PROFILE_VERSION_FIELDS.map((field) =>
                `${field}: ${pin[field]}`).join('; ')}; provider: {pin.provider_id}</p>
            ) : <p role="alert">Некорректные версии профиля.</p>}
            <button type="button" onClick={() => onConfigChange({ profile_revision: undefined })}>
              Снять закрепление версий
            </button>
          </>
        ) : (
          <>
            <p>Версии не закреплены. Вставьте только шесть проверенных полей версии
              из snapshot v2, без промпта, ключей или других данных.</p>
            <textarea aria-label="Метаданные версии профиля" value={raw}
              onChange={(event) => setDraft({ nodeId: node.id, value: event.target.value })} />
            {raw && !validDraft ? <p role="alert">Некорректные метаданные версии.</p> : null}
            <button type="button" disabled={!validDraft || !agentValue || !modelValue || !toolValue}
              onClick={() => {
                if (validProfileRevision(parsed)) {
                  onConfigChange({ profile_revision: parsed });
                  setDraft({ nodeId: '', value: '' });
                }
              }}>Закрепить версии</button>
          </>
        )}
      </section>
    </div>
  );
}
