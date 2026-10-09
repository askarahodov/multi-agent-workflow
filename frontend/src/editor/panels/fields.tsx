import type { ReactNode } from 'react';

/**
 * Shared form-field primitives used across the property panels (agent node
 * panel, non-agent node config, edge panel). Each field renders a labelled
 * input/select plus an optional inline validation message keyed to the field.
 */

export interface FieldShellProps {
  label: string;
  required?: boolean;
  /** Inline (field-level) validation message from the graph/schema validator. */
  fieldError?: string;
  children: ReactNode;
  testId?: string;
}

/** Label + children + inline error wrapper shared by every field. */
export function Field({ label, required, fieldError, children, testId }: FieldShellProps) {
  return (
    <label className="field" data-testid={testId} style={{ display: 'block', marginBottom: 12 }}>
      <span style={{ display: 'block', fontSize: 12, fontWeight: 600, marginBottom: 4 }}>
        {label}
        {required ? ' *' : ''}
      </span>
      {children}
      {fieldError ? (
        <span
          className="field-error"
          data-testid={testId ? `${testId}-error` : undefined}
          style={{ display: 'block', color: '#b91c1c', fontSize: 12, marginTop: 4 }}
        >
          {fieldError}
        </span>
      ) : null}
    </label>
  );
}

export interface TextFieldProps {
  label: string;
  value: string;
  onChange: (value: string) => void;
  placeholder?: string;
  fieldError?: string;
  testId?: string;
  required?: boolean;
  type?: 'text' | 'number';
}

export function TextField({
  label,
  value,
  onChange,
  placeholder,
  fieldError,
  testId,
  required,
  type = 'text',
}: TextFieldProps) {
  return (
    <Field label={label} required={required} fieldError={fieldError} testId={testId}>
      <input
        data-testid={testId ? `${testId}-input` : undefined}
        type={type}
        value={value ?? ''}
        placeholder={placeholder}
        onChange={(event) => onChange(event.target.value)}
        style={{ width: '100%', boxSizing: 'border-box', padding: 6 }}
      />
    </Field>
  );
}

export type SelectOption = string | { value: string; label: string };

export interface SelectFieldProps {
  label: string;
  value: string;
  onChange: (value: string) => void;
  options: readonly SelectOption[];
  placeholder?: string;
  fieldError?: string;
  testId?: string;
  required?: boolean;
}

export function SelectField({
  label,
  value,
  onChange,
  options,
  placeholder = '— select —',
  fieldError,
  testId,
  required,
}: SelectFieldProps) {
  const renderOption = (option: SelectOption, index: number) => {
    if (typeof option === 'string') {
      return (
        <option key={option} value={option}>
          {option}
        </option>
      );
    }
    return (
      <option key={`${option.value}-${index}`} value={option.value}>
        {option.label}
      </option>
    );
  };
  return (
    <Field label={label} required={required} fieldError={fieldError} testId={testId}>
      <select
        data-testid={testId ? `${testId}-select` : undefined}
        value={value ?? ''}
        onChange={(event) => onChange(event.target.value)}
        style={{ width: '100%', boxSizing: 'border-box', padding: 5 }}
      >
        <option value="">{placeholder}</option>
        {options.map(renderOption)}
      </select>
    </Field>
  );
}
