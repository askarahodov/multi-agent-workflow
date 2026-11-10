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

  await page.getByTestId('nav-conveyor').click();
  await expect(page.getByTestId('conveyor-stage-profile-' + tasks[0].id))
    .toContainText(agent.name);
  await expect(page.getByTestId('conveyor-stage-profile-' + tasks[0].id))
    .toContainText('роль researcher');
  await page.getByTestId('conveyor-inspect-budget-' + tasks[0].id).click();
  await expect(page.getByTestId('agent-budget-state')).toContainText('USD-лимит не задан');
  await expect(page.getByTestId('agent-budget-native-boundary')).toContainText('НЕ контролируется');
  await page.getByTestId('nav-runs').click();
  await expect(page.getByTestId('select-run-' + run.id)).toBeVisible();

  // Real HTTP → Runs dashboard → QA evidence boundary → scoped operator
  // quarantine → task card → quarantine deep link. This is one run ID and
  // one persisted task; no manual claim/submit, no paid provider calls.
  await expect(page.getByTestId('run-integrity-summary')).toBeVisible();
  await expect(page.getByTestId('run-integrity-summary')).toContainText('Задач завершено: 0 / 1');
  await expect(page.getByTestId('run-release-boundary')).toContainText('Выпуск не подтверждён');
  await expect(page.getByTestId('run-release-boundary')).toContainText('политика выключена');
  const status = await page.request.get(
    '/api/v1/workflows/runs/' + run.id + '/release-approval');
  expect(status.status()).toBe(200);
  expect(await status.json()).toMatchObject({
    run_id: run.id, required: false, status: 'not_configured', approved_at: null,
  });
  await expect(page.getByTestId('run-integrity-summary')).toContainText(
    'Нет полного набора подтверждённых QA receipts',
  );
  await page.getByTestId('runs-open-recovery').click();
  await expect(page.getByTestId('recovery-run-scope')).toContainText(run.id);
  await expect(page.getByTestId('recovery-task-' + tasks[0].id)).toHaveCount(0);
  await page.getByRole('button', {name: 'Назад к запуску'}).click();

  await page.getByTestId('run-task-' + tasks[0].id).click();
  await page.getByTestId('task-open-recovery').click();
  await expect(page.getByTestId('recovery-run-scope')).toContainText(run.id);
  await expect(page.getByTestId('recovery-task-' + tasks[0].id)).toHaveCount(0);
  await page.getByRole('button', {name: 'Назад к запуску'}).click();
  await page.getByTestId('run-task-' + tasks[0].id).click();
  await expect(page.getByTestId('task-readonly-status')).toBeVisible();
  await expect(page.getByTestId('task-claim-button')).toHaveCount(0);
  await page.getByTestId('task-open-log').click();
  await expect(page.getByTestId('log-run-select')).toHaveValue(run.id);
  await expect(page.getByTestId('agent-log-feed')).toContainText('run.launched');
  // Pause must detach from the real stream, not consume/lose unseen events
  // by continuing to advance its cursor while hiding them.
  await page.getByTestId('log-pause-button').click();
  await expect(page.getByTestId('log-stream-status')).toContainText('Пауза');
  await expect(page.getByTestId('log-stream-status')).not.toContainText('В реальном времени');
  await page.getByTestId('log-pause-button').click();
  await expect(page.getByTestId('log-stream-status')).toContainText('В реальном времени');
  await expect(page.getByTestId('agent-log-feed')).toContainText('run.launched');

  // Fully new React session again, same run ID and one server-owned task.
  await page.reload();
  await page.getByTestId('project-item-' + project.id).click();
  await page.getByTestId('nav-runs').click();
  await expect(page.getByTestId('select-run-' + run.id)).toBeVisible();
  await page.getByTestId('select-run-' + run.id).click();
  await expect(page.getByTestId('run-task-' + tasks[0].id)).toBeVisible();

  // Exercise the alternate run-centric launch, not only the editor button.
  // The immutable version, explicit fresh preflight and confirmation are required.
  await page.getByTestId('runs-definition-select').selectOption(saved.id);
  await expect(page.getByTestId('runs-version-select').locator('option', { hasText: '№1' }))
    .toBeAttached();
  await page.getByTestId('runs-version-select').selectOption(version.id);
  await expect(page.getByTestId('runs-launch-published')).toBeDisabled();
  await page.getByTestId('runs-check-preflight').click();
  await expect(page.getByTestId('runs-preflight')).toContainText('создание запуска');
  await expect(page.getByTestId('runs-launch-published')).toBeEnabled();
  const otherRunPost = page.waitForResponse(r =>
    r.url().includes('/workflows/definitions/' + saved.id + '/versions/' + version.id + '/runs') &&
    r.request().method() === 'POST');
  await page.getByTestId('runs-launch-published').click();
  const otherResponse = await otherRunPost;
  expect(otherResponse.status()).toBe(201);
  const otherRun = await otherResponse.json() as { id: string };
  const posted = otherResponse.request().postDataJSON() as {
    project_id: string; name: string; idempotency_key: string;
  };
  expect(posted.idempotency_key).toMatch(/^[a-f0-9]{32}$/);
  const publishedRoute = '/api/v1/workflows/definitions/' + saved.id
    + '/versions/' + version.id + '/runs';
  const repeated = await page.request.post(publishedRoute, {data: posted});
  expect(repeated.status()).toBe(201);
  expect((await repeated.json() as {id: string}).id).toBe(otherRun.id);
  const rejected = await page.request.post(publishedRoute, {
    data: {...posted, name: posted.name + '-changed'},
  });
  expect(rejected.status()).toBe(409);
  const persistedRuns = await page.request.get('/api/v1/workflows/runs?limit=100');
  expect(persistedRuns.status()).toBe(200);
  const allRuns = (await persistedRuns.json() as {
    items: Array<{id:string;project_id:string}>;
  }).items;
  expect(allRuns.filter(item => item.id === otherRun.id)).toHaveLength(1);
  await expect(page.getByText(new RegExp('Запуск №1 создан: ' + otherRun.id))).toBeVisible();
  await page.reload();
  await page.getByTestId('project-item-' + project.id).click();
  await page.getByTestId('nav-runs').click();
  await expect(page.getByTestId('select-run-' + otherRun.id)).toBeVisible();
  await page.getByTestId('select-run-' + otherRun.id).click();
  await expect(page.locator('[data-testid^="run-task-"]')).toHaveCount(1);

  // Real server commits the POST, but a simulated network reset hides its
  // response from the browser. Navigation must not discard its pending key.
  await page.getByTestId('runs-definition-select').selectOption(saved.id);
  await expect(page.getByTestId('runs-version-select').locator('option', {hasText:'№1'})).toBeAttached();
  await page.getByTestId('runs-version-select').selectOption(version.id);
  await page.getByTestId('runs-check-preflight').click();
  await expect(page.getByTestId('runs-launch-published')).toBeEnabled();
  let lostCommitId = '';
  let lostKey = '';
  const routePattern = '**/workflows/definitions/' + saved.id + '/versions/' + version.id + '/runs';
  await page.route(routePattern, async route => {
    if (route.request().method() !== 'POST') {
      await route.continue();
      return;
    }
    const attempted = route.request().postDataJSON() as {idempotency_key:string};
    lostKey = attempted.idempotency_key;
    const realResponse = await route.fetch(); // no API mocking; commits to SQLite
    expect(realResponse.status()).toBe(201);
    lostCommitId = (await realResponse.json() as {id:string}).id;
    await route.abort('failed'); // only the browser response is lost
  });
  await page.getByTestId('runs-launch-published').click();
  await expect.poll(() => lostCommitId).not.toBe('');
  await page.unroute(routePattern);
  await page.getByTestId('nav-settings').click();
  await page.getByTestId('nav-runs').click();
  // A full tab reload also restores the unresolved key from sessionStorage.
  await page.reload();
  await page.getByTestId('project-item-' + project.id).click();
  await page.getByTestId('nav-runs').click();
  await page.getByTestId('runs-definition-select').selectOption(saved.id);
  await expect(page.getByTestId('runs-version-select').locator('option', {hasText:'№1'})).toBeAttached();
  await page.getByTestId('runs-version-select').selectOption(version.id);
  // No new client preflight is necessary for an unresolved confirmed-in-DB
  // launch. The server matches the original principal/key/payload.
  await expect(page.getByTestId('runs-launch-published')).toBeEnabled();
  const recoveredPost = page.waitForResponse(response =>
    response.url().includes('/workflows/definitions/' + saved.id + '/versions/' + version.id + '/runs') &&
    response.request().method() === 'POST');
  await page.getByTestId('runs-launch-published').click();
  const recovered = await recoveredPost;
  expect(recovered.status()).toBe(201);
  expect((await recovered.json() as {id:string}).id).toBe(lostCommitId);
  expect((recovered.request().postDataJSON() as {idempotency_key:string}).idempotency_key)
    .toBe(lostKey);
  const allAfter = await page.request.get('/api/v1/workflows/runs?limit=100');
  expect(allAfter.status()).toBe(200);
  expect((await allAfter.json() as {items:Array<{id:string}>}).items
    .filter(item => item.id === lostCommitId)).toHaveLength(1);
  expect(outgoingCompletions).toHaveLength(0);
});


