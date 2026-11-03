import assert from 'node:assert/strict'
import { mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { dirname, join, resolve } from 'node:path'
import { test } from 'node:test'
import { fileURLToPath } from 'node:url'
import { checkNodeWorkspaces, checkRetiredMathPlugin } from './check-docs-deps.js'

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..')

function withFixture(callback) {
  const fixture = mkdtempSync(join(tmpdir(), 'maw-dependency-policy-'))
  try {
    for (const workspace of ['.', 'apps/frontend']) {
      const dir = resolve(fixture, workspace)
      mkdirSync(dir, { recursive: true })
      writeFileSync(join(dir, 'package.json'), JSON.stringify({ dependencies: { safe: '1.0.0' } }))
      writeFileSync(join(dir, 'package-lock.json'), JSON.stringify({ packages: { '': {} } }))
    }
    callback(fixture)
  } finally {
    rmSync(fixture, { recursive: true, force: true })
  }
}

test('both checked-in npm dependency graphs are free of retired plugin', () => {
  assert.deepEqual(checkNodeWorkspaces(root), [])
})

test('frontend direct and transitive copies cannot bypass the offline guard', () => {
  withFixture(fixture => {
    const frontend = resolve(fixture, 'apps/frontend')
    writeFileSync(join(frontend, 'package.json'), JSON.stringify({
      dependencies: { 'markdown-it-katex': '^2.0.3' }
    }))
    writeFileSync(join(frontend, 'package-lock.json'), JSON.stringify({ packages: {
      '': {}, 'node_modules/example/node_modules/markdown-it-katex': { version: '2.0.3' }
    } }))
    assert.deepEqual(checkNodeWorkspaces(fixture), [
      'apps/frontend: package.json dependencies',
      'apps/frontend: package-lock.json node_modules/example/node_modules/markdown-it-katex'
    ])
  })
})

test('frontend npm alias is rejected even if installed package name differs', () => {
  withFixture(fixture => {
    const frontend = resolve(fixture, 'apps/frontend')
    writeFileSync(join(frontend, 'package.json'), JSON.stringify({
      devDependencies: { mathPlugin: 'npm:markdown-it-katex@2.0.3' }
    }))
    assert.deepEqual(checkNodeWorkspaces(fixture), [
      'apps/frontend: package.json devDependencies alias mathPlugin'
    ])
  })
})

test('missing or corrupted frontend lockfile fails closed', () => {
  withFixture(fixture => {
    const file = resolve(fixture, 'apps/frontend/package-lock.json')
    rmSync(file)
    assert.throws(() => checkNodeWorkspaces(fixture), /ENOENT/)
    writeFileSync(file, '{malformed json')
    assert.throws(() => checkNodeWorkspaces(fixture), /JSON|Expected|property|position/i)
  })
})

test('current docs dependency graph does not ship the retired math plugin', () => {
  const manifest = JSON.parse(readFileSync(resolve(root, 'package.json'), 'utf8'))
  const lock = JSON.parse(readFileSync(resolve(root, 'package-lock.json'), 'utf8'))
  assert.deepEqual(checkRetiredMathPlugin(manifest, lock), [])
})

test('rejects a direct dependency even if the lockfile has not been refreshed', () => {
  const manifest = { devDependencies: { 'markdown-it-katex': '^2.0.3' } }
  const lock = { packages: { '': {} } }
  assert.deepEqual(checkRetiredMathPlugin(manifest, lock), ['package.json devDependencies'])
})

test('rejects a nested transitive installed copy', () => {
  const manifest = { devDependencies: { vitepress: '^1.6.0' } }
  const lock = { packages: {
    '': { devDependencies: { vitepress: '^1.6.0' } },
    'node_modules/plugin/node_modules/markdown-it-katex': { version: '2.0.3' }
  } }
  assert.deepEqual(checkRetiredMathPlugin(manifest, lock), [
    'package-lock.json node_modules/plugin/node_modules/markdown-it-katex'
  ])
})

test('rejects a lockfile-only dependency declaration', () => {
  const lock = { packages: { '': { dependencies: { 'markdown-it-katex': '2.0.3' } } } }
  assert.deepEqual(checkRetiredMathPlugin({}, lock), [
    'package-lock.json (root) dependencies'
  ])
})

test('missing or damaged lockfile is not considered safe', () => {
  assert.throws(() => checkRetiredMathPlugin({}, {}), /packages object/)
  assert.throws(() => checkRetiredMathPlugin({}, { packages: [] }), /packages object/)
  assert.throws(() => checkRetiredMathPlugin(null, { packages: {} }), /package.json/)
})


test('rejects npm alias specifications and installed alias package names', () => {
  const alias = 'npm:markdown-it-katex@2.0.3'
  const manifest = { dependencies: { 'legacy-math': alias } }
  const lock = { packages: {
    '': { dependencies: { 'legacy-math': alias } },
    'node_modules/legacy-math': { name: 'markdown-it-katex', version: '2.0.3' }
  } }
  const violations = checkRetiredMathPlugin(manifest, lock)
  assert.ok(violations.includes('package.json dependencies alias legacy-math'))
  assert.ok(violations.includes('package-lock.json (root) dependencies alias legacy-math'))
  assert.ok(violations.includes('package-lock.json node_modules/legacy-math'))
})

test('rejects a nested transitive npm alias dependency', () => {
  const lock = { packages: {
    '': {},
    'node_modules/example': { dependencies: { renamed: 'npm:markdown-it-katex@^2.0.3' } }
  } }
  assert.deepEqual(checkRetiredMathPlugin({}, lock), [
    'package-lock.json node_modules/example dependencies alias renamed'
  ])
})

test('allows unrelated npm aliases and rejects malformed dependency entries', () => {
  const manifest = { dependencies: { safe: 'npm:markdown-it-katex-safe@1.0.0' } }
  assert.deepEqual(checkRetiredMathPlugin(manifest, { packages: { '': {} } }), [])
  assert.throws(() => checkRetiredMathPlugin({}, { packages: { '': null } }), /must be an object/)
  assert.throws(() => checkRetiredMathPlugin({ dependencies: 'invalid' }, {
    packages: { '': {} }
  }), /must be a dependency object/)
})
