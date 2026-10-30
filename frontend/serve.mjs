/**
 * Production static server for the built frontend bundle.
 *
 * Used by `frontend/Dockerfile.release` as the container entrypoint: it serves
 * the Vite `dist/` output with an SPA fallback (unknown paths return
 * `index.html`) and correct content types. Node stdlib only — no dev server and
 * no runtime dependencies, so the release image stays small and can run as a
 * non-root user.
 *
 * The application talks to the backend over the same origin (`/api/v1`), which a
 * reverse proxy in front of this container is expected to route; this server
 * only serves static assets.
 */
import { createReadStream } from 'node:fs';
import { stat } from 'node:fs/promises';
import { createServer } from 'node:http';
import { extname, join, normalize, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = resolve(fileURLToPath(new URL('.', import.meta.url)), 'dist');
const PORT = Number(process.env.PORT ?? 5173);
const HOST = process.env.HOST ?? '0.0.0.0';

const MIME = {
  '.html': 'text/html; charset=utf-8',
  '.js': 'text/javascript; charset=utf-8',
  '.mjs': 'text/javascript; charset=utf-8',
  '.css': 'text/css; charset=utf-8',
  '.json': 'application/json; charset=utf-8',
  '.map': 'application/json; charset=utf-8',
  '.svg': 'image/svg+xml',
  '.png': 'image/png',
  '.jpg': 'image/jpeg',
  '.jpeg': 'image/jpeg',
  '.gif': 'image/gif',
  '.webp': 'image/webp',
  '.ico': 'image/x-icon',
  '.woff': 'font/woff',
  '.woff2': 'font/woff2',
  '.ttf': 'font/ttf',
  '.txt': 'text/plain; charset=utf-8',
};

/** Resolve a request path to a file inside ROOT, or null when none matches. */
function resolveInsideRoot(urlPath) {
  let decoded;
  try {
    decoded = decodeURIComponent(urlPath.split('?')[0]);
  } catch {
    return null;
  }
  // `normalize` collapses `..` segments; the prefix check rejects any path that
  // still escapes the served root (defence in depth against traversal).
  const candidate = join(ROOT, normalize(decoded));
  if (candidate !== ROOT && !candidate.startsWith(ROOT + '/')) return null;
  return candidate;
}

async function findFile(urlPath) {
  const candidate = resolveInsideRoot(urlPath);
  if (!candidate) return null;
  try {
    const info = await stat(candidate);
    if (info.isFile()) return candidate;
    if (info.isDirectory()) {
      const index = join(candidate, 'index.html');
      if ((await stat(index)).isFile()) return index;
    }
  } catch {
    /* not a file — fall through to the SPA fallback */
  }
  return null;
}

const server = createServer(async (req, res) => {
  if (req.method !== 'GET' && req.method !== 'HEAD') {
    res.writeHead(405, { Allow: 'GET, HEAD' });
    res.end();
    return;
  }

  // SPA fallback: unknown routes serve index.html so client-side routing works.
  const file = (await findFile(req.url ?? '/')) ?? join(ROOT, 'index.html');
  const ext = extname(file).toLowerCase();

  res.writeHead(200, {
    'Content-Type': MIME[ext] ?? 'application/octet-stream',
    // Vite fingerprints files under /assets; index.html must never be cached.
    'Cache-Control': ext === '.html' ? 'no-cache' : 'public, max-age=3600',
  });

  if (req.method === 'HEAD') {
    res.end();
    return;
  }
  createReadStream(file)
    .on('error', () => res.destroy())
    .pipe(res);
});

server.listen(PORT, HOST, () => {
  console.log(`frontend static server listening on http://${HOST}:${PORT} (root: ${ROOT})`);
});
