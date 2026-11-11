import { afterEach, describe, expect, it, vi } from 'vitest';
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import AgentProfilesManager, { type AgentProfile } from './AgentProfilesManager';

const model = { id: 'm1', provider_id: 'p1', name: 'Offline', model_id: 'offline/model' };
const deny = { id: 'pol-deny', name: 'deny-all', version: 1, permissions: {
  fs_read: [], fs_write: [], git: [], shell: [], network: [],
} };
const write = { id: 'pol-write', name: 'writer', version: 1, permissions: {
  fs_read: ['/workspace/proj/**'], fs_write: ['/workspace/proj/out/**'],
  git: [], shell: [], network: [],
} };
const json = (data: unknown, status = 200) => ({
  ok: status < 400, status, json: async () => data,
});
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

describe('restricted agent profile authoring', () => {
  it('creates separate developer and reviewer profiles without model completion', async () => {
    const posts: Array<{ url: string; body: Record<string, unknown> }> = [];
    vi.stubGlobal('fetch', vi.fn(async (url: string, init?: RequestInit) => {
      if (url === '/api/v1/tool-policies') return json({ items: [deny, write] });
      if (init?.method === 'POST') {
        const body = JSON.parse(init.body as string) as Record<string, unknown>;
        posts.push({ url, body });
        return json({
          ...body, id: 'a' + posts.length, version: 1,
        }, 201);
      }
      return json({}, 404);
    }));
    const onSaved = vi.fn();
    const { rerender } = render(
      <AgentProfilesManager agents={[]} models={[model]} onSaved={onSaved} />,
    );
    await screen.findByRole('option', { name: 'writer' });
    fireEvent.change(screen.getByLabelText('Имя профиля'), { target: { value: 'Dev' } });
    fireEvent.change(screen.getByLabelText('System instructions'), {
      target: { value: 'Implement scoped changes' },
    });
    fireEvent.change(screen.getByLabelText('Модель профиля'), { target: { value: 'm1' } });
    fireEvent.change(screen.getByLabelText('Tool policy'), { target: { value: 'pol-write' } });
    fireEvent.click(screen.getByRole('button', { name: 'Создать профиль' }));
    await waitFor(() => expect(onSaved).toHaveBeenCalledTimes(1));
    expect(posts[0]).toMatchObject({
      url: '/api/v1/agents/definitions',
      body: { name: 'Dev', role: 'developer', default_model_profile_id: 'm1',
        default_tool_policy_id: 'pol-write', system_prompt: 'Implement scoped changes',
        max_concurrency: 1 },
    });
    rerender(<AgentProfilesManager agents={[onSaved.mock.calls[0][0] as AgentProfile]}
      models={[model]} onSaved={onSaved} />);
    fireEvent.change(screen.getByLabelText('Роль агента'), { target: { value: 'reviewer' } });
    expect(screen.queryByRole('option', { name: 'writer' })).not.toBeInTheDocument();
    fireEvent.change(screen.getByLabelText('Имя профиля'), { target: { value: 'Independent review' } });
    fireEvent.change(screen.getByLabelText('System instructions'), {
      target: { value: 'Independently verify published artifacts' },
    });
    fireEvent.change(screen.getByLabelText('Модель профиля'), { target: { value: 'm1' } });
    fireEvent.change(screen.getByLabelText('Tool policy'), { target: { value: 'pol-deny' } });
    fireEvent.click(screen.getByRole('button', { name: 'Создать профиль' }));
    await waitFor(() => expect(onSaved).toHaveBeenCalledTimes(2));
    expect(posts[1].body).toMatchObject({
      name: 'Independent review', role: 'reviewer',
      default_tool_policy_id: 'pol-deny', supported_stages: ['reviewer'],
    });
    expect(posts.every(post => post.url !== '/api/v1/completions')).toBe(true);
    expect(vi.mocked(fetch).mock.calls.every(([url]) => url !== '/api/v1/completions')).toBe(true);
  });

  it('refuses negative budget and carries an explicit USD cap in Settings profile authoring', async () => {
    const posts: Record<string, unknown>[] = [];
    vi.stubGlobal('fetch', vi.fn(async (url: string, init?: RequestInit) => {
      if (url === '/api/v1/tool-policies') return json({ items: [deny] });
      if (init?.method === 'POST') {
        const payload = JSON.parse(init.body as string) as Record<string, unknown>;
        posts.push(payload);
        return json({ ...payload, id: 'budget-profile', version: 1 }, 201);
      }
      return json({}, 404);
    }));
    render(<AgentProfilesManager agents={[]} models={[model]} onSaved={vi.fn()}/>);
    await screen.findByRole('option', { name: 'deny-all' });
    fireEvent.change(screen.getByLabelText('Имя профиля'), { target: { value: 'Budgeted developer' } });
    fireEvent.change(screen.getByLabelText('System instructions'), { target: { value: 'Implement' } });
    fireEvent.change(screen.getByLabelText('Модель профиля'), { target: { value: model.id } });
    fireEvent.change(screen.getByLabelText('Tool policy'), { target: { value: deny.id } });
    const field = screen.getByLabelText('Бюджет USD (для обычных completions)');
    fireEvent.change(field, { target: { value: '-1' } });
    expect(screen.getByRole('button', { name: 'Создать профиль' })).toBeDisabled();
    expect(posts).toHaveLength(0);
    fireEvent.change(field, { target: { value: '2.5' } });
    fireEvent.click(screen.getByRole('button', { name: 'Создать профиль' }));
    await waitFor(() => expect(posts).toHaveLength(1));
    expect(posts[0].budget_limit).toBe(2.5);
    expect(vi.mocked(fetch).mock.calls.some(([url]) => String(url).includes('/completions'))).toBe(false);
  });

  it('creates deny-all tool-policy and never widens a reviewer to write access', async () => {
    const saved: Record<string, unknown>[] = [];
    vi.stubGlobal('fetch', vi.fn(async (_url: string, init?: RequestInit) => {
      if (init?.method === 'POST') {
        const payload = JSON.parse(init.body as string) as Record<string, unknown>;
        saved.push(payload);
        return json({ ...payload, id: 'new-policy', version: 1 }, 201);
      }
      return json({ items: [] });
    }));
    render(<AgentProfilesManager agents={[]} models={[model]} onSaved={vi.fn()} />);
    fireEvent.change(screen.getByLabelText('Роль агента'), { target: { value: 'reviewer' } });
    const forbidden = screen.getByLabelText('Разрешённая запись (только developer)');
    expect(forbidden).toBeDisabled();
    fireEvent.change(screen.getByLabelText('Имя политики'), { target: { value: 'review-readonly' } });
    fireEvent.click(screen.getByRole('button', { name: 'Создать tool-policy' }));
    await screen.findByText(/Политика сохранена/);
    expect(saved).toHaveLength(1);
    expect(saved[0]).toMatchObject({
      name: 'review-readonly', permissions: {
        fs_read: [], fs_write: [], git: [], shell: [], network: [],
      },
    });
  });

  it('keeps independently assigned stages on PATCH and duplicates all stage bindings', async () => {
    const profile: AgentProfile = {
      id: 'multi-stage', name: 'Specialist', role: 'developer', version: 5,
      system_prompt: 'Implement and verify', default_model_profile_id: 'm1',
      default_tool_policy_id: deny.id, max_concurrency: 2,
      supported_stages: ['implementation', 'tests'],
    };
    const writes: Array<{ method: string; body: Record<string, unknown> }> = [];
    vi.stubGlobal('fetch', vi.fn(async (url: string, init?: RequestInit) => {
      if (url === '/api/v1/tool-policies' && !init?.method) {
        return json({ items: [deny] });
      }
      if (init?.method === 'PATCH' || init?.method === 'POST') {
        const body = JSON.parse(init.body as string) as Record<string, unknown>;
        writes.push({ method: init.method, body });
        return json({ ...profile, ...body, version: 6 }, init.method === 'POST' ? 201 : 200);
      }
      return json({}, 404);
    }));
    const saved = vi.fn();
    render(<AgentProfilesManager agents={[profile]} models={[model]} onSaved={saved} />);
    await screen.findByRole('option', { name: 'deny-all' });
    fireEvent.click(screen.getByRole('button', { name: 'Изменить' }));
    fireEvent.change(screen.getByLabelText('Имя профиля'), {
      target: { value: 'Specialist renamed' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Сохранить изменения профиля' }));
    await waitFor(() => expect(writes).toHaveLength(1));
    expect(writes[0].method).toBe('PATCH');
    expect(writes[0].body).toMatchObject({ version: 5, name: 'Specialist renamed' });
    expect(writes[0].body).not.toHaveProperty('supported_stages');
    expect(saved).toHaveBeenCalledWith(expect.objectContaining({
      supported_stages: ['implementation', 'tests'],
    }));

    fireEvent.click(screen.getByRole('button', { name: 'Копировать' }));
    expect(screen.getByLabelText('Имя профиля')).toHaveValue('Specialist — копия');
    fireEvent.click(screen.getByRole('button', { name: 'Создать профиль' }));
    await waitFor(() => expect(writes).toHaveLength(2));
    expect(writes[1].method).toBe('POST');
    expect(writes[1].body.supported_stages).toEqual(['implementation', 'tests']);
    expect(writes[1].body).not.toHaveProperty('version');
    // Neither editing route can invoke a provider completion.
    expect(vi.mocked(fetch).mock.calls.some(([url]) =>
      String(url).includes('/completions'))).toBe(false);
  });

  it('patches an existing profile using its version and does not claim success on 409', async () => {
    const agent: AgentProfile = {
      id: 'agent-1', name: 'Dev', role: 'developer', version: 3,
      default_model_profile_id: 'm1', default_tool_policy_id: 'pol-deny',
      system_prompt: 'old', max_concurrency: 1,
    };
    const patchBodies: Record<string, unknown>[] = [];
    vi.stubGlobal('fetch', vi.fn(async (url: string, init?: RequestInit) => {
      if (url === '/api/v1/tool-policies') return json({ items: [deny] });
      if (init?.method === 'PATCH') {
        patchBodies.push(JSON.parse(init.body as string) as Record<string, unknown>);
        return json({ detail: 'Conflict' }, 409);
      }
      return json({}, 404);
    }));
    const onSaved = vi.fn();
    render(<AgentProfilesManager agents={[agent]} models={[model]} onSaved={onSaved} />);
    await screen.findByRole('option', { name: 'deny-all' });
    fireEvent.click(screen.getByRole('button', { name: 'Изменить' }));
    fireEvent.change(screen.getByLabelText('System instructions'), { target: { value: 'updated' } });
    fireEvent.click(screen.getByRole('button', { name: 'Сохранить изменения профиля' }));
    await screen.findByText(/Версия профиля изменена/);
    expect(patchBodies).toHaveLength(1);
    expect(patchBodies[0]).toMatchObject({ version: 3, system_prompt: 'updated' });
    expect(onSaved).not.toHaveBeenCalled();
  });
  it('authors filesystem paths in the exact secure native gateway namespace', async () => {
    const posts: Array<Record<string, unknown>> = [];
    vi.stubGlobal('fetch', vi.fn(async (_url: string, init?: RequestInit) => {
      if (init?.method === 'POST') {
        const payload = JSON.parse(init.body as string) as Record<string, unknown>;
        posts.push(payload);
        return json({ ...payload, id: 'trusted-policy', version: 1 }, 201);
      }
      return json({ items: [] });
    }));
    render(<AgentProfilesManager agents={[]} models={[model]} onSaved={vi.fn()} />);
    fireEvent.change(screen.getByLabelText('Имя политики'), { target: { value: 'scoped-native' } });
    fireEvent.change(screen.getByLabelText('Разрешённое чтение (необязательно)'), {
      target: { value: '/srv/maw/workspace/project/**' },
    });
    fireEvent.change(screen.getByLabelText('Разрешённая запись (только developer)'), {
      target: { value: '/srv/maw/workspace/project/out/**' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Создать tool-policy' }));
    await screen.findByText(/Политика сохранена/);
    expect(posts).toHaveLength(1);
    expect(posts[0].permissions).toMatchObject({
      fs_read: ['/srv/maw/workspace/project/**'],
      fs_write: ['/srv/maw/workspace/project/out/**'],
      shell: [], git: [], network: [],
    });
    // A path that was legal in the old UI but cannot match the mounted
    // native gateway namespace must not be sent to the server.
    fireEvent.change(screen.getByLabelText('Имя политики'), { target: { value: 'wrong-root' } });
    fireEvent.change(screen.getByLabelText('Разрешённое чтение (необязательно)'), {
      target: { value: '/workspace/project/**' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Создать tool-policy' }));
    await screen.findByText(/Путь должен иметь вид \/srv\/maw\/workspace\/project/);
    expect(posts).toHaveLength(1);
  });

  it('refuses empty runtime instructions and requires an actionable prompt', async () => {
    const post = vi.fn();
    vi.stubGlobal('fetch', vi.fn(async (url: string, init?: RequestInit) => {
      if (url === '/api/v1/tool-policies') return json({ items: [deny] });
      if (init?.method === 'POST') return post();
      return json({}, 404);
    }));
    render(<AgentProfilesManager agents={[]} models={[model]} onSaved={vi.fn()} />);
    await screen.findByRole('option', { name: 'deny-all' });
    fireEvent.change(screen.getByLabelText('Имя профиля'), { target: { value: 'Reviewer' } });
    fireEvent.change(screen.getByLabelText('Модель профиля'), { target: { value: 'm1' } });
    fireEvent.change(screen.getByLabelText('Tool policy'), { target: { value: 'pol-deny' } });
    expect(screen.getByRole('button', { name: 'Создать профиль' })).toBeDisabled();
    fireEvent.change(screen.getByLabelText('System instructions'), { target: { value: '    ' } });
    expect(screen.getByRole('button', { name: 'Создать профиль' })).toBeDisabled();
    expect(post).not.toHaveBeenCalled();
  });

  it('loads an existing policy from the next cursor page before editing', async () => {
    const fetchCalls: string[] = [];
    vi.stubGlobal('fetch', vi.fn(async (url: string) => {
      fetchCalls.push(url);
      if (url === '/api/v1/tool-policies') return json({
        items: [write], next_cursor: 'opaque-page-2',
      });
      if (url === '/api/v1/tool-policies?after=opaque-page-2') return json({
        items: [deny], next_cursor: null,
      });
      return json({}, 404);
    }));
    const existing: AgentProfile = {
      id: 'agent-previous', name: 'Independent reviewer', role: 'reviewer',
      version: 4, system_prompt: 'Verify evidence',
      default_model_profile_id: 'm1', default_tool_policy_id: 'pol-deny',
    };
    render(<AgentProfilesManager agents={[existing]} models={[model]} onSaved={vi.fn()} />);
    await screen.findByRole('option', { name: 'deny-all' });
    fireEvent.click(screen.getByRole('button', { name: 'Изменить' }));
    expect(screen.getByLabelText('Tool policy')).toHaveValue('pol-deny');
    expect(screen.getByRole('button', { name: 'Сохранить изменения профиля' })).toBeEnabled();
    expect(fetchCalls.filter(url => url.startsWith('/api/v1/tool-policies'))).toEqual([
      '/api/v1/tool-policies', '/api/v1/tool-policies?after=opaque-page-2',
    ]);
    // Editing the persisted profile now also reads its budget. The new
    // read-only request must not disturb policy pagination or call a model.
    expect(fetchCalls).toContain('/api/v1/agents/definitions/agent-previous/budget');
    expect(fetchCalls.every(url => !url.includes('/completions'))).toBe(true);
  });

  it('fails closed on repeated tool-policy cursor instead of silently hiding entries', async () => {
    vi.stubGlobal('fetch', vi.fn(async (url: string) => json({
      items: url.includes('after=') ? [deny] : [write], next_cursor: 'cycle',
    })));
    render(<AgentProfilesManager agents={[]} models={[model]} onSaved={vi.fn()} />);
    await screen.findByRole('alert');
    expect(screen.queryByRole('option', { name: 'writer' })).not.toBeInTheDocument();
    expect(screen.queryByRole('option', { name: 'deny-all' })).not.toBeInTheDocument();
  });

  it('keeps a created tool policy when an older list GET completes later', async () => {
    let finishList: ((page: unknown) => void) | undefined;
    const pendingList = new Promise<unknown>(resolve => { finishList = resolve; });
    vi.stubGlobal('fetch', vi.fn(async (url: string, init?: RequestInit) => {
      if (url === '/api/v1/tool-policies' && !init?.method) {
        return pendingList;
      }
      if (url === '/api/v1/tool-policies' && init?.method === 'POST') {
        const payload = JSON.parse(init.body as string) as Record<string, unknown>;
        return json({ ...payload, id: 'new-policy', version: 1 }, 201);
      }
      return json({}, 404);
    }));
    render(<AgentProfilesManager agents={[]} models={[model]} onSaved={vi.fn()} />);
    fireEvent.change(screen.getByLabelText('Имя политики'), {
      target: { value: 'new-policy' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Создать tool-policy' }));
    await screen.findByText(/Политика сохранена/);
    expect(screen.getByRole('option', { name: 'new-policy' })).toBeInTheDocument();
    await act(async () => {
      finishList?.(json({ items: [], next_cursor: null }));
      await pendingList;
    });
    await waitFor(() => {
      expect(screen.getByRole('option', { name: 'new-policy' })).toBeInTheDocument();
    });
  });


  it('retains a verified POST policy after the catalog GET fails and can save the agent', async () => {
    let rejectList: ((reason: Error) => void) | undefined;
    const pendingList = new Promise<never>((_resolve, reject) => { rejectList = reject; });
    const postBodies: Array<{ url: string; body: Record<string, unknown> }> = [];
    vi.stubGlobal('fetch', vi.fn(async (url: string, init?: RequestInit) => {
      if (url === '/api/v1/tool-policies' && !init?.method) return pendingList;
      if (init?.method === 'POST') {
        const body = JSON.parse(init.body as string) as Record<string, unknown>;
        postBodies.push({ url, body });
        return json({ ...body, id: 'post-confirmed', version: 1 }, 201);
      }
      return json({}, 404);
    }));
    const onSaved = vi.fn();
    render(<AgentProfilesManager agents={[]} models={[model]} onSaved={onSaved} />);
    fireEvent.change(screen.getByLabelText('Имя политики'), {
      target: { value: 'verified-read-only' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Создать tool-policy' }));
    await screen.findByText(/Политика сохранена/);
    await act(async () => { rejectList?.(new Error('catalog unavailable')); });
    expect(screen.getByRole('alert')).toHaveTextContent(/Каталог tool-policy недоступен/);
    expect(screen.getByRole('option', { name: 'verified-read-only' })).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText('Имя профиля'), {
      target: { value: 'Developer' },
    });
    fireEvent.change(screen.getByLabelText('System instructions'), {
      target: { value: 'Implement reviewed changes' },
    });
    fireEvent.change(screen.getByLabelText('Модель профиля'), { target: { value: 'm1' } });
    expect(screen.getByRole('button', { name: 'Создать профиль' })).toBeEnabled();
    fireEvent.click(screen.getByRole('button', { name: 'Создать профиль' }));
    await waitFor(() => expect(onSaved).toHaveBeenCalledTimes(1));
    expect(postBodies).toHaveLength(2);
    expect(postBodies[1]).toMatchObject({
      url: '/api/v1/agents/definitions',
      body: { default_tool_policy_id: 'post-confirmed' },
    });
  });

  it('allows a newly confirmed policy after an initial catalog failure, without trusting missing entries', async () => {
    const postBodies: Array<{ url: string; body: Record<string, unknown> }> = [];
    vi.stubGlobal('fetch', vi.fn(async (url: string, init?: RequestInit) => {
      if (url === '/api/v1/tool-policies' && !init?.method) throw new Error('offline');
      if (init?.method === 'POST') {
        const body = JSON.parse(init.body as string) as Record<string, unknown>;
        postBodies.push({ url, body });
        return json({ ...body, id: 'verified-after-failure', version: 1 }, 201);
      }
      return json({}, 404);
    }));
    render(<AgentProfilesManager agents={[]} models={[model]} onSaved={vi.fn()} />);
    await screen.findByRole('alert');
    expect(screen.getByRole('button', { name: 'Создать профиль' })).toBeDisabled();
    expect(screen.queryByRole('option', { name: 'deny-all' })).not.toBeInTheDocument();
    fireEvent.change(screen.getByLabelText('Имя политики'), {
      target: { value: 'confirmed-after-error' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Создать tool-policy' }));
    await screen.findByText(/Политика сохранена/);
    expect(screen.getByRole('option', { name: 'confirmed-after-error' })).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText('Имя профиля'), { target: { value: 'Dev' } });
    fireEvent.change(screen.getByLabelText('System instructions'), {
      target: { value: 'Work within scoped tool grants' },
    });
    fireEvent.change(screen.getByLabelText('Модель профиля'), { target: { value: 'm1' } });
    expect(screen.getByRole('button', { name: 'Создать профиль' })).toBeEnabled();
    expect(postBodies).toHaveLength(1);
  });

  it('edits description, stages and skills only when explicitly changed; copies all fields',async()=>{
    const original:AgentProfile={
      id:'advanced',name:'Developer',role:'developer',version:7,
      system_prompt:'Write validated code',description:'Initial purpose',
      default_model_profile_id:model.id,default_tool_policy_id:deny.id,
      supported_stages:['implementation','tests'],skills:['python','git'],
    };
    const writes:Array<{method:string;body:Record<string,unknown>}>=[];
    vi.stubGlobal('fetch',vi.fn(async(url:string,init?:RequestInit)=>{
      if(url==='/api/v1/tool-policies'&&!init?.method)return json({items:[deny]});
      if(init?.method==='PATCH'||init?.method==='POST'){
        const body=JSON.parse(init.body as string) as Record<string,unknown>;
        writes.push({method:init.method,body});
        return json({...original,...body,version:8},init.method==='POST'?201:200);
      }
      return json({},404);
    }));
    render(<AgentProfilesManager agents={[original]} models={[model]} onSaved={vi.fn()}/>);
    await screen.findByRole('option',{name:'deny-all'});
    fireEvent.click(screen.getByRole('button',{name:'Изменить'}));
    fireEvent.change(screen.getByLabelText('Описание профиля'),{
      target:{value:'New scoped purpose'}});
    fireEvent.change(screen.getByLabelText('Стадии исполнения (через запятую)'),{
      target:{value:'implementation, tests, review'}});
    fireEvent.change(screen.getByLabelText('Навыки (через запятую)'),{
      target:{value:'python, git, python'}});
    fireEvent.click(screen.getByRole('button',{name:'Сохранить изменения профиля'}));
    await waitFor(()=>expect(writes).toHaveLength(1));
    expect(writes[0]).toMatchObject({method:'PATCH',body:{version:7,
      description:'New scoped purpose',supported_stages:['implementation','tests','review'],
      skills:['python','git']}});
    fireEvent.click(screen.getByRole('button',{name:'Копировать'}));
    expect(screen.getByLabelText('Описание профиля')).toHaveValue('Initial purpose');
    expect(screen.getByLabelText('Стадии исполнения (через запятую)'))
      .toHaveValue('implementation, tests');
    fireEvent.click(screen.getByRole('button',{name:'Создать профиль'}));
    await waitFor(()=>expect(writes).toHaveLength(2));
    expect(writes[1]).toMatchObject({method:'POST',body:{
      supported_stages:['implementation','tests'],skills:['python','git'],
      description:'Initial purpose'}});
  });

});
