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

test('canonical ADR and compatibility URL expose the same document', async ({page})=>{
  await page.goto(ADR,{waitUntil:'domcontentloaded'});
  const old=await page.locator('.vp-doc h1').first().innerText();
  await page.goto('/adr/ADR-010-multi-agent-orchestration',{waitUntil:'domcontentloaded'});
  await expect(page.locator('.vp-doc h1').first()).toHaveText(old);
  await expect(page.locator('.maw-mermaid__svg svg').first()).toBeAttached();
});
test('requirements and contracts page exposes real issue references', async ({page})=>{
  await page.goto('/governance/requirements-and-contracts',{waitUntil:'domcontentloaded'});
  await expect(page.locator('.vp-doc h1')).toHaveText('Требования и контракты');
  await expect(page.locator('.vp-doc a[href$="/issues/336"]')).toBeVisible();
  await expect(page.locator('.vp-doc a[href$="/issues/337"]')).toBeVisible();
});


test('requirements portal navigates to each canonical page and retains draft status', async ({ page }) => {
  const targets = [
    { link: 'PRD', route: /\/product\/PRD(?:\.html)?$/, title: 'PRD: Multi-Agent Workflow — корпоративная фабрика разработки' },
    { link: 'Реестр контрактов', route: /\/architecture\/contract-registry(?:\.html)?$/, title: 'Реестр контрактов: baseline и план покрытия' },
    { link: 'Трассируемость', route: /\/product\/traceability(?:\.html)?$/, title: 'Трассируемость требований' },
  ];
  for (const target of targets) {
    await page.goto('/governance/requirements-and-contracts', { waitUntil: 'domcontentloaded' });
    await page.locator('.vp-doc').getByRole('link', { name: target.link, exact: true }).click();
    await expect(page).toHaveURL(target.route);
    await expect(page.locator('.vp-doc h1')).toHaveText(target.title);
    await expect(page.locator('.vp-doc').getByText(/проект для согласования|проект для review/).first()).toBeVisible();
  }
});

test('Russian documentation headings expose distinct meaningful anchors', async ({ page }) => {
  await page.goto('/governance/documentation-policy', { waitUntil: 'domcontentloaded' });
  const headings = page.locator('.vp-doc h2');
  const ids = await headings.evaluateAll(nodes => nodes.map(node => node.id));
  expect(ids.length).toBeGreaterThanOrEqual(5);
  expect(new Set(ids).size).toBe(ids.length);
  const russian = ids.filter(id => /[А-Яа-яЁё]/.test(decodeURIComponent(id)));
  expect(russian.length).toBeGreaterThanOrEqual(4);
  const heading = headings.filter({ hasText: 'Навигация и проверка портала' });
  const id = await heading.getAttribute('id');
  expect(id).toBeTruthy();
  await page.locator('.vp-doc h2').filter({ hasText: 'Навигация и проверка портала' }).locator('a.header-anchor').click({ force: true });
  await expect.poll(() => decodeURIComponent(new URL(page.url()).hash.slice(1))).toBe(decodeURIComponent(id!));
});
