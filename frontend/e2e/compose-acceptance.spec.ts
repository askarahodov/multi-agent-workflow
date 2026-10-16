import { test, expect } from '@playwright/test';

// No page.route(), fixtures, in-memory mock adapter or paid provider requests.
// All API requests flow through the running Vite proxy to real Compose services.

const definition = {
  schema_version: '1.0',
  metadata: { name: 'Browser HTTP flow', version: 1, created_at: '2026-10-16T00:00:00Z' },
  nodes: [
    { id: 'n_start', type: 'start', label: 'Start', position: { x: 0, y: 0 }, config: {} },
    { id: 'n_end', type: 'end', label: 'End', position: { x: 100, y: 0 }, config: {} },
  ],
  edges: [],
};

test('real MVP UI creates/selects project, workflow HTTP revision, run/task and live log', async ({ page }) => {
  const tag = `compose-ui-${Date.now()}`;
  const projectName = `project-${tag}`;
  const runName = `run-${tag}`;

  const failedRequests: string[] = [];
  const pageErrors: string[] = [];
  const sentRequests: string[] = [];
  page.on('requestfailed', r => failedRequests.push(`${r.method()} ${r.url().split('?')[0]}`));
  page.on('pageerror', e => pageErrors.push(e.message.slice(0, 200)));
  page.on('request', r => {
    if (r.method() === 'POST') sentRequests.push(r.url().split('?')[0]);
  });
  await page.goto('/');
  await expect(page.getByTestId('nav-project')).toBeVisible();
  await page.getByTestId('project-name-input').fill(projectName);
  const projectResponse = page.waitForResponse(r =>
    r.url().includes('/api/v1/projects') && r.request().method() === 'POST',
  { timeout: 12000 });
  await page.getByTestId('project-create-button').click();
  const createdResponse = await projectResponse.catch(async () => {
    const formText = (await page.locator('main').innerText()).slice(0, 1600);
    throw new Error(`Project POST missing; outgoing POSTs=${JSON.stringify(sentRequests)}; ` +
      `failed=${JSON.stringify(failedRequests)}; exceptions=${JSON.stringify(pageErrors)}; ` +
      `visible UI=${formText}`);
  });
  expect(createdResponse.status()).toBe(201);
  const project = await createdResponse.json();
  expect(project.name).toBe(projectName);
  await expect(page.getByText(projectName, { exact: true })).toBeVisible();

  // Browser-origin HTTP exercises Vite's /api/v1/workflows proxy, not a unit mock.
  const definitionResponse = await page.request.post('/api/v1/workflows/definitions', {
    data: { name: `definition-${tag}`, definition },
  });
  expect(definitionResponse.status()).toBe(201);
  const wf = await definitionResponse.json();
  const versionResponse = await page.request.post(
    `/api/v1/workflows/definitions/${wf.id}/versions`,
    { data: { definition_snapshot: definition, changelog: 'actual frontend HTTP smoke' } },
  );
  expect(versionResponse.status()).toBe(201);
  expect((await versionResponse.json()).version_number).toBe(1);

  await page.getByTestId('nav-runs').click();
  await page.getByTestId('run-name-input').fill(runName);
  await page.getByTestId('task-title-input-0').fill('smoke-task');
  const runResponse = page.waitForResponse(r =>
    r.url().includes('/api/v1/workflows/runs') && r.request().method() === 'POST');
  await page.getByTestId('run-create-button').click();
  const launched = await runResponse;
  expect(launched.status()).toBe(201);
  const run = await launched.json();
  expect(run.project_id).toBe(project.id);
  await expect(page.getByText(runName, { exact: true }).first()).toBeVisible();

  const list = await page.request.get(`/api/v1/workflows/runs/${run.id}/tasks`);
  expect(list.ok()).toBeTruthy();
  const tasks = (await list.json()).items;
  expect(tasks).toHaveLength(1);
  expect(tasks[0].title).toBe('smoke-task');
  await page.getByTestId(`run-task-${tasks[0].id}`).click();
  await expect(page.getByTestId('nav-task')).toBeVisible();

  await page.getByTestId('nav-agent-log').click();
  await expect(page.getByTestId('log-run-select')).toHaveValue(run.id);
  await expect(page.getByTestId('agent-log-feed')).toContainText('running');
  // Prove agent log uses real HTTP rather than an imaginary LLM event stream.
  const snapshot = await page.request.get(`/api/v1/workflows/runs/${run.id}`);
  expect((await snapshot.json()).status).toBe('running');
});

test('settings persist a synthetic provider and model; never trigger a paid completion', async ({ page }) => {
  const tag = Date.now();
  const name = `openrouter-acceptance-${tag}`;
  const fakeKey = `test-invalid-key-${tag}`;
  const completions: string[] = [];
  page.on('request', request => {
    if (request.url().includes('/api/v1/completions')) completions.push(request.url());
  });
  await page.goto('/');
  await page.getByTestId('nav-settings').click();
  await expect(page.getByRole('heading', { name: 'OpenRouter — подключение' })).toBeVisible();
  await page.getByLabel('Имя подключения').fill(name);
  await page.getByLabel('API key', { exact: true }).fill(fakeKey);
  await page.getByRole('button', { name: 'Добавить подключение' }).click();
  await expect(page.getByRole('status')).toContainText('Подключение сохранено');
  const providersResponse = await page.request.get('/api/v1/providers');
  expect(providersResponse.ok()).toBeTruthy();
  const text = await providersResponse.text();
  expect(text).not.toContain(fakeKey);
  expect(text).not.toContain('auth_config');
  const provider = JSON.parse(text).items.find((item: { name: string }) => item.name === name);
  expect(provider).toBeTruthy();
  await page.getByLabel('Подключение', { exact: true }).selectOption(provider.id);
  await page.getByLabel('Model ID').fill('offline/test-model');
  await page.getByRole('button', { name: 'Сохранить модель' }).click();
  await expect(page.getByRole('status')).toContainText('Профиль модели сохранён');
  const models = await page.request.get('/api/v1/model-profiles');
  expect((await models.json()).items.some(
    (item: { provider_id: string; model_id: string }) =>
      item.provider_id === provider.id && item.model_id === 'offline/test-model',
  )).toBeTruthy();
  expect(completions).toHaveLength(0);
  // No screenshots on success and no actual OpenRouter credential is used.
});
