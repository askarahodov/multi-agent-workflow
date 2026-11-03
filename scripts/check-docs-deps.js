/** Offline guard against restoring the unpatched markdown-it-katex XSS dependency.
 *
 * This package has no fixed release (GHSA-5ff8-jcf9-fw62). VitePress already
 * provides math support, so the old markdown-it integration is unnecessary.
 */
import { readFileSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const RETIRED_PACKAGE = 'markdown-it-katex'
const DEP_FIELDS = ['dependencies', 'devDependencies', 'optionalDependencies', 'peerDependencies']

function inspectDependencies(dependencies, location, violations) {
  if (dependencies === undefined) return
  if (!dependencies || typeof dependencies !== 'object' || Array.isArray(dependencies)) {
    throw new TypeError(`${location} must be a dependency object`)
  }
  for (const [name, spec] of Object.entries(dependencies)) {
    if (name === RETIRED_PACKAGE) {
      violations.add(location)
    } else if (typeof spec === 'string' &&
               /^npm:markdown-it-katex(?:@|$)/i.test(spec)) {
      violations.add(`${location} alias ${name}`)
    }
  }
}

export function checkRetiredMathPlugin(manifest, lock) {
  if (!manifest || typeof manifest !== 'object' || Array.isArray(manifest)) {
    throw new TypeError('package.json must contain an object')
  }
  if (!lock || typeof lock !== 'object' || !lock.packages ||
      typeof lock.packages !== 'object' || Array.isArray(lock.packages)) {
    throw new TypeError('package-lock.json must contain a packages object')
  }
  const violations = new Set()
  for (const field of DEP_FIELDS) {
    inspectDependencies(manifest[field], `package.json ${field}`, violations)
  }
  for (const [name, entry] of Object.entries(lock.packages)) {
    if (!entry || typeof entry !== 'object' || Array.isArray(entry)) {
      throw new TypeError(`package-lock.json ${name} must be an object`)
    }
    if (name === `node_modules/${RETIRED_PACKAGE}` ||
        name.endsWith(`/node_modules/${RETIRED_PACKAGE}`) ||
        entry.name === RETIRED_PACKAGE) {
      violations.add(`package-lock.json ${name}`)
    }
    for (const field of DEP_FIELDS) {
      inspectDependencies(entry[field],
        `package-lock.json ${name || '(root)'} ${field}`, violations)
    }
  }
  return [...violations].sort()
}

export function main(root = resolve(dirname(fileURLToPath(import.meta.url)), '..')) {
  try {
    const manifest = JSON.parse(readFileSync(resolve(root, 'package.json'), 'utf8'))
    const lock = JSON.parse(readFileSync(resolve(root, 'package-lock.json'), 'utf8'))
    const violations = checkRetiredMathPlugin(manifest, lock)
    if (violations.length) {
      console.error(`Retired ${RETIRED_PACKAGE} dependency detected:\n${violations.join('\n')}`)
      return 1
    }
    console.log('Documentation dependency policy: PASS (no markdown-it-katex)')
    return 0
  } catch (error) {
    console.error(`Documentation dependency policy: FAIL (${error.message})`)
    return 1
  }
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  process.exitCode = main()
}
