import { expect, test } from '@playwright/test';

const ADR = '/developer/architecture-decisions/ADR-010-multi-agent-orchestration';

/** The docs renderer previously passed build checks but could fail in-browser.
 * This loads real Mermaid 12 in Chromium from the VitePress preview build.
 */
test('actual architecture diagrams hydrate as SVG, not code/fallback', async ({ page }) => {
  await page.goto(ADR, { waitUntil: 'domcontentloaded' });

  const diagrams = page.locator('.maw-mermaid');
  await expect(diagrams.first()).toBeAttached();
  await expect.poll(() => page.locator('.maw-mermaid__svg svg').count(),
    { timeout: 45_000 }).toBeGreaterThanOrEqual(2);

  await expect(diagrams.first().locator('.maw-mermaid__svg svg')).toBeVisible();
  await expect(diagrams.nth(1).locator('.maw-mermaid__svg svg')).toBeAttached();
  await expect(diagrams.first().locator('pre')).toHaveCount(0);
  await expect(page.locator('.maw-mermaid [role="alert"]')).toHaveCount(0);
  await expect(page.locator('.maw-mermaid svg script')).toHaveCount(0);
});

test('Mermaid diagrams survive a full navigation/reload without stale render IDs', async ({ page }) => {
  await page.goto(ADR, { waitUntil: 'domcontentloaded' });
  await expect(page.locator('.maw-mermaid__svg svg').first()).toBeAttached();

  await page.reload({ waitUntil: 'domcontentloaded' });
  await expect.poll(() => page.locator('.maw-mermaid__svg svg').count(),
    { timeout: 45_000 }).toBeGreaterThanOrEqual(2);
  await expect(page.locator('.maw-mermaid [role="alert"]')).toHaveCount(0);

  // Different Mermaid fences must not share DOM IDs after dynamic imports.
  const svgIds = await page.locator('.maw-mermaid__svg svg').evaluateAll(svgs =>
    svgs.map(svg => svg.id).filter(Boolean));
  expect(svgIds.length).toBeGreaterThanOrEqual(2);
  expect(new Set(svgIds).size).toBe(svgIds.length);
});
