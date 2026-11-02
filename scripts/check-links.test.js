import assert from 'node:assert/strict'
import { mkdtempSync, mkdirSync, writeFileSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import path from 'node:path'
import { test } from 'node:test'
import { resolveLink } from './check-links.js'

test('VitePress root absolute routes, clean URLs, and assets resolve correctly', () => {
  const root = mkdtempSync(path.join(tmpdir(), 'docs-links-'))
  try {
    mkdirSync(path.join(root, 'guide'), { recursive: true })
    mkdirSync(path.join(root, 'assets', 'chunks'), { recursive: true })
    writeFileSync(path.join(root, 'index.html'), '')
    writeFileSync(path.join(root, 'guide', 'start.html'), '')
    writeFileSync(path.join(root, 'guide', 'index.html'), '')
    writeFileSync(path.join(root, 'assets', 'chunks', 'app.js'), '')
    writeFileSync(path.join(root, 'favicon.ico'), '')
    const page = path.join(root, 'guide', 'start.html')
    assert.equal(resolveLink('/', page, root), path.join(root, 'index.html'))
    assert.equal(resolveLink('/guide/start', page, root), path.join(root, 'guide', 'start.html'))
    assert.equal(resolveLink('/guide/', page, root), path.join(root, 'guide', 'index.html'))
    assert.equal(resolveLink('/assets/chunks/app.js', page, root), path.join(root, 'assets', 'chunks', 'app.js'))
    assert.equal(resolveLink('/favicon.ico', page, root), path.join(root, 'favicon.ico'))
    assert.equal(resolveLink('../guide/start?x=1#intro', page, root), path.join(root, 'guide', 'start.html'))
    assert.equal(resolveLink('/missing', page, root), path.join(root, 'missing', 'index.html'))
    assert.equal(resolveLink('/../../outside', page, root), null)
  } finally {
    rmSync(root, { recursive: true, force: true })
  }
})
