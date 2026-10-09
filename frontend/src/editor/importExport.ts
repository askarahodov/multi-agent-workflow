/**
 * JSON export/import for workflow definitions.
 *
 * Export serialises a `WorkflowDefinition` to a `.json` Blob / file for
 * download. Import parses a file, validates it against `workflow.schema.json`
 * (Draft 2020-12) AND the graph validator, and only then returns the accepted
 * document. The module is deliberately side-effect free with respect to any
 * store: on rejection it returns field-level errors and performs NO store
 * mutation — the caller decides whether to commit the accepted document.
 */

import Ajv2020 from 'ajv/dist/2020.js';
import { type ErrorObject, type ValidateFunction } from 'ajv';
import addFormats from 'ajv-formats';

import schema from '../workflow/workflow.schema.json';
import type { WorkflowDefinition } from '../workflow/types';
import { validateGraph } from '../workflow/validateGraph';
import type { ValidationError, ValidationResult } from '../workflow/validateGraph';

export interface ExportResult {
  /** Pretty-printed JSON text of the definition. */
  json: string;
  /** `application/json` Blob suitable for a download link. */
  blob: Blob;
  /** Sanitised `*.json` filename derived from the workflow name. */
  filename: string;
}

export interface ImportOutcome {
  ok: boolean;
  /** Present exactly when `ok` is `true`. */
  workflow?: WorkflowDefinition;
  /** Field-level validation errors when `ok` is `false`. */
  errors: ValidationError[];
}

let compiled: ValidateFunction | undefined;

function schemaValidator(): ValidateFunction {
  if (!compiled) {
    const ajv = new Ajv2020({ allErrors: true, strict: true, validateFormats: true });
    addFormats(ajv);
    compiled = ajv.compile(schema);
  }
  return compiled;
}

function ajvErrorsToValidationErrors(errors: ErrorObject[] | null | undefined): ValidationError[] {
  if (!errors) return [];
  return errors.map((error) => ({
    path: error.instancePath || '#',
    message: error.message ? `${error.message}${error.params ? ` (${JSON.stringify(error.params)})` : ''}` : 'schema violation',
  }));
}

/**
 * Validates an arbitrary parsed value against the workflow JSON Schema and the
 * graph invariants. Returns `isValid: false` with path-specific errors when
 * either layer rejects the document.
 */
export function validateWorkflowDocument(doc: unknown): ValidationResult {
  const validate = schemaValidator();
  const schemaErrors: ValidationError[] = [];
  if (!validate(doc)) {
    schemaErrors.push(...ajvErrorsToValidationErrors(validate.errors));
  }
  if (schemaErrors.length > 0) {
    return { isValid: false, errors: schemaErrors };
  }
  return validateGraph(doc as WorkflowDefinition);
}

function sanitiseFilename(name: string): string {
  const safe = name.replace(/[^a-zA-Z0-9_-]+/g, '_').replace(/^_+|_+$/g, '') || 'workflow';
  return `${safe}.json`;
}

/** Builds the downloadable JSON export without touching the DOM. */
export function buildExport(workflow: WorkflowDefinition, filename?: string): ExportResult {
  const json = JSON.stringify(workflow, null, 2);
  const blob = new Blob([json], { type: 'application/json' });
  return { json, blob, filename: filename ?? sanitiseFilename(workflow.metadata.name) };
}

/** Triggers a browser download of the workflow definition. */
export function downloadWorkflow(workflow: WorkflowDefinition, filename?: string): void {
  const { blob, filename: resolved } = buildExport(workflow, filename);
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement('a');
  anchor.href = url;
  anchor.download = resolved;
  document.body.appendChild(anchor);
  anchor.click();
  document.body.removeChild(anchor);
  URL.revokeObjectURL(url);
}

/** Parses raw text and validates it; never mutates any store on failure. */
export function parseWorkflowText(text: string): ImportOutcome {
  let parsed: unknown;
  try {
    parsed = JSON.parse(text);
  } catch (error) {
    return {
      ok: false,
      errors: [{ path: '#', message: `invalid JSON: ${(error as Error).message}` }],
    };
  }

  const result = validateWorkflowDocument(parsed);
  if (!result.isValid) {
    return { ok: false, errors: result.errors };
  }
  return { ok: true, workflow: parsed as WorkflowDefinition, errors: [] };
}

/** Reads a `File` and returns a validated import outcome (store untouched). */
export async function importWorkflow(file: File): Promise<ImportOutcome> {
  const text = await file.text();
  return parseWorkflowText(text);
}