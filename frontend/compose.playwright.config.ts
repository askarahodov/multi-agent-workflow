import { defineConfig, devices } from '@playwright/test';

/** Explicit Docker Compose acceptance, NOT the legacy mocked editor suite. */
export default defineConfig({
  testDir: './e2e',
  testMatch: /compose-acceptance\.spec\.ts/,
  fullyParallel: false,
  workers: 1,
  retries: 0,
  reporter: [['list']],
  timeout: 60_000,
  expect: { timeout: 15_000 },
  use: {
    ...devices['Desktop Chrome'],
    baseURL: process.env.MAW_ACCEPTANCE_BASE_URL ?? 'http://127.0.0.1:5173',
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
  },
  // Intentionally no webServer: the browser must hit the ALREADY RUNNING
  // real docker-compose frontend, never an in-process mock or Vite preview.
});
