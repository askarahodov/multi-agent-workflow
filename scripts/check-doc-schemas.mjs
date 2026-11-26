import { createRequire } from 'node:module';
import { readFileSync } from 'node:fs';
import assert from 'node:assert/strict';
// Reuse the locked frontend Ajv 2020-12 validator, no new dependency or network.
const require = createRequire(new URL('../apps/frontend/package.json', import.meta.url));
const Ajv2020 = require('ajv/dist/2020.js').default;
const ajv = new Ajv2020({strict:true, allErrors:true});
const read = name => JSON.parse(readFileSync(new URL('../docs/governance/'+name, import.meta.url), 'utf8'));
for (const name of ['documentation-inventory','checked-examples']) {
  const schema = read(name+'.schema.json');
  assert(ajv.validateSchema(schema), name+' invalid schema');
  const check = ajv.compile(schema);
  const data = read(name+'.json');
  assert(check(data), name+' invalid data: '+JSON.stringify(check.errors));
  assert(!check({...data,version:2}), name+' accepted wrong version');
  assert(!check({...data,unexpected:true}), name+' accepted extra field');
  const key = name==='documentation-inventory'?'records':'examples';
  const invalid=structuredClone(data);
  delete invalid[key][0][name==='documentation-inventory'?'owner':'files'];
  assert(!check(invalid), name+' accepted missing required field');
  console.log(name+': JSON Schema 2020-12 PASS');
}
