/**
 * Schema validation gate (AT3).
 *
 * 1. Confirms `src/workflow/workflow.schema.json` itself conforms to the JSON
 *    Schema Draft 2020-12 meta-schema, compiled by ajv 8 in strict mode.
 * 2. Compiles the workflow schema as a validator and asserts that:
 *      - a minimal valid document passes,
 *      - `schema_version` is a required const "1.0" (wrong/missing version rejected).
 *
 * Exits 0 on success, 1 on failure. Run via `npm run schema:validate`.
 */
import Ajv2020 from 'ajv/dist/2020.js';
import addFormats from 'ajv-formats';
import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const root = join(dirname(fileURLToPath(import.meta.url)), '..');
const schemaPath = join(root, 'src', 'workflow', 'workflow.schema.json');
const schema = JSON.parse(readFileSync(schemaPath, 'utf8'));

const ajv = new Ajv2020({ strict: true, allErrors: true, validateFormats: true });
addFormats(ajv);

let failed = false;
function assert(condition, message) {
  if (condition) {
    console.log(`  PASS  ${message}`);
  } else {
    failed = true;
    console.error(`  FAIL  ${message}`);
  }
}

// 1) workflow.schema.json must conform to the Draft 2020-12 meta-schema.
const metaSchema = ajv.getSchema('https://json-schema.org/draft/2020-12/schema');
const metaOk = metaSchema ? metaSchema(schema) : false;
const metaErrors = metaSchema?.errors ?? [];
assert(
  metaOk,
  'workflow.schema.json conforms to the Draft 2020-12 meta-schema',
);
if (!metaOk) {
  console.error('meta-schema errors:', JSON.stringify(metaErrors, null, 2));
}

// 2) Compile the workflow schema as a strict validator.
const validate = ajv.compile(schema);

const minimalValid = {
  schema_version: '1.0',
  metadata: { name: 'minimal', version: 1, created_at: '2026-10-09T00:00:00Z' },
  nodes: [],
  edges: [],
};

assert(validate(minimalValid), 'minimal valid document validates');

const wrongVersion = { ...minimalValid, schema_version: '2.0' };
assert(!validate(wrongVersion), 'schema_version "2.0" is rejected (must be const "1.0")');

const missingVersion = {
  metadata: minimalValid.metadata,
  nodes: [],
  edges: [],
};
assert(!validate(missingVersion), 'missing schema_version is rejected (it is required)');

console.log(failed ? '\nSCHEMA VALIDATION FAILED' : '\nSCHEMA VALIDATION PASSED');
process.exit(failed ? 1 : 0);