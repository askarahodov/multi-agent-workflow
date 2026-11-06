/**
 * Defense-in-depth redaction for user-visible task/attempt evidence.
 *
 * The HTTP API still owns authorization and transport secrecy. A task's
 * input/output, error and Git path can come from an untrusted worker. Never
 * stringify those raw values into the end-user UI. This is NOT an evidence
 * signature or a backend authorization boundary.
 */
import { sanitizeRunLogText } from './runStream';

const REDACTED = '[REDACTED]';
const TRUNCATED = '[TRUNCATED]';
const MAX_DEPTH = 12;
const MAX_ENTRIES = 150;
const MAX_VISITED_NODES = 1000;
const MAX_TEXT = 32768;

/** Common credential fields, including camelCase, headers and private keys. */
export function isSensitiveDisplayField(key: string): boolean {
  const name = key.replace(/[^a-zA-Z0-9]/g, '').toLowerCase();
  return name === 'auth' ||
    name === 'authorization' ||
    name === 'cookie' ||
    name === 'setcookie' ||
    name === 'password' ||
    name === 'passphrase' ||
    name === 'secret' ||
    name === 'credential' ||
    name === 'credentials' ||
    name === 'apikey' ||
    name === 'xapikey' ||
    name === 'clientsecret' ||
    name === 'privatekey' ||
    name === 'accesskey' ||
    name === 'sessionkey' ||
    name.endsWith('token') ||
    name.endsWith('secret') ||
    name.endsWith('password') ||
    name.endsWith('credential') ||
    name.endsWith('privatekey') ||
    name.endsWith('apikey');
}

export function sanitizeTaskDisplayText(value: string): string {
  const bounded = value.length > MAX_TEXT ? value.slice(0, MAX_TEXT) + TRUNCATED : value;
  // A URL query may be stripped by the stream sanitizer, but credentials in
  // URL userinfo survive that step unless they are removed separately.
  const withoutUserinfo = bounded.replace(
    /\b((?:https?|wss?):\/\/)[^\s/?#]+@/gi, '$1[REDACTED]@',
  );
  // Header syntax is distinct from field assignments. Strip *all* header
  // values to the end of the line/quoted value: Basic auth and multiple
  // semicolon-separated cookies must not leave a second credential visible.
  const withoutHeaders = withoutUserinfo
    .replace(/\b(Authorization|Proxy-Authorization|X-API-Key)\s*[:=]\s*[^\r\n"'<>]+/gi, '$1: [REDACTED]')
    .replace(/\b(Cookie|Set-Cookie)\s*[:=]\s*[^\r\n"'<>]+/gi, '$1: [REDACTED]');
  // Locate credential field names independently of enclosing assignments:
  // message="clientSecret=..." and payload={"clientSecret":"..."} must
  // not consume the outer wrapper and hide the inner sensitive key.
  // Do not globally unescape JSON quotes: a value may itself contain \".
  const safe = sanitizeRunLogText(withoutHeaders);
  const fields = /(?:\\?["'])?([a-z][a-z0-9_-]{0,64})(?:\\?["'])?\s*[:=]\s*/gi;
  let cursor = 0;
  let output = '';
  for (const match of safe.matchAll(fields)) {
    const start = match.index;
    if (start < cursor || !isSensitiveDisplayField(match[1])) continue;
    const valueStart = start + match[0].length;
    if (valueStart >= safe.length) continue;
    if (safe.startsWith(REDACTED, valueStart)) continue;
    let end = valueStart;
    const quote = safe[end];
    if (quote === '"' || quote === "'") {
      // A normal JSON/string literal: escaped internal quotes are data,
      // never mistaken for the terminating quote.
      end += 1;
      while (end < safe.length) {
        if (safe[end] === '\\') { end += 2; continue; }
        if (safe[end++] === quote) break;
      }
    } else if (quote === '\\' && (safe[end + 1] === '"' || safe[end + 1] === "'")) {
      // Copied escaped JSON can contain double/triple backslash quote
      // sequences. Without parsing the outer serialization reliably,
      // fail closed on the *whole line* instead of leaking a suffix.
      while (end < safe.length && safe[end] !== '\n' && safe[end] !== '\r') end++;
    } else if (quote === '{' || quote === '[') {
      // Unknown nested literal: conservative line-level redaction.
      while (end < safe.length && safe[end] !== '\n' && safe[end] !== '\r') end++;
    } else {
      while (end < safe.length && !/[\s,;}\]]/.test(safe[end])) end++;
    }
    output += safe.slice(cursor, start) + match[0] + REDACTED;
    cursor = end;
  }
  return output + safe.slice(cursor);
}

/** Immutable, bounded copy; the original API response is never rewritten. */
export function redactTaskDisplayValue(value: unknown): unknown {
  // A per-level fan-out cap is insufficient for a deeply nested JSON tree.
  // Count all traversed values to bound worst-case work across branches.
  let remaining = MAX_VISITED_NODES;
  function visit(current: unknown, depth: number): unknown {
    if (remaining-- <= 0) return TRUNCATED;
    if (typeof current === 'string') return sanitizeTaskDisplayText(current);
    if (current === null || typeof current === 'number' || typeof current === 'boolean') return current;
    if (depth >= MAX_DEPTH) return TRUNCATED;
    if (Array.isArray(current)) {
      const result = current.slice(0, MAX_ENTRIES).map(item => visit(item, depth + 1));
      if (current.length > MAX_ENTRIES) result.push(TRUNCATED);
      return result;
    }
    if (typeof current === 'object') {
      const result: Record<string, unknown> = Object.create(null) as Record<string, unknown>;
      for (const [key, entry] of Object.entries(current).slice(0, MAX_ENTRIES)) {
        const safeKey = sanitizeTaskDisplayText(key).slice(0, 256);
        result[safeKey] = isSensitiveDisplayField(key) ? REDACTED : visit(entry, depth + 1);
      }
      if (Object.keys(current).length > MAX_ENTRIES) result['…'] = TRUNCATED;
      return result;
    }
    return TRUNCATED;
  }
  return visit(value, 0);
}

/** Structured JSON rendering must use this, never JSON.stringify(raw payload). */
export function stringifyTaskDisplayValue(value: unknown): string {
  return JSON.stringify(redactTaskDisplayValue(value), null, 2);
}
