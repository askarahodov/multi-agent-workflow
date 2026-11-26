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


describe('explicit profile revisions', () => {
  it('rejects extra or incomplete revision fields in the canonical JSON schema', () => {
    const validate = ajv.compile(workflowSchema as object);
    const pin = { agent_role: 'tester', agent_definition_version: 2, model_profile_version: 3,
      tool_policy_version: 4, provider_id: '44444444-4444-4444-8444-444444444444', provider_version: 5 };
    const graph = (revision: unknown) => ({
      schema_version: '1.0', metadata: { name: 'pin', version: 1, created_at: '2026-11-05T00:00:00Z' },
      nodes: [{ id: 'a', type: 'agent', label: 'A', position: { x: 0, y: 0 },
        config: { profile_revision: revision } }], edges: [],
    });
    expect(validate(graph(pin))).toBe(true);
    for (const bad of [null, {}, { ...pin, role: 'forged' }, { ...pin, provider_version: true }, { ...pin, agent_role: 'tester\n' }]) {
      expect(validate(graph(bad))).toBe(false);
    }
  });
});
