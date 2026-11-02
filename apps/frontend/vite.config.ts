import react from '@vitejs/plugin-react';
import { configDefaults, defineConfig } from 'vitest/config';

// https://vitejs.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    // Dev integration-mode gateway (ADR-101): forward /api/v1 calls to the
    // backing services. The workflow-definition/runtime routes (workflows/*)
    // live on the orchestration server (default :8000) and the agent/model/
    // tool-policy reference routes on agent-management (default :8001).
    // Override via ORCH_UPSTREAM / AGENT_MGMT_UPSTREAM when running locally.
    proxy: {
      '/api/v1/workflows': {
        target: process.env.ORCH_UPSTREAM ?? 'http://localhost:8000',
        changeOrigin: true,
        // The run event channel (/workflows/runs/{id}/ws) is a WebSocket:
        // upgrade requests must be proxied too, or the browser's live log
        // never leaves the "Подключение…" state behind the dev server.
        ws: true,
      },
      // MVP v1 platform domain (projects, workspaces, runtime agents) is owned
      // by the orchestration server too (ADR-101 §5.3).
      '/api/v1/projects': {
        target: process.env.ORCH_UPSTREAM ?? 'http://localhost:8000',
        changeOrigin: true,
      },
      '/api/v1/workspaces': {
        target: process.env.ORCH_UPSTREAM ?? 'http://localhost:8000',
        changeOrigin: true,
      },
      // Agent management owns agent *definitions* (config): /agents/definitions.
      '/api/v1/agents/definitions': {
        target: process.env.AGENT_MGMT_UPSTREAM ?? 'http://localhost:8001',
        changeOrigin: true,
      },
      // Runtime registered agents (ADR-101 §5.3) belong to the orchestrator:
      // POST /agents/register, GET /agents.
      '/api/v1/agents/register': {
        target: process.env.ORCH_UPSTREAM ?? 'http://localhost:8000',
        changeOrigin: true,
      },
      '/api/v1/agents': {
        target: process.env.ORCH_UPSTREAM ?? 'http://localhost:8000',
        changeOrigin: true,
      },
      '/api/v1/tasks': {
        target: process.env.ORCH_UPSTREAM ?? 'http://localhost:8000',
        changeOrigin: true,
      },
      '/api/v1/admin': {
        target: process.env.ORCH_UPSTREAM ?? 'http://localhost:8000',
        changeOrigin: true,
      },
      '/api/v1/contracts': {
        target: process.env.ORCH_UPSTREAM ?? 'http://localhost:8000',
        changeOrigin: true,
      },
      '/api/v1/providers': {
        target: process.env.AGENT_MGMT_UPSTREAM ?? 'http://localhost:8001',
        changeOrigin: true,
      },
      '/api/v1/completions': {
        target: process.env.AGENT_MGMT_UPSTREAM ?? 'http://localhost:8001',
        changeOrigin: true,
      },
      '/api/v1/model-profiles': {
        target: process.env.AGENT_MGMT_UPSTREAM ?? 'http://localhost:8001',
        changeOrigin: true,
      },
      '/api/v1/tool-policies': {
        target: process.env.AGENT_MGMT_UPSTREAM ?? 'http://localhost:8001',
        changeOrigin: true,
      },
    },
  },
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./src/test/setup.ts'],
    css: false,
    // Playwright e2e specs live in ./e2e and run via `playwright test`
    // (playwright.config.ts testDir); keep them out of vitest's default
    // `**/*.spec.ts` collection so `vitest run` covers unit tests only.
    // App.tsx imports src/mvp/** in production, so its component and App
    // regression tests must run. Exclude only Playwright's own e2e suite and
    // preserve Vitest's default exclusions (node_modules, dist, etc.).
    exclude: [...configDefaults.exclude, 'e2e/**'],
  },
});