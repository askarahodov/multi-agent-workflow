import assert from 'node:assert/strict'
import { test } from 'node:test'
import { installMermaidFence } from '../docs/.vitepress/mermaid-fence.mjs'

function createRenderer() {
  let originalCalls = 0
  const md = {
    renderer: { rules: { fence: () => { originalCalls++; return '<pre>original</pre>' } } },
    utils: { escapeHtml: (value) => value.replaceAll('&', '&amp;')
      .replaceAll('<', '&lt;').replaceAll('>', '&gt;')
      .replaceAll('"', '&quot;').replaceAll("'", '&#39;') },
  }
  installMermaidFence(md)
  return { md, originalCalls: () => originalCalls }
}

test('Mermaid fences render through client-only component with escaped expression', () => {
  const { md } = createRenderer()
  const malicious = '</div><script>alert("x")</script>&\nA --> B'
  const html = md.renderer.rules.fence([{ info: 'mermaid', content: malicious }], 0, {}, {}, {})
  assert.ok(html.startsWith('<ClientOnly><MermaidDiagram :source="'))
  assert.ok(html.endsWith('" /></ClientOnly>'))
  assert.ok(html.includes('&lt;script&gt;'))
  assert.ok(html.includes('&amp;'))
  assert.ok(html.includes('\\n'))
  assert.ok(!html.includes('<script>'))
  assert.ok(!html.includes('alert("x")'))
})

test('non-Mermaid fences keep the original markdown renderer', () => {
  const { md, originalCalls } = createRenderer()
  const fence = md.renderer.rules.fence
  assert.equal(fence([{ info: 'typescript', content: 'a' }], 0, {}, {}, {}), '<pre>original</pre>')
  assert.equal(fence([{ info: 'mermaidish', content: 'b' }], 0, {}, {}, {}), '<pre>original</pre>')
  assert.equal(originalCalls(), 2)
})

test('handles an empty Mermaid diagram without raw HTML injection', () => {
  const { md } = createRenderer()
  const html = md.renderer.rules.fence([{ info: 'mermaid', content: '' }], 0, {}, {}, {})
  assert.ok(html.includes('&quot;&quot;'))
})