test('real Compose run POST remains project-scoped after delayed reply, lost reply and recovery', async ({page})=>{
  test.setTimeout(180_000);
  const tag='runs-scope-'+Date.now();
  const first=await create<Entity>(page.request,'/projects',{name:tag+'-a'});
  const second=await create<Entity>(page.request,'/projects',{name:tag+'-b'});
  const provider=await create<Entity>(page.request,'/providers',{
    name:tag+'-provider',type:'mock',auth_config:{},
  });
  const model=await create<Entity>(page.request,'/model-profiles',{
    provider_id:provider.id,name:tag+'-model',model_id:'offline/dry-run',
  });
  const policy=await create<Entity>(page.request,'/tool-policies',{
    name:tag+'-policy',permissions:{},
  });
  const agent=await create<Entity>(page.request,'/agents/definitions',{
    name:tag+'-agent',role:'researcher',default_model_profile_id:model.id,
    default_tool_policy_id:policy.id,
  });
  const contract=await create<Entity>(page.request,'/contracts',{
    project_id:first.id,name:tag+'-contract',
    schema:{type:'object',required:['summary'],
      properties:{summary:{type:'string',minLength:1}}},
  });
  const nodes=[
    {id:'start',type:'start',label:'Начало',position:{x:0,y:0},config:{}},
    {id:'agent',type:'agent',label:'Developer',position:{x:220,y:0},
      config:{agent_definition_id:agent.id,model_profile_id:model.id,tool_policy_id:policy.id}},
    {id:'gate',type:'gate',label:'Contract',position:{x:440,y:0},
      config:{gate_type:'automatic',contract_id:contract.id}},
    {id:'end',type:'end',label:'Готово',position:{x:660,y:0},config:{}},
  ];
  const edges=nodes.slice(0,-1).map((node,i)=>({
    id:'edge-'+i,source_node_id:node.id,target_node_id:nodes[i+1].id,
    output_mapping:{},on_error:'fail',max_retries:0,
  }));
  const definition={schema_version:'1.0',
    metadata:{name:tag,description:'Run context browser acceptance',version:1,
      created_at:'2026-11-10T00:00:00Z'},
    nodes,edges,
  };
  const saved=await create<Entity&{version:number}>(page.request,'/workflows/definitions',{
    project_id:first.id,name:tag,definition,
  });
  const published=await create<{id:string;version_number:number}>(
    page.request,'/workflows/definitions/'+saved.id+'/versions',{
      expected_version:saved.version,definition_snapshot:definition,changelog:'Browser acceptance',
    });
  const runPath='/api/v1/workflows/definitions/'+saved.id+
    '/versions/'+published.id+'/runs';
  const routePattern='**/workflows/definitions/'+saved.id+
    '/versions/'+published.id+'/runs';
  const completions:string[]=[];
  page.on('request',request=>{
    if(request.url().includes('/completions'))completions.push(request.url());
  });
  acceptConfirmation(page);
  await page.goto('/');
  await page.getByTestId('project-item-'+first.id).click();
  await page.getByTestId('nav-runs').click();
  async function selectPublished(){
    await expect(page.getByTestId('runs-definition-select')
      .locator('option',{hasText:tag})).toBeAttached({timeout:15000});
    await page.getByTestId('runs-definition-select').selectOption(saved.id);
    await expect(page.getByTestId('runs-version-select')
      .locator('option',{hasText:'№1'})).toBeAttached();
    await page.getByTestId('runs-version-select').selectOption(published.id);
  }
  await selectPublished();
  await page.getByTestId('runs-check-preflight').click();
  await expect(page.getByTestId('runs-launch-published')).toBeEnabled();

  // The real server commits the POST immediately. Only its HTTP response is
  // delayed while the operator switches to another project.
  let release! :()=>void;
  const continueResponse=new Promise<void>(resolve=>{release=resolve;});
  let committedId='';
  let firstKey='';
  await page.route(routePattern,async route=>{
    if(route.request().method()!=='POST'){await route.continue();return;}
    firstKey=(route.request().postDataJSON() as {idempotency_key:string}).idempotency_key;
    const real=await route.fetch();
    expect(real.status()).toBe(201);
    committedId=(await real.json() as {id:string}).id;
    await continueResponse;
    await route.fulfill({response:real});
  });
  const delivered=page.waitForResponse(response=>response.url().includes(runPath) &&
    response.request().method()==='POST');
  await page.getByTestId('runs-launch-published').click();
  await expect.poll(()=>committedId).not.toBe('');
  expect(firstKey).toMatch(/^[a-f0-9]{32}$/);
  await page.getByTestId('nav-project').click();
  await page.getByTestId('project-item-'+second.id).click();
  await page.getByTestId('nav-runs').click();
  release();
  const deliveredResponse=await delivered;
  expect(deliveredResponse.status()).toBe(201);
  expect((await deliveredResponse.json() as {id:string}).id).toBe(committedId);
  // Unroute only after the in-flight route handler has completed fulfilment.
  await page.unroute(routePattern);
  await expect(page.getByTestId('runs-launch-published')).toBeDisabled();
  await expect(page.getByText('Детали выбранного запуска')).toHaveCount(0);
  await expect(page.getByTestId('select-run-'+committedId)).toHaveCount(0);
  const persisted=await page.request.get('/api/v1/workflows/runs/'+committedId);
  expect(persisted.status()).toBe(200);
  expect(await persisted.json()).toMatchObject({
    id:committedId,project_id:first.id,
    input_data:{_workflow_version_id:published.id},
  });
  const tasks=await page.request.get('/api/v1/workflows/runs/'+committedId+'/tasks');
  expect(tasks.status()).toBe(200);
  const taskItems=(await tasks.json() as {items:Array<{node_id:string;contract_id:string}>}).items;
  expect(taskItems).toHaveLength(1);
  expect(taskItems[0]).toMatchObject({node_id:'agent',contract_id:contract.id});

  // Switching back shows the durable run, but does not silently select it.
  await page.getByTestId('nav-project').click();
  await page.getByTestId('project-item-'+first.id).click();
  await page.getByTestId('nav-runs').click();
  await expect(page.getByTestId('select-run-'+committedId)).toBeVisible();
  await expect(page.getByText('Детали выбранного запуска')).toHaveCount(0);
  await selectPublished();
  await page.getByTestId('runs-check-preflight').click();
  await expect(page.getByTestId('runs-launch-published')).toBeEnabled();

  // A second intentional launch commits in SQLite but its browser response
  // is lost. After switching away/back and page reload, the original key
  // must replay the original run instead of creating a duplicate.
  let ambiguousId='';
  let ambiguousKey='';
  await page.route(routePattern,async route=>{
    if(route.request().method()!=='POST'){await route.continue();return;}
    ambiguousKey=(route.request().postDataJSON() as {idempotency_key:string}).idempotency_key;
    const real=await route.fetch();
    expect(real.status()).toBe(201);
    ambiguousId=(await real.json() as {id:string}).id;
    await route.abort('failed');
  });
  const aborted=page.waitForEvent('requestfailed',{
    predicate:r=>r.url().includes(runPath)&&r.method()==='POST',
  });
  await page.getByTestId('runs-launch-published').click();
  await expect.poll(()=>ambiguousId).not.toBe('');
  expect(ambiguousId).not.toBe(committedId);
  expect(ambiguousKey).not.toBe(firstKey);
  await aborted;
  // Wait until Playwright has delivered the deliberate transport failure.
  await page.unroute(routePattern);
  await page.getByTestId('nav-project').click();
  await page.getByTestId('project-item-'+second.id).click();
  await page.getByTestId('nav-runs').click();
  await expect(page.getByText('Детали выбранного запуска')).toHaveCount(0);
  await page.reload();
  await page.getByTestId('project-item-'+first.id).click();
  await page.getByTestId('nav-runs').click();
  await selectPublished();
  await expect(page.getByTestId('runs-launch-published')).toBeEnabled();
  const retry=page.waitForResponse(r=>r.url().includes(runPath)&&
    r.request().method()==='POST');
  await page.getByTestId('runs-launch-published').click();
  const recovered=await retry;
  expect(recovered.status()).toBe(201);
  expect((await recovered.json() as {id:string}).id).toBe(ambiguousId);
  expect((recovered.request().postDataJSON() as {idempotency_key:string}).idempotency_key)
    .toBe(ambiguousKey);
  const all=await page.request.get('/api/v1/workflows/runs?project_id='+first.id+'&limit=100');
  expect(all.status()).toBe(200);
  const sourceRuns=(await all.json() as {items:Array<{id:string}>}).items;
  expect(sourceRuns.filter(r=>r.id===committedId)).toHaveLength(1);
  expect(sourceRuns.filter(r=>r.id===ambiguousId)).toHaveLength(1);
  expect(completions).toHaveLength(0);
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


test('editor project ownership survives navigation and real HTTP never saves an old document under a new project',async({page})=>{
  test.setTimeout(120_000);
  const tag='scope-editor-'+Date.now();
  const first=await create<Entity>(page.request,'/projects',{name:tag+'-a'});
  const second=await create<Entity>(page.request,'/projects',{name:tag+'-b'});
  const completions:string[]=[];
  page.on('request',request=>{if(request.url().includes('/completions'))completions.push(request.url());});
  acceptConfirmation(page);
  await page.goto('/');
  await expect(page.getByTestId('project-item-'+first.id)).toBeVisible();
  await page.getByTestId('project-item-'+first.id).click();
  await page.getByTestId('nav-editor').click();
  await page.getByTestId('editor-workflow-name').fill(tag+'-saved');
  const beforePost=page.waitForResponse(r=>r.url().includes('/api/v1/workflows/definitions')&&
    r.request().method()==='POST');
  await page.getByTestId('editor-save').click();
  const beforeResponse=await beforePost;
  expect(beforeResponse.status()).toBe(201);
  const saved=await beforeResponse.json() as Entity&{project_id:string};
  expect(saved.project_id).toBe(first.id);

  await page.getByTestId('nav-project').click();
  await page.getByTestId('project-item-'+second.id).click();
  await page.getByTestId('nav-editor').click();
  await expect(page.getByTestId('editor-project-mismatch')).toBeVisible();
  await expect(page.getByTestId('editor-workflow-name')).toHaveValue(tag+'-saved');
  await expect(page.getByTestId('editor-save')).toBeDisabled();
  await expect(page.getByTestId('editor-run')).toBeDisabled();
  await page.getByRole('button',{name:'Новый'}).click();
  await expect(page.getByTestId('editor-project-mismatch')).toHaveCount(0);
  await page.getByTestId('editor-workflow-name').fill(tag+'-new');
  const secondPost=page.waitForResponse(r=>r.url().includes('/api/v1/workflows/definitions')&&
    r.request().method()==='POST');
  await page.getByTestId('editor-save').click();
  const secondResponse=await secondPost;
  expect(secondResponse.status()).toBe(201);
  const savedSecond=await secondResponse.json() as Entity&{project_id:string};
  expect(savedSecond.project_id).toBe(second.id);
  expect(savedSecond.id).not.toBe(saved.id);
  const original=await page.request.get('/api/v1/workflows/definitions/'+saved.id);
  expect(original.status()).toBe(200);
  expect(await original.json()).toMatchObject({name:tag+'-saved',project_id:first.id});
  expect(completions).toHaveLength(0);
});


test('profiles nav uses restricted shared editor with persisted role, policy, stages and versioned copy',async({page})=>{
  test.setTimeout(120_000);
  const tag='canonical-profiles-'+Date.now();
  const provider=await create<Entity>(page.request,'/providers',{
    name:tag+'-provider',type:'mock',auth_config:{},
  });
  const model=await create<Entity>(page.request,'/model-profiles',{
    provider_id:provider.id,name:tag+'-model',model_id:'offline/dry-run',
  });
  const completions:string[]=[];
  page.on('request',request=>{
    if(request.url().includes('/completions'))completions.push(request.url());
  });
  await page.goto('/');
  await page.getByTestId('nav-profiles').click();
  await expect(page.getByRole('heading',{level:1,name:'Профили агентов'})).toBeVisible();
  await expect(page.getByLabel('Модель профиля').locator('option',{hasText:tag+'-model'}))
    .toBeAttached({timeout:15000});
  // A reviewer cannot author a policy with filesystem writes, even though the
  // same persisted agent-management policy endpoint serves both UI routes.
  await page.getByLabel('Роль агента').selectOption('reviewer');
  await expect(page.getByLabel('Разрешённая запись (только developer)')).toBeDisabled();
  await page.getByLabel('Имя политики').fill(tag+'-deny');
  await page.getByRole('button',{name:'Создать tool-policy'}).click();
  await expect(page.getByText(/Политика сохранена/)).toBeVisible();
  const choices=page.getByLabel('Tool policy');
  const policyId=await choices.inputValue();
  expect(policyId).toBeTruthy();
  await page.getByLabel('Имя профиля').fill(tag+'-reviewer');
  await page.getByLabel('System instructions').fill('Independently verify server artifacts');
  await page.getByLabel('Модель профиля').selectOption(model.id);
  await page.getByLabel('Стадии исполнения (через запятую)').fill('tests, review, security');
  const post=page.waitForResponse(r=>r.url().includes('/api/v1/agents/definitions')&&
    r.request().method()==='POST');
  await page.getByRole('button',{name:'Создать профиль'}).click();
  const created=await post;
  expect(created.status()).toBe(201);
  const profile=await created.json() as {
    id:string;version:number;role:string;default_model_profile_id:string;
    default_tool_policy_id:string;supported_stages:string[];
  };
  expect(profile).toMatchObject({role:'reviewer',version:1,
    default_model_profile_id:model.id,default_tool_policy_id:policyId,
    supported_stages:['tests','review','security']});
  await expect(page.getByTestId('saved-agent-profiles')).toContainText(tag+'-reviewer');
  await page.reload();
  await page.getByTestId('nav-profiles').click();
  await expect(page.getByTestId('saved-agent-profiles')).toContainText(tag+'-reviewer');
  const row=page.getByTestId('saved-agent-profiles').locator('li')
    .filter({hasText:tag+'-reviewer'});
  await row.getByRole('button',{name:'Изменить'}).click();
  await expect(page.getByLabel('Стадии исполнения (через запятую)'))
    .toHaveValue('tests, review, security');
  await page.getByLabel('Навыки (через запятую)').fill('audit, code-review');
  const patch=page.waitForResponse(r=>r.url().includes('/api/v1/agents/definitions/'+profile.id)&&
    r.request().method()==='PATCH');
  await page.getByRole('button',{name:'Сохранить изменения профиля'}).click();
  const revised=await patch;
  expect(revised.status()).toBe(200);
  expect(await revised.json()).toMatchObject({
    id:profile.id,version:2,skills:['audit','code-review'],
    supported_stages:['tests','review','security'],
  });
  await expect(page.getByTestId('saved-agent-profiles')).toContainText('v2');
  expect(completions).toHaveLength(0);
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
  // Confirm both records survive a reload using the real backend, not just React state.
  await page.reload();
  await page.getByTestId('nav-settings').click();
  await page.getByRole('tab', { name: 'Подключения' }).click();
  await expect(page.getByText(name, { exact: true })).toBeVisible();
  await page.getByRole('tab', { name: 'Модели' }).click();
  await expect(page.locator('ul li span').getByText(
    'offline/test-model — offline/test-model', { exact: true },
  )).toBeVisible();
  expect(completions).toHaveLength(0);
  // No screenshots on success and no actual OpenRouter credential is used.
});

test('first-run wizard creates a project and workspace through real orchestration HTTP', async ({ page }) => {
  const unique = 'wizard-compose-' + Date.now();
  const completions: string[] = [];
  page.on('request', request => {
    if (request.url().includes('/api/v1/completions')) completions.push(request.url());
  });
  await page.goto('/');
  await page.getByTestId('nav-setup').click();
  await expect(page.getByRole('heading', { name: 'Настройка проекта' })).toBeVisible();
  await expect(page.getByTestId('setup-project-select')).toBeVisible();
  await page.getByTestId('setup-project-name').fill(unique);
  const projectPost = page.waitForResponse(response =>
    response.url().includes('/api/v1/projects') &&
    response.request().method() === 'POST');
  await page.getByRole('button', { name: 'Создать проект' }).click();
  expect((await projectPost).status()).toBe(201);
  await expect(page.getByTestId('setup-workspace-name')).toBeVisible();
  await page.getByTestId('setup-workspace-name').fill('Default workspace');
  const workspacePost = page.waitForResponse(response =>
    response.url().includes('/api/v1/workspaces') &&
    response.request().method() === 'POST');
  await page.getByRole('button', { name: 'Создать пространство' }).click();
  expect((await workspacePost).status()).toBe(201);
  await expect(page.getByText(/реальные серверные справочники/)).toBeVisible();
  const projects = await page.request.get('/api/v1/projects');
  expect(projects.status()).toBe(200);
  expect((await projects.json() as Array<{ name: string }>).some(p => p.name === unique)).toBe(true);
  expect(completions).toHaveLength(0);
});

test('settings creates independently scoped developer/reviewer profiles usable by workflow editor', async ({page}) => {
  test.setTimeout(120_000);
  const tag = 'profile-browser-' + Date.now();
  const completions: string[] = [];
  page.on('request', request => {
    if (request.url().includes('/completions')) completions.push(request.url());
  });
  const project = await create<Entity>(page.request, '/projects', { name: tag });
  const provider = await create<Entity>(page.request, '/providers', {
    name: tag + '-provider', type: 'mock', auth_config: {},
  });
  const model = await create<Entity>(page.request, '/model-profiles', {
    provider_id: provider.id, name: tag + '-model', model_id: 'offline/model',
  });
  await page.goto('/');
  await page.getByTestId('nav-settings').click();
  await page.getByRole('tab', { name: 'Роли агентов' }).click();
  await expect(page.getByRole('heading', { name: 'Создать профиль агента' })).toBeVisible();

  const makePolicy = async (policyName: string) => {
    await page.getByLabel('Имя политики').fill(policyName);
    await page.getByRole('button', { name: 'Создать tool-policy' }).click();
    await expect(page.getByTestId('agent-profile-status')).toContainText('Политика сохранена');
  };
  await makePolicy(tag + '-developer-policy');
  await page.getByLabel('Имя профиля').fill(tag + '-developer');
  await page.getByLabel('System instructions').fill('Implement scoped project changes.');
  await page.getByLabel('Модель профиля').selectOption(model.id);
  await page.getByRole('button', { name: 'Создать профиль', exact: true }).click();
  await expect(page.getByTestId('agent-profile-status')).toContainText('Профиль сохранён');
  await expect(page.getByTestId('saved-agent-profiles')).toContainText(tag + '-developer');

  await page.getByLabel('Роль агента').selectOption('reviewer');
  await makePolicy(tag + '-reviewer-policy');
  await page.getByLabel('Имя профиля').fill(tag + '-reviewer');
  await page.getByLabel('System instructions').fill('Independently verify evidence.');
  await page.getByLabel('Модель профиля').selectOption(model.id);
  await page.getByRole('button', { name: 'Создать профиль', exact: true }).click();
  await expect(page.getByTestId('agent-profile-status')).toContainText('Профиль сохранён');

  const response = await page.request.get('/api/v1/agents/definitions');
  expect(response.status()).toBe(200);
  const agents = (await response.json()).items as Array<{
    id: string; name: string; role: string; default_model_profile_id: string;
    default_tool_policy_id: string; version: number;
  }>;
  const developer = agents.find(item => item.name === tag + '-developer');
  const reviewer = agents.find(item => item.name === tag + '-reviewer');
  expect(developer).toMatchObject({ role: 'developer', default_model_profile_id: model.id, version: 1 });
  expect(reviewer).toMatchObject({ role: 'reviewer', default_model_profile_id: model.id, version: 1 });
  expect(developer?.default_tool_policy_id).not.toBe(reviewer?.default_tool_policy_id);

  // Browser reload must reconstruct definitions from the backend, not React state.
  await page.reload();
  await page.getByTestId('nav-settings').click();
  await page.getByRole('tab', { name: 'Роли агентов' }).click();
  await expect(page.getByTestId('saved-agent-profiles')).toContainText(tag + '-developer');
  await expect(page.getByTestId('saved-agent-profiles')).toContainText(tag + '-reviewer');

  // The published graph builder's selector reads these same server definitions.
  await page.getByTestId('nav-project').click();
  await page.getByTestId('project-item-' + project.id).click();
  await page.getByTestId('nav-editor').click();
  const builder = page.getByTestId('configured-template-builder');
  await expect(builder).toBeVisible();
  await builder.locator('summary').click();
  await expect(page.getByTestId('preset-agent-0').locator('option', { hasText: tag + '-developer' }))
    .toBeAttached({ timeout: 15_000 });
  await expect(page.getByTestId('preset-agent-0').locator('option', { hasText: tag + '-reviewer' }))
    .toBeAttached();
  expect(completions).toHaveLength(0);
});

test('real browser shows durable server budget without a paid provider request', async ({page}) => {
  const tag = 'budget-browser-' + Date.now();
  const completions: string[] = [];
  page.on('request', r => { if (r.url().includes('/completions')) completions.push(r.url()); });
  const provider = await create<Entity>(page.request, '/providers', {
    name: tag + '-provider', type: 'mock', auth_config: {},
  });
  const model = await create<Entity>(page.request, '/model-profiles', {
    provider_id: provider.id, name: tag + '-model', model_id: 'offline/model',
  });
  const policy = await create<Entity>(page.request, '/tool-policies', {
    name: tag + '-policy', permissions: {},
  });
  const profile = await create<Entity>(page.request, '/agents/definitions', {
    name: tag + '-developer', role: 'developer',
    default_model_profile_id: model.id, default_tool_policy_id: policy.id,
    budget_limit: 1.5,
  });
  const apiResponse = await page.request.get(
    '/api/v1/agents/definitions/' + profile.id + '/budget');
  expect(apiResponse.status()).toBe(200);
  expect(await apiResponse.json()).toMatchObject({
    agent_definition_id: profile.id,
    limit_microusd: 1_500_000,
    spent_estimated_microusd: 0,
    reserved_microusd: 0,
    remaining_estimated_microusd: 1_500_000,
    completion_budget_status: 'available',
    native_budget_enforced: false,
  });
  await page.goto('/');
  await page.getByTestId('nav-profiles').click();
  const budgetProfile=page.getByTestId('saved-agent-profiles').locator('li')
    .filter({hasText:tag+'-developer'});
  await expect(budgetProfile).toBeVisible();
  await budgetProfile.getByRole('button',{name:'Изменить'}).click();
  await expect(page.getByTestId('agent-budget-state')).toContainText('Есть расчётный остаток');
  await expect(page.getByTestId('agent-budget-amounts')).toContainText('Незакрытых резервов: 0');
  await expect(page.getByTestId('agent-budget-native-boundary')).toContainText('НЕ контролируется');

  await page.reload();
  await page.getByTestId('nav-profiles').click();
  await page.getByRole('button', { name: new RegExp(tag + '-developer') }).click();
  await expect(page.getByTestId('agent-budget-state')).toContainText('Есть расчётный остаток');
  expect(completions).toHaveLength(0);
});

test('ticket-only SSE and WebSocket stream a persisted run without URL API keys', async ({page}) => {
  // Default local acceptance must still run against flags=0. Only the paired,
  // explicit ticket-mode run is allowed to exercise this alternate contract.
  test.skip(process.env.MAW_STREAM_TICKET_E2E !== '1', 'ticket-only Compose opt-in required');
  test.setTimeout(60_000);
  const tag = 'ticket-compose-' + Date.now();
  const project = await create<Entity>(page.request, '/projects', {name: tag});
  const run = await create<Entity>(page.request, '/workflows/runs', {
    project_id: project.id, name: tag + '-run', tasks: [{title: 'offline task'}],
  });
  const prefix = '/api/v1/workflows/runs/' + encodeURIComponent(run.id);
  const issue = async (transport: 'sse' | 'websocket') => {
    const reply = await page.request.post(prefix + '/stream-tickets', {data: {transport}});
    expect(reply.status()).toBe(200);
    expect(reply.headers()['cache-control']).toContain('no-store');
    const payload = await reply.json() as {ticket:string;expires_in:number};
    expect(payload.ticket).toMatch(/^[A-Za-z0-9_-]{43}$/);
    expect(payload.expires_in).toBeLessThanOrEqual(30);
    return payload.ticket;
  };

  // Legacy credentials in stream URLs are deliberately rejected in ticket mode.
  const unauthorized = await page.request.get(prefix + '/events?api_key=dev&max_events=1');
  expect(unauthorized.status()).toBe(401);

  const sseTicket = await issue('sse');
  const ssePath = prefix + '/events?stream_ticket=' + encodeURIComponent(sseTicket) + '&max_events=1';
  const first = await page.request.get(ssePath);
  expect(first.status()).toBe(200);
  expect(await first.text()).toContain('run.launched');
  expect((await page.request.get(ssePath)).status()).toBe(403);

  const wsTicket = await issue('websocket');
  await page.goto('/');
  const frame = await page.evaluate(async ({path}) => {
    return new Promise<string>((resolve, reject) => {
      const url = new URL(path, location.href);
      url.protocol = location.protocol === 'https:' ? 'wss:' : 'ws:';
      const socket = new WebSocket(url.toString());
      const timeout = window.setTimeout(() => {
        socket.close();
        reject(new Error('ticket WebSocket timed out'));
      }, 10_000);
      socket.onmessage = event => {
        window.clearTimeout(timeout);
        resolve(String(event.data));
        socket.close();
      };
      socket.onerror = () => {
        window.clearTimeout(timeout);
        reject(new Error('ticket WebSocket handshake failed'));
      };
      socket.onclose = () => window.clearTimeout(timeout);
    });
  }, {path: prefix + '/ws?stream_ticket=' + encodeURIComponent(wsTicket) + '&max_events=1'});
  expect(JSON.parse(frame)).toMatchObject({type: 'run_event'});
  expect(frame).toContain('run.launched');
  expect(frame).not.toContain('api_key');
  // A ticket bound to WS cannot be reused in SSE, even after WS consumed it.
  expect((await page.request.get(
    prefix + '/events?stream_ticket=' + encodeURIComponent(wsTicket) + '&max_events=1',
  )).status()).toBe(403);
});
