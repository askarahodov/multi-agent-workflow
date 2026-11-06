import { defineConfig, devices } from '@playwright/test';

/**
 * Portable, offline Chromium smoke tests for the built frontend.
 * The real-API browser acceptance is separately run by
 * compose.playwright.config.ts against six live Compose services.
 */
export default defineConfig({
  testDir: './e2e',
  testMatch: /(?:design-system|live-run)\.spec\.ts/,
  fullyParallel: false,
  forbidOnly: Boolean(process.env.CI),
  retries: process.env.CI ? 1 : 0,
  workers: process.env.CI ? 1 : undefined,
  reporter: [['list']],
  timeout: 30_000,
  expect: { timeout: 10_000 },
  use: {
    ...devices['Desktop Chrome'],
    baseURL: 'http://127.0.0.1:4173',
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
  },
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'] } }],
  webServer: {
    command: 'npm run preview -- --host 127.0.0.1 --port 4173 --strictPort',
    url: 'http://127.0.0.1:4173/',
    timeout: 120_000,
    reuseExistingServer: !process.env.CI,
  },
});
