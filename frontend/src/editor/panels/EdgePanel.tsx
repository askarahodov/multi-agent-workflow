import { useEffect, useState } from 'react';

import type { ErrorAction, WorkflowEdge } from '../../workflow/types';
import { SelectField, TextField } from './fields';

/** Approved on_error enum value for workflow edges (schema `errorActions`). */
export const ERROR_ACTIONS: readonly ErrorAction[] = ['fail', 'retry', 'skip'];

/** Inline removable pair used to edit `output_mapping`. */
interface MappingRow {
  key: string;
  value: string;
}

export interface EdgePanelProps {
  edge: WorkflowEdge;
  /** Inline field-level validation errors keyed by edge field name. */
  fieldErrors: Record<string, string>;
  onChangeEdge: (patch: Partial<Omit<WorkflowEdge, 'id'>>) => void;
}

function mapToRows(mapping: Record<string, string>): MappingRow[] {
  return Object.entries(mapping ?? {}).map(([key, value]) => ({ key, value }));
}

function rowsToMap(rows: MappingRow[]): Record<string, string> {
  const mapping: Record<string, string> = {};
  for (const row of rows) {
    const key = row.key.trim();
    if (key) mapping[key] = row.value;
  }
  return mapping;
}

/**
 * Inspector for a workflow edge. Exposes `output_mapping` (an editable set of
 * key/value pairs), the `condition` expression, the `on_error` policy and
 * `max_retries`, flushing each change through `onChangeEdge` so edits persist
 * into the store's edge object immediately.
 */
export default function EdgePanel({ edge, fieldErrors, onChangeEdge }: EdgePanelProps) {
  const [rows, setRows] = useState<MappingRow[]>(() => mapToRows(edge.output_mapping));

  // Re-seed the local row editor whenever a different edge is inspected
  // (switching selection), so the editor reflects the newly selected edge's
  // map. `output_mapping` itself is intentionally omitted from the deps: while
  // editing, local `rows` is already the source of truth (each keystroke
  // flushes `rowsToMap(rows)` to the store), so the effect must only reset on
  // a change of target edge.
  useEffect(() => {
    setRows(mapToRows(edge.output_mapping));
    // eslint-disable-next-line react-hooks/exhaustive-deps -- see comment above
  }, [edge.id]);

  return (
    <div className="edge-panel" data-testid="edge-panel">
      <div
        className="field"
        data-testid="output_mapping"
        style={{ display: 'block', marginBottom: 12 }}
      >
        <span style={{ display: 'block', fontSize: 12, fontWeight: 600, marginBottom: 4 }}>
          Output mapping
        </span>
        {rows.length === 0 ? (
          <em style={{ fontSize: 12, display: 'block', marginBottom: 6, color: '#555' }}>
            No output mapping — outputs pass through unchanged.
          </em>
        ) : null}
        {rows.map((row, index) => (
          <div
            key={index}
            data-testid={`output-mapping-row-${index}`}
            style={{ display: 'flex', gap: 6, marginBottom: 6 }}
          >
            <input
              data-testid={`output-mapping-key-${index}`}
              placeholder="output key"
              value={row.key}
              onChange={(event) => {
                const next = [...rows];
                next[index] = { ...next[index], key: event.target.value };
                setRows(next);
                onChangeEdge({ output_mapping: rowsToMap(next) });
              }}
              style={{ flex: 1, minWidth: 0, padding: 5 }}
            />
            <input
              data-testid={`output-mapping-value-${index}`}
              placeholder="source field"
              value={row.value}
              onChange={(event) => {
                const next = [...rows];
                next[index] = { ...next[index], value: event.target.value };
                setRows(next);
                onChangeEdge({ output_mapping: rowsToMap(next) });
              }}
              style={{ flex: 1, minWidth: 0, padding: 5 }}
            />
            <button
              type="button"
              data-testid={`output-mapping-remove-${index}`}
              onClick={() => {
                const next = rows.filter((_, i) => i !== index);
                setRows(next);
                onChangeEdge({ output_mapping: rowsToMap(next) });
              }}
              aria-label={`Remove output mapping row ${index + 1}`}
              style={{ padding: '0 8px' }}
            >
              ×
            </button>
          </div>
        ))}
        <button
          type="button"
          data-testid="output-mapping-add"
          onClick={() => {
            const next = [...rows, { key: '', value: '' }];
            setRows(next);
            onChangeEdge({ output_mapping: rowsToMap(next) });
          }}
          style={{ padding: '4px 10px' }}
        >
          + Add mapping
        </button>
        {fieldErrors.output_mapping ? (
          <span
            className="field-error"
            style={{ display: 'block', color: '#b91c1c', fontSize: 12 }}
          >
            {fieldErrors.output_mapping}
          </span>
        ) : null}
      </div>

      <TextField
        label="Condition"
        value={edge.condition ?? ''}
        onChange={(value) => onChangeEdge({ condition: value || undefined })}
        placeholder="e.g. $result.score >= 0.8"
        fieldError={fieldErrors.condition}
        testId="condition"
      />
      <SelectField
        label="On error"
        required
        value={edge.on_error}
        onChange={(value) => onChangeEdge({ on_error: value as ErrorAction })}
        options={ERROR_ACTIONS}
        fieldError={fieldErrors.on_error}
        testId="on_error"
      />
      <TextField
        label="Max retries"
        required
        type="number"
        value={String(edge.max_retries ?? 0)}
        onChange={(value) => {
          const parsed = Number(value);
          onChangeEdge({
            max_retries: Number.isFinite(parsed) && parsed >= 0 ? Math.trunc(parsed) : 0,
          });
        }}
        fieldError={fieldErrors.max_retries}
        testId="max_retries"
      />
    </div>
  );
}
