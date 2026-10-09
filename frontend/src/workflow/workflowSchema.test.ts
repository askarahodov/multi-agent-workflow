import Ajv2020 from 'ajv/dist/2020.js';
import addFormats from 'ajv-formats';
import { describe, expect, it } from 'vitest';
import workflowSchema from './workflow.schema.json';

const ajv = new Ajv2020({ strict: true, allErrors: true, validateFormats: true });
addFormats(ajv);

const metaSchemaUri = 'https://json-schema.org/draft/2020-12/schema';

function compileUnderMetaSchema() {
  const schema = workflowSchema as object;
  const meta = ajv.getSchema(metaSchemaUri);
  const conforms = meta ? meta(schema) : false;
  return { conforms, metaErrors: meta?.errors ?? [] };
}

describe('workflow.schema.json (Draft 2020-12)', () => {
  it('compiles cleanly as a strict ajv schema (AT3)', () => {
    // Compiling in strict mode throws if the schema contains invalid/unknown
    // keywords. If it compiles without throwing, it is a valid schema.
    expect(() => ajv.compile(workflowSchema as object)).not.toThrow();
  });

  it('conforms to the Draft 2020-12 meta-schema (AT3)', () => {
    const { conforms, metaErrors } = compileUnderMetaSchema();
    expect(conforms).toBe(true);
    expect(metaErrors).toEqual([]);
  });

  it('declares schema_version as a required const "1.0" (AT3)', () => {
    const validate = ajv.compile(workflowSchema as object);
    const valid = {
      schema_version: '1.0',
      metadata: { name: 'm', version: 1, created_at: '2026-10-09T00:00:00Z' },
      nodes: [],
      edges: [],
    };
    expect(validate(valid)).toBe(true);

    const wrongVersion = { ...valid, schema_version: '2.0' };
    expect(validate(wrongVersion)).toBe(false);

    const { schema_version: _dropped, ...missingVersion } = valid as Record<string, unknown>;
    expect(validate(missingVersion)).toBe(false);
  });
});
