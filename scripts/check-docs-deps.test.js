import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { test } from 'node:test'
import { fileURLToPath } from 'node:url'
import { checkRetiredMathPlugin } from './check-docs-deps.js'

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..')

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
