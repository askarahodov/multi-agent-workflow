import { defineConfig, devices } from '@playwright/test';
import { fileURLToPath } from 'node:url';

const root = fileURLToPath(new URL('../..', import.meta.url));

/** Only the built documentation preview; never contact a real LLM/provider. */
export default defineConfig({
  testDir: './e2e',
  testMatch: /docs-mermaid\.spec\.ts/,
  timeout: 60_000,
  expect: { timeout: 35_000 },
  retries: 1,
  workers: 1,
  reporter: [['list'], ['html', { open: 'never' }]],
  use: {
    ...devices['Desktop Chrome'],
    baseURL: 'http://127.0.0.1:4174',
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
  },
  webServer: {
    command: 'npm run docs:preview -- --host 127.0.0.1 --port 4174 --strictPort',
    cwd: root,
    url: 'http://127.0.0.1:4174',
    timeout: 120_000,
    reuseExistingServer: false,
  },
});
