import { useEffect, useState } from 'react';

import type {
  AgentDefinitionRef,
  ApiAdapter,
  ModelProfileRef,
  ToolPolicyRef,
} from '../../api/types';
import { allPages } from '../paginateCatalog';
import { Field } from './fields';

/**
 * Fetch all server pages before offering a reference in the inspector.
 * Failed/cyclic pagination is not a valid partial catalog.
 */
export interface RefListState<T> {
  items: T[];
  loading: boolean;
  error: string | null;
}
function initialRefState<T>(): RefListState<T> {
  return { items: [], loading: true, error: null };
}
function useRefList<T>(
  loader: (api: ApiAdapter) => Promise<T[]>,
  api: ApiAdapter,
): RefListState<T> {
  const [loaded,setLoaded]=useState<{api:ApiAdapter;data:RefListState<T>}|null>(null);
  useEffect(() => {
    let active = true;
    setLoaded({api,data:initialRefState<T>()});
    loader(api)
      .then((items) => {
        if (active) setLoaded({api,data:{items,loading:false,error:null}});
      })
      .catch((error: unknown) => {
        if (active) setLoaded({api,data:{items:[],loading:false,
          error:error instanceof Error?error.message:String(error)}});
      });
    return () => { active = false; };
    // eslint-disable-next-line react-hooks/exhaustive-deps -- keyed on stable API adapter
  }, [api]);
  // During a same-component adapter switch, the previous adapter's
  // successful list must not appear even for one render.
  return loaded?.api===api ? loaded.data : initialRefState<T>();
}

export function useAgentDefinitions(api: ApiAdapter): RefListState<AgentDefinitionRef> {
  return useRefList((a) => allPages(after=>a.listAgentDefinitions({after,limit:100})),api);
}
export function useModelProfiles(api: ApiAdapter): RefListState<ModelProfileRef> {
  return useRefList((a) => allPages(after=>a.listModelProfiles({after,limit:100})),api);
}
export function useToolPolicies(api: ApiAdapter): RefListState<ToolPolicyRef> {
  return useRefList((a) => allPages(after=>a.listToolPolicies({after,limit:100})),api);
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
export function ReferenceSelect({
  label,value,options,loading,loadError,fieldError,testId,required,onChange,
}:ReferenceSelectProps) {
  return (
    <Field label={label} required={required} fieldError={fieldError} testId={testId}>
      <select
        data-testid={testId ? `${testId}-select` : undefined}
        value={value ?? ''}
        disabled={loading||Boolean(loadError)}
        onChange={(event) => onChange(event.target.value)}
        style={{ width: '100%', boxSizing: 'border-box', padding: 5 }}
      >
        <option value="">{loading ? 'Loading…' : '— none —'}</option>
        {options.map((option) => (
          <option key={option.id} value={option.id}>{option.label}</option>
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
