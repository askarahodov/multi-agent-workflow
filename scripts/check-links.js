#!/usr/bin/env node
// Simple link checker for VitePress build output
// Checks for broken internal links in generated HTML files

import fs from 'fs'
import path from 'path'
import { fileURLToPath } from 'url'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const distDir = path.join(__dirname, '..', 'docs', '.vitepress', 'dist')

function findHtmlFiles(dir) {
  const files = []
  function walk(d) {
    for (const entry of fs.readdirSync(d, { withFileTypes: true })) {
      const fullPath = path.join(d, entry.name)
      if (entry.isDirectory()) {
        walk(fullPath)
      } else if (entry.name.endsWith('.html')) {
        files.push(fullPath)
      }
    }
  }
  walk(dir)
  return files
}

function extractLinks(html, basePath) {
  const links = []
  const regex = /href=["']([^"']+)["']/g
  let match
  while ((match = regex.exec(html)) !== null) {
    const href = match[1]
    // Skip external links, anchors, mailto, tel, javascript
    if (
      href.startsWith('http://') ||
      href.startsWith('https://') ||
      href.startsWith('mailto:') ||
      href.startsWith('tel:') ||
      href.startsWith('javascript:') ||
      href.startsWith('#')
    ) {
      continue
    }
    links.push({ href, basePath })
  }
  return links
}

export function resolveLink(href, basePath, root = distDir) {
  // Decode URL pathname and discard fragment/query without treating assets as HTML.
  const pathname = href.split(/[?#]/, 1)[0]
  if (!pathname) return basePath
  let decoded
  try {
    decoded = decodeURIComponent(pathname)
  } catch {
    return null
  }
  const resolved = decoded.startsWith('/')
    ? path.resolve(root, '.' + decoded)
    : path.resolve(path.dirname(basePath), decoded)
  // Do not allow links escaping the generated site root.
  const relative = path.relative(root, resolved)
  if (relative.startsWith('..' + path.sep) || relative === '..' || path.isAbsolute(relative)) {
    return null
  }
  // VitePress cleanUrls emits /guide/page.html (not /guide/page/index.html).
  // For directory links, keep /guide/ -> /guide/index.html.
  if (decoded.endsWith('/') || (fs.existsSync(resolved) && fs.statSync(resolved).isDirectory())) {
    return path.join(resolved, 'index.html')
  }
  if (path.extname(resolved)) return resolved
  const html = resolved + '.html'
  if (fs.existsSync(html)) return html
  return path.join(resolved, 'index.html')
}

function main() {
  console.log('Checking internal links in', distDir)
  
  const htmlFiles = findHtmlFiles(distDir)
  console.log(`Found ${htmlFiles.length} HTML files`)
  
  let brokenLinks = 0
  let checkedLinks = 0
  
  for (const file of htmlFiles) {
    const html = fs.readFileSync(file, 'utf-8')
    const links = extractLinks(html, file)
    
    for (const link of links) {
      checkedLinks++
      const resolvedPath = resolveLink(link.href, link.basePath)
      const relativePath = resolvedPath ? path.relative(distDir, resolvedPath) : '(invalid/outside site root)'
      
      if (!resolvedPath || !fs.existsSync(resolvedPath)) {
        console.error(`❌ BROKEN: ${path.relative(distDir, link.basePath)} -> ${link.href} (resolved to ${relativePath})`)
        brokenLinks++
      }
    }
  }
  
  console.log(`\nChecked ${checkedLinks} internal links`)
  console.log(`Broken links: ${brokenLinks}`)
  
  if (brokenLinks > 0) {
    process.exit(1)
  } else {
    console.log('✅ All internal links OK')
  }
}

main()