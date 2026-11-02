// frontend/e2e/simple-test.spec.ts
import { test, expect } from '@playwright/test';

test('simple navigation test', async ({ page }) => {
  await page.goto('https://example.com');
  await expect(page).toHaveURL('https://example.com/');
});