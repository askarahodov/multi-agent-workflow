import { test, expect, type APIRequestContext, type Page } from '@playwright/test';

// Real Chromium -> Compose frontend -> Vite proxy -> persisted orchestration +
// agent-management APIs. No page.route(), browser mocks or paid completions.
async function create<T>(request: APIRequestContext, path: string, data: unknown): Promise<T> {
  const response = await request.post('/api/v1' + path, { data });
  expect(response.status(), path + ': ' + (await response.text()).slice(0, 900)).toBe(201);
  return response.json() as Promise<T>;
}

type Entity = { id: string; name: string };
const acceptConfirmation = (page: Page) =>
  page.on('dialog', async dialog => { await dialog.accept(); });

test('Chromium creates project → configured graph → saved version → preflight → run/task/log → reload', async ({page}) => {
  test.setTimeout(120_000);
  const tag = 'graph-browser-' + Date.now();
  const workflowName = 'Compose ' + tag;
  const outgoingCompletions: string[] = [];
  page.on('request', r => {
    if (r.url().includes('/completions')) outgoingCompletions.push(r.url());
  });
  acceptConfirmation(page);

  await page.goto('/');
  await expect(page.getByTestId('nav-project')).toBeVisible();
  await page.getByTestId('project-name-input').fill(tag);
  const projectPost = page.waitForResponse(r =>
    r.url().includes('/api/v1/projects') && r.request().method() === 'POST');
  await page.getByTestId('project-create-button').click();
  const projectResponse = await projectPost;
  expect(projectResponse.status()).toBe(201);
  const project = await projectResponse.json() as Entity;
  await expect(page.getByTestId('project-item-' + project.id)).toHaveAttribute('aria-current', 'true');

  // These are actual persisted catalog records, not placeholder UUIDs. A mock
  // provider avoids network completion requests and must NOT imply live readiness.
  const provider = await create<Entity>(page.request, '/providers', {
    name: tag + '-provider', type: 'mock', auth_config: {},
  });
  const model = await create<Entity>(page.request, '/model-profiles', {
    provider_id: provider.id, name: tag + '-model', model_id: 'offline/dry-run',
  });
  const policy = await create<Entity>(page.request, '/tool-policies', {
    name: tag + '-policy', permissions: {},
  });
  const agent = await create<Entity>(page.request, '/agents/definitions', {
    name: tag + '-agent', role: 'researcher',
    default_model_profile_id: model.id, default_tool_policy_id: policy.id,
  });
  const contract = await create<Entity>(page.request, '/contracts', {
    project_id: project.id, name: tag + '-contract',
    schema: {type:'object', required:['summary'],
      properties:{summary:{type:'string',minLength:1}}},
  });

  await page.getByTestId('nav-editor').click();
  const builder = page.getByTestId('configured-template-builder');
  await expect(builder).toBeVisible();
  await builder.locator('summary').click();
  await expect(page.getByTestId('preset-agent-0').locator('option', {hasText:agent.name}))
    .toBeAttached({timeout:15000});
  await page.getByTestId('preset-contract').selectOption(contract.id);
  await page.getByTestId('preset-agent-0').selectOption(agent.id);
  await page.getByTestId('preset-model-0').selectOption(model.id);
  await page.getByTestId('preset-policy-0').selectOption(policy.id);
  await expect(page.getByTestId('preset-build')).toBeEnabled();
  await page.getByTestId('preset-build').click();
  await page.getByTestId('editor-workflow-name').fill(workflowName);
  await page.getByTestId('editor-validate').click();
  await expect(page.getByText('Граф подходит для запуска (проверка браузера).')).toBeVisible();
  await expect(page.getByTestId('editor-publish')).toBeDisabled();

  const savePost = page.waitForResponse(r =>
    r.url().includes('/api/v1/workflows/definitions') && r.request().method() === 'POST');
  await page.getByTestId('editor-save').click();
  const savedResponse = await savePost;
  expect(savedResponse.status()).toBe(201);
  const saved = await savedResponse.json() as Entity & {version:number};
  await expect(page.getByText('Черновик сохранён на сервере. Для исполнения требуется публикация.'))
    .toBeVisible();

  const publishPost = page.waitForResponse(r =>
    r.url().includes('/workflows/definitions/' + saved.id + '/versions') &&
    r.request().method() === 'POST');
  await page.getByTestId('editor-publish').click();
  const publishResponse = await publishPost;
  expect(publishResponse.status()).toBe(201);
  const version = await publishResponse.json() as {id:string;version_number:number};
  await expect(page.getByText(/Опубликована неизменяемая версия/)).toBeVisible();
  expect(version.version_number).toBe(1);

  // The server, not the React canvas, compiles the exact immutable snapshot.
  const inspected = await page.request.get(
    '/api/v1/workflows/definitions/' + saved.id + '/versions');
  expect(inspected.ok()).toBeTruthy();
  const snapshots = (await inspected.json()).items;
  expect(snapshots).toHaveLength(1);
  const graph = snapshots[0].definition_snapshot;
  expect(graph.nodes.map((node:{type:string})=>node.type))
    .toEqual(['start','agent','gate','end']);
  expect(graph.nodes[1].config).toMatchObject({
    agent_definition_id:agent.id, model_profile_id:model.id, tool_policy_id:policy.id,
  });
  expect(graph.nodes[2].config.contract_id).toBe(contract.id);

  // Browser reload discards React memory; open the persisted definition and
  // select the immutable server version again before pressing Run.
  await page.reload();
  await page.getByTestId('project-item-' + project.id).click();
  await page.getByTestId('nav-editor').click();
  await expect(page.getByTestId('editor-workflow-list').locator('option', {hasText:workflowName}))
    .toBeAttached({timeout:15000});
  await page.getByTestId('editor-workflow-list').selectOption(saved.id);
  await expect(page.getByTestId('editor-workflow-name')).toHaveValue(workflowName);
  await expect(page.getByTestId('editor-version-select')).toHaveValue(version.id);

  const readOnly = await page.request.get(
    '/api/v1/workflows/definitions/' + saved.id + '/versions/' + version.id +
    '/preflight?project_id=' + project.id);
  expect(readOnly.status()).toBe(200);
  const report = await readOnly.json();
  expect(report.can_create_run).toBe(true);
  expect(report.execution_ready).toBe(false);
  expect(report.task_count).toBe(1);
  expect(report.checks.some((c:{code:string;status:string}) =>
    c.code === 'worker' && c.status === 'unknown')).toBe(true);

  const runPost = page.waitForResponse(r =>
    r.url().includes('/workflows/definitions/' + saved.id + '/versions/' + version.id + '/runs') &&
    r.request().method() === 'POST');
  await page.getByTestId('editor-run').click();
  const createdRunResponse = await runPost;
  expect(createdRunResponse.status()).toBe(201);
  const run = await createdRunResponse.json() as {
    id:string;project_id:string;input_data:Record<string,string>;
  };
  expect(run.project_id).toBe(project.id);
  expect(run.input_data._workflow_version_id).toBe(version.id);
  await expect(page.getByTestId('select-run-' + run.id)).toBeVisible();
  const taskResponse = await page.request.get('/api/v1/workflows/runs/' + run.id + '/tasks');
  expect(taskResponse.status()).toBe(200);
  const tasks = (await taskResponse.json()).items as Array<{
    id:string;node_id:string;contract_id:string;
    input_data:Record<string,unknown>;status:string;
  }>;
  expect(tasks).toHaveLength(1);
  expect(tasks[0].node_id).toBe('agent-1');
  expect(tasks[0].contract_id).toBe(contract.id);
  expect(tasks[0].input_data.workflow_agent_reference).toMatchObject(graph.nodes[1].config);
  expect(tasks[0].status).toBe('pending');

  await page.getByTestId('run-task-' + tasks[0].id).click();
  await expect(page.getByTestId('task-readonly-status')).toBeVisible();
  await expect(page.getByTestId('task-claim-button')).toHaveCount(0);
  await page.getByTestId('task-open-log').click();
  await expect(page.getByTestId('log-run-select')).toHaveValue(run.id);
  await expect(page.getByTestId('agent-log-feed')).toContainText('run.launched');

  // Fully new React session again, same run ID and one server-owned task.
  await page.reload();
  await page.getByTestId('project-item-' + project.id).click();
  await page.getByTestId('nav-runs').click();
  await expect(page.getByTestId('select-run-' + run.id)).toBeVisible();
  await page.getByTestId('select-run-' + run.id).click();
  await expect(page.getByTestId('run-task-' + tasks[0].id)).toBeVisible();
  expect(outgoingCompletions).toHaveLength(0);
});

test('server preflight blocks a corrupted archived graph without recording any run', async ({page}) => {
  const tag = 'negative-browser-' + Date.now();
  const project = await create<Entity>(page.request, '/projects', {name:tag});
  const contract = await create<Entity>(page.request, '/contracts', {
    project_id:project.id,name:tag+'-contract',schema:{type:'object'},
  });
  const metadata = {name:tag,version:1,created_at:'2026-11-05T00:00:00Z'};
  const nodes = [
    {id:'start',type:'start',label:'Start',position:{x:0,y:0},config:{}},
    {id:'unsupported',type:'delay',label:'Unsupported',position:{x:100,y:0},
      config:{duration_seconds:1}},
    {id:'end',type:'end',label:'End',position:{x:200,y:0},config:{}},
  ];
  const edges = nodes.slice(0,-1).map((node,index)=>({
    id:'edge-'+index,source_node_id:node.id,target_node_id:nodes[index+1].id,
    on_error:'fail',max_retries:0,output_mapping:{},
  }));
  const definition = {schema_version:'1.0',metadata,nodes,edges};
  const workflow = await create<Entity>(page.request, '/workflows/definitions',
    {project_id:project.id,name:tag,definition});
  // Legacy archive can contain invalid graph snapshots. It must not become
  // executable just because the database has a published version row.
  const archived = await create<{id:string}>(page.request,
    '/workflows/definitions/'+workflow.id+'/versions', {definition_snapshot:definition});
  const before = await page.request.get('/api/v1/workflows/runs');
  const countBefore = (await before.json()).items.length;
  await page.goto('/');
  await page.getByTestId('project-item-' + project.id).click();
  await page.getByTestId('nav-runs').click();
  await expect(page.getByTestId('runs-definition-select').locator('option', {hasText:tag}))
    .toBeAttached({timeout:15000});
  await page.getByTestId('runs-definition-select').selectOption(workflow.id);
  await expect.poll(() => page.getByTestId('runs-version-select').locator('option').count()).toBeGreaterThan(1);
  await page.getByTestId('runs-version-select').selectOption(archived.id);
  await page.getByTestId('runs-check-preflight').click();
  await expect(page.getByTestId('runs-preflight')).toContainText('заблокировано');
  await expect(page.getByTestId('runs-launch-published')).toBeDisabled();
  const post = await page.request.post(
    '/api/v1/workflows/definitions/'+workflow.id+'/versions/'+archived.id+'/runs',
    {data:{project_id:project.id,name:'must-reject'}});
  expect(post.status()).toBe(422);
  const after = await page.request.get('/api/v1/workflows/runs');
  expect((await after.json()).items.length).toBe(countBefore);
  // Contract exists; failure is explicitly graph runtime semantics, not a
  // missing Contract Gate alias or a live worker/provider credential.
  expect(contract.id).toBeTruthy();
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
  await expect(page.getByRole('heading', { name: 'Настройки проекта' })).toBeVisible();
  await expect(page.getByRole('heading', { name: 'Подключение AI-провайдера' })).toBeVisible();
  await page.getByLabel('Имя подключения').fill(name);
  await page.getByLabel('API key', { exact: true }).fill(fakeKey);
  await page.getByRole('button', { name: 'Добавить подключение' }).click();
  await expect(page.getByTestId('settings-status')).toContainText('Подключение сохранено');
  const providersResponse = await page.request.get('/api/v1/providers');
  expect(providersResponse.ok()).toBeTruthy();
  const text = await providersResponse.text();
  expect(text).not.toContain(fakeKey);
  expect(text).not.toContain('auth_config');
  const provider = JSON.parse(text).items.find((item: { name: string }) => item.name === name);
  expect(provider).toBeTruthy();
  // The model-profile form lives on the «Модели» tab of the tabbed settings
  // layout (only the active panel is rendered).
  await page.getByRole('tab', { name: 'Модели' }).click();
  await page.getByLabel('Подключение', { exact: true }).selectOption(provider.id);
  await page.getByLabel('Model ID').fill('offline/test-model');
  await page.getByRole('button', { name: 'Сохранить модель' }).click();
  await expect(page.getByTestId('settings-status')).toContainText('Профиль модели сохранён');
  const models = await page.request.get('/api/v1/model-profiles');
  expect((await models.json()).items.some(
    (item: { provider_id: string; model_id: string }) =>
      item.provider_id === provider.id && item.model_id === 'offline/test-model',
  )).toBeTruthy();
  expect(completions).toHaveLength(0);
  // Verify the browser restores the saved state from real HTTP after reload.
  await page.reload();
  await page.getByTestId('nav-settings').click();
  await page.getByRole('tab', { name: 'Подключения' }).click();
  await expect(page.getByText(name, { exact: true })).toBeVisible();
  await page.getByRole('tab', { name: 'Модели' }).click();
  await expect(page.getByText('offline/test-model — offline/test-model', { exact: true })).toBeVisible();
  expect(completions).toHaveLength(0);
  // No screenshots on success and no actual OpenRouter credential is used.
});
