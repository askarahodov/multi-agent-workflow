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

function resolveLink(href, basePath) {
  // Remove hash fragment
  const [pathname] = href.split('#')
  if (!pathname) return basePath // Just anchor link

  // Resolve relative to basePath directory
  const baseDir = path.dirname(basePath)
  const resolved = path.resolve(baseDir, pathname)
  
  // Check if it's a directory (should have index.html)
  let checkPath = resolved
  if (!path.extname(resolved)) {
    checkPath = path.join(resolved, 'index.html')
  } else if (!checkPath.endsWith('.html')) {
    checkPath = resolved + '.html'
  }
  
  return checkPath
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
      const relativePath = path.relative(distDir, resolvedPath)
      
      if (!fs.existsSync(resolvedPath)) {
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