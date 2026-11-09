import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
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

});
