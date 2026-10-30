import { useEffect, useState } from 'react';

import type {
  AgentDefinitionRef,
  ApiAdapter,
  CursorPage,
  ModelProfileRef,
  ToolPolicyRef,
} from '../../api/types';
import { Field } from './fields';

/**
 * Reference selectors for the property panels.
 *
 * Agent-definition / model-profile / tool-policy lists are populated through
 * the typed `ApiAdapter` surface defined by TASK-004 (`listAgentDefinitions`,
 * `listModelProfiles`, `listToolPolicies`). Until the orchestration server is
 * reachable the mock adapter serves canned UUID references, so offline
 * development and the unit tests use the exact same code path as the live HTTP
 * adapter — no panel depends on which backend is wired in.
 */

export interface RefListState<T> {
  items: T[];
  loading: boolean;
  error: string | null;
}

function initialRefState<T>(): RefListState<T> {
  return { items: [], loading: true, error: null };
}

/**
 * Fetches a cursor-paged reference list via the api adapter exactly once per
 * adapter instance (the loader closures are recreated every render but the
 * effect is keyed only on the stable `api`, so no refetch loop occurs).
 */
function useRefList<T>(
  loader: (api: ApiAdapter) => Promise<CursorPage<T>>,
  api: ApiAdapter,
): RefListState<T> {
  const [state, setState] = useState<RefListState<T>>(initialRefState<T>);
  useEffect(() => {
    let active = true;
    setState(initialRefState);
    loader(api)
      .then((page) => {
        if (active) setState({ items: page.items, loading: false, error: null });
      })
      .catch((error: unknown) => {
        if (active) {
          setState({ items: [], loading: false, error: errorMessage(error) });
        }
      });
    return () => {
      active = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps -- keyed on the stable adapter
  }, [api]);
  return state;
}

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

export function useAgentDefinitions(api: ApiAdapter): RefListState<AgentDefinitionRef> {
  return useRefList((a) => a.listAgentDefinitions(), api);
}

export function useModelProfiles(api: ApiAdapter): RefListState<ModelProfileRef> {
  return useRefList((a) => a.listModelProfiles(), api);
}

export function useToolPolicies(api: ApiAdapter): RefListState<ToolPolicyRef> {
  return useRefList((a) => a.listToolPolicies(), api);
}

export interface ReferenceSelectProps {
  label: string;
  value?: string;
  options: Array<{ id: string; label: string }>;
  loading?: boolean;
  loadError?: string | null;
  fieldError?: string;
  testId?: string;
  required?: boolean;
  onChange: (value: string) => void;
}

/**
 * A `<select>` populated with an entity's reference list (e.g. the model
 * profiles). Value is the referenced UUID; the internal `''` empty option is
 * used while loading or as an explicit "none" state that yields `undefined`.
 */
export function ReferenceSelect({
  label,
  value,
  options,
  loading,
  loadError,
  fieldError,
  testId,
  required,
  onChange,
}: ReferenceSelectProps) {
  return (
    <Field label={label} required={required} fieldError={fieldError} testId={testId}>
      <select
        data-testid={testId ? `${testId}-select` : undefined}
        value={value ?? ''}
        disabled={loading}
        onChange={(event) => onChange(event.target.value)}
        style={{ width: '100%', boxSizing: 'border-box', padding: 5 }}
      >
        <option value="">{loading ? 'Loading…' : '— none —'}</option>
        {options.map((option) => (
          <option key={option.id} value={option.id}>
            {option.label}
          </option>
        ))}
      </select>
      {loadError ? (
        <span
          className="ref-load-error"
          data-testid={testId ? `${testId}-load-error` : undefined}
          style={{ display: 'block', color: '#b91c1c', fontSize: 12, marginTop: 4 }}
        >
          Could not load options: {loadError}
        </span>
      ) : null}
    </Field>
  );
}
