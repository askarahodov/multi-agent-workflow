import { describe, expect, it } from 'vitest';
import {
  isSensitiveDisplayField,
  redactTaskDisplayValue,
  sanitizeTaskDisplayText,
  stringifyTaskDisplayValue,
} from './taskDisplayRedaction';

describe('run/task evidence presentation boundary', () => {
  it('redacts credentials in deeply nested objects without rewriting source data', () => {
    const raw = {
      api_key: 'secret-api-key-123',
      provider: {
        apiKey: 'camel-key-123',
        headers: {
          Authorization: 'Bearer a-secret-bearer',
          'X-API-Key': 'hidden-header-key',
          Cookie: 'session=secret-cookie',
        },
        endpoint: 'https://gateway.example.test/run?stream_ticket=secret-ticket&after=42',
        token_usage: 27,
        max_total_tokens: 4096,
        extra: [{ refreshToken: 'refresh-secret' }, { result: true }],
      },
      input: 'Authorization: Bearer prose-secret; password=pass-secret',
    };
    const text = stringifyTaskDisplayValue(raw);
    for (const secret of [
      'secret-api-key-123', 'camel-key-123', 'a-secret-bearer',
      'hidden-header-key', 'secret-cookie', 'secret-ticket',
      'refresh-secret', 'prose-secret', 'pass-secret',
    ]) expect(text).not.toContain(secret);
    expect(text).toContain('[REDACTED]');
    expect(text).toContain('token_usage');
    expect(text).toContain('4096');
    expect(text).toContain('https://gateway.example.test/run?[REDACTED]');
    expect(raw.api_key).toBe('secret-api-key-123');
    expect(raw.provider.headers.Authorization).toBe('Bearer a-secret-bearer');
  });

  it('does not over-redact non-credential metrics and identifiers', () => {
    expect(isSensitiveDisplayField('token_usage')).toBe(false);
    expect(isSensitiveDisplayField('max_total_tokens')).toBe(false);
    expect(isSensitiveDisplayField('workflow_run_id')).toBe(false);
    expect(isSensitiveDisplayField('model_profile_id')).toBe(false);
    expect(isSensitiveDisplayField('sessionToken')).toBe(true);
    expect(isSensitiveDisplayField('client-secret')).toBe(true);
    expect(isSensitiveDisplayField('private_key')).toBe(true);
    const input = { attempt_count: 2, status: 'completed', node_id: 'agent_1' };
    expect(redactTaskDisplayValue(input)).toEqual(input);
  });

  it('redacts quoted JSON strings and unquoted camelCase assignments from worker errors', () => {
    const input = [
      '{"client_secret":"json-secret","apiKey":"camel-quoted-secret","token_usage":5}',
      "clientSecret='client-secret' refreshToken=refresh-secret sessionToken=session-secret",
      'apiKey="key-secret" service_credential=another-secret',
    ].join('\n');
    const safe = sanitizeTaskDisplayText(input);
    for (const secret of [
      'json-secret', 'camel-quoted-secret', 'client-secret', 'refresh-secret',
      'session-secret', 'key-secret', 'another-secret',
    ]) expect(safe).not.toContain(secret);
    expect(safe).toContain('token_usage');
    const copied = '{\\"clientSecret\\":\\"escaped-value\\"}';
    expect(sanitizeTaskDisplayText(copied)).not.toContain('escaped-value');
  });

  it('redacts credentials inside non-sensitive serialized wrappers and escaped quote values', () => {
    const raw = [
      '{"message":"clientSecret=wrapped-secret"}',
      'payload={"clientSecret":"nested-secret","token_usage":5}',
      JSON.stringify({clientSecret: 'prefix"suffix-secret', token_usage: 8}),
      String.raw`{\"clientSecret\":\"prefix\\\"escaped-suffix-secret\"}`,
      'description=benign-secret-looking-label',
    ].join('\n');
    const safe = sanitizeTaskDisplayText(raw);
    for (const credential of [
      'wrapped-secret', 'nested-secret', 'prefix', 'suffix-secret', 'escaped-suffix-secret',
    ]) expect(safe).not.toContain(credential);
    expect(safe).toContain('token_usage');
    expect(safe).toContain('description=benign-secret-looking-label');
    expect(sanitizeTaskDisplayText('Authorization: [REDACTED]')).toBe('Authorization: [REDACTED]');
  });

  it('hides full Cookie and Basic Authorization headers and URL userinfo', () => {
    const input = [
      'Cookie: session=cookie-first; auth=cookie-second',
      'Authorization: Basic dXNlcjpwYXNzd29yZA==',
      'https://alice:repo-password@git.example.test/repo.git?after=1',
      'https://bob:plain-password@git.example.test/repo.git',
      'wss://api-user:ws-password@stream.example.test/socket?stream_ticket=ticket-secret',
    ].join('\n');
    const safe = sanitizeTaskDisplayText(input);
    for (const secret of [
      'cookie-first', 'cookie-second', 'dXNlcjpwYXNzd29yZA==',
      'repo-password', 'plain-password', 'ws-password', 'ticket-secret',
    ]) expect(safe).not.toContain(secret);
    expect(safe).toContain('Cookie: [REDACTED]');
    expect(safe).toContain('Authorization: [REDACTED]');
    expect(safe).toContain('https://[REDACTED]@git.example.test/repo.git');
  });

  it('redacts full Digest and quoted cookie headers without leaving response parameters', () => {
    const input = [
      'Authorization: Digest username="alice", realm="service", nonce="nonce", response="digest-response-secret"',
      'Set-Cookie: sid="cookie-secret"; Expires="Friday"',
      'Proxy-Authorization: Digest username="operator", response="proxy-secret"',
      'next-line=visible',
    ].join('\n');
    const safe = sanitizeTaskDisplayText(input);
    for (const secret of ['digest-response-secret', 'cookie-secret', 'proxy-secret']) {
      expect(safe).not.toContain(secret);
    }
    expect(safe).toContain('Authorization: [REDACTED]');
    expect(safe).toContain('Set-Cookie: [REDACTED]');
    expect(safe).toContain('Proxy-Authorization: [REDACTED]');
    expect(safe).toContain('next-line=visible');
  });

  it('limits untrusted strings, lists and nesting before rendering', () => {
    const huge = 'safe' + 'x'.repeat(100_000);
    const cut = sanitizeTaskDisplayText(huge);
    expect(cut.length).toBeLessThan(33_000);
    expect(cut).toContain('[TRUNCATED]');
    const list = Array.from({ length: 180 }, (_, i) => i);
    const rendered = redactTaskDisplayValue(list) as unknown[];
    expect(rendered).toHaveLength(151);
    expect(rendered[150]).toBe('[TRUNCATED]');
    let nested: unknown = 'end';
    for (let i = 0; i < 20; i += 1) nested = { nested };
    expect(stringifyTaskDisplayValue(nested)).toContain('[TRUNCATED]');
    // Traversal must also be bounded across many shallow branches.
    const wide = Array.from({ length: 30 }, () => Array(70).fill('safe'));
    expect(stringifyTaskDisplayValue(wide)).toContain('[TRUNCATED]');
    // Dynamic JSON keys must not manipulate the prototype of the display copy.
    const hostileKey = JSON.parse('{"__proto__":{"password":"hidden"},"safe":true}') as Record<string, unknown>;
    const copy = redactTaskDisplayValue(hostileKey) as Record<string, unknown>;
    expect(Object.getPrototypeOf(copy)).toBeNull();
    expect(copy.safe).toBe(true);
  });

  it('sanitizes worker error strings, private key names and URL-bearing paths', () => {
    expect(sanitizeTaskDisplayText('client_secret=secret-one')).not.toContain('secret-one');
    expect(sanitizeTaskDisplayText('Cookie: session=private-cookie')).not.toContain('private-cookie');
    expect(sanitizeTaskDisplayText('https://repo.test/git?token=private-query')).not.toContain('private-query');
    expect(stringifyTaskDisplayValue({
      filePath: 'https://service.test/path?api_key=worker-key',
      private_key: 'my-sensitive-key',
    })).not.toMatch(/worker-key|my-sensitive-key/);
  });
});
