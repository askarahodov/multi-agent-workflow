/** Render Mermaid fences as a safe Vue component rather than an outdated plugin.
 * The expression is JSON-encoded first, then HTML attribute-escaped. Never
 * embed untrusted diagram text directly in template/HTML source.
 */
export function installMermaidFence(md) {
  const original = md.renderer.rules.fence
  md.renderer.rules.fence = (tokens, index, options, env, self) => {
    const token = tokens[index]
    if (token.info.trim().split(/\s+/)[0] !== 'mermaid') {
      return original
        ? original(tokens, index, options, env, self)
        : self.renderToken(tokens, index, options)
    }
    const expression = md.utils.escapeHtml(JSON.stringify(token.content))
    return `<ClientOnly><MermaidDiagram :source="${expression}" /></ClientOnly>`
  }
}
