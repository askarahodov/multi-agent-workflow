// frontend/e2e/design-system.spec.ts
//
// E2E smoke tests for the design system + core layouts (ADR-110).
// Runs against the built app served by `vite preview` (playwright.config.ts
// webServer). The sections render their error/empty states without a live
// backend, so the smoke test asserts the shell, navigation, accessibility
// wiring and responsive behaviour rather than backend data.

import { test, expect, type Page } from '@playwright/test';

const BASE = 'http://localhost:4173';

async function gotoSecure(page: Page, path = '/'): Promise<void> {
  await page.goto(`${BASE}${path}`);
  await expect(page.getByRole('navigation', { name: 'Основная навигация' })).toBeVisible();
}

test.describe('application shell', () => {
  test('renders the shell, skip link and default project layout', async ({ page }) => {
    await gotoSecure(page);
    await expect(page.getByRole('heading', { level: 1, name: 'Проект' })).toBeVisible();
    await expect(page.getByRole('link', { name: 'Перейти к содержимому' })).toBeVisible();
    await expect(page.getByRole('main')).toBeVisible();
  });

  test('navigates between the core layouts', async ({ page }) => {
    await gotoSecure(page);
    await expect(page.getByRole('heading', { level: 1, name: 'Проект' })).toBeVisible();
    await expect(page.getByRole('heading', { level: 2, name: 'Проект' })).toBeVisible();

    await page.getByTestId('nav-board').click();
    await expect(page.getByRole('heading', { level: 1, name: 'Kanban-доска' })).toBeVisible();
    await expect(page.getByRole('heading', { level: 2, name: 'Kanban-доска' })).toBeVisible();

    await page.getByTestId('nav-agent-log').click();
    await expect(page.getByRole('heading', { level: 1, name: 'Живой журнал' })).toBeVisible();
    await expect(page.getByRole('heading', { level: 2, name: 'Живой журнал агента' })).toBeVisible();

    await page.getByTestId('nav-settings').click();
    await expect(page.getByRole('heading', { level: 1, name: 'Настройки' })).toBeVisible();
    await expect(page.getByRole('heading', { level: 2, name: 'Настройки проекта' })).toBeVisible();
  });

  test('the skip link is the first keyboard stop and targets main content', async ({ page }) => {
    await gotoSecure(page);
    await page.keyboard.press('Tab');
    const focused = await page.evaluate(() => document.activeElement?.textContent?.trim());
    expect(focused).toBe('Перейти к содержимому');
    await expect(page.getByRole('link', { name: 'Перейти к содержимому' })).toHaveAttribute('href', '#main-content');
  });
});

test.describe('accessibility', () => {
  test('every icon-only button carries an accessible name', async ({ page }) => {
    await gotoSecure(page);
    const buttons = page.locator('button');
    const count = await buttons.count();
    for (let i = 0; i < count; i += 1) {
      const button = buttons.nth(i);
      const text = (await button.textContent())?.trim() ?? '';
      if (text.length > 0) continue; // has a visible label
      const name = await button.getAttribute('aria-label');
      expect(name, `icon-only button #${i} must have aria-label`).toBeTruthy();
    }
  });

  test('the live agent feed is a polite live region', async ({ page }) => {
    await gotoSecure(page);
    await page.getByTestId('nav-agent-log').click();
    const liveRegion = page.getByTestId('shell-live-region');
    await expect(liveRegion).toHaveAttribute('aria-live', 'polite');
    // Notifications region is always mounted.
    await expect(page.getByRole('region', { name: 'Уведомления' })).toHaveCount(1);
  });
});

test.describe('responsive breakpoints', () => {
  test('sidebar is a drawer below md and a rail at desktop width', async ({ page }) => {
    await gotoSecure(page);

    // Narrow (mobile): the menu button is shown, desktop nav is off-canvas.
    await page.setViewportSize({ width: 375, height: 780 });
    await expect(page.getByRole('button', { name: 'Открыть меню' })).toBeVisible();

    // Wide (desktop): the persistent sidebar navigation is visible.
    await page.setViewportSize({ width: 1280, height: 800 });
    await expect(page.getByTestId('nav-board')).toBeVisible();
  });
});
