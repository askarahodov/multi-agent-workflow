import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import AgentProfilesPage from './AgentProfilesPage';

const sent: Array<{url: string; method: string; body?: unknown}> = [];
let records: Array<Record<string, unknown>>;
let policies: Array<Record<string, unknown>>;
function json(data: unknown, status = 200): Response {
  return { ok: status < 400, status, json: async () => data } as Response;
}
beforeEach(() => {
  sent.length = 0; records = []; policies = [];
  vi.stubGlobal('fetch', vi.fn(async (url: string, init?: RequestInit) => {
    const method = init?.method ?? 'GET';
    const body = init?.body ? JSON.parse(init.body as string) as Record<string, unknown> : undefined;
    sent.push({url, method, body});
    if (method === 'GET') {
      if (url.includes('/agents/definitions')) return json({ items: records });
      if (url.includes('/model-profiles')) return json({ items: [{id:'m1',name:'default',model_id:'model-x'}] });
      if (url.includes('/tool-policies')) return json({ items: policies.length ? policies : [{id:'t1',name:'restricted'}] });
    }
    if (method === 'POST' && url.endsWith('/tool-policies')) {
      const policy = { id: 't2', ...body }; policies.push(policy);
      return json(policy, 201);
    }
    if (method === 'POST' && url.endsWith('/agents/definitions')) {
      const agent = { id: 'a1', version: 1, ...body };
      records = [agent]; return json(agent, 201);
    }
    if (method === 'PATCH' && url.includes('/agents/definitions/')) {
      const agent = {...records[0], ...body, version: 2};
      records = [agent]; return json(agent);
    }
    return json({}, 404);
  }));
});
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

describe('server-backed agent profiles', () => {
  it('creates a versioned agent with model, tool policy, role and restricted budget metadata', async () => {
    render(<AgentProfilesPage />);
    await screen.findByText('Профилей нет. Создайте первый.');
    fireEvent.change(screen.getByLabelText('Название'), { target: { value: 'Developer' } });
    fireEvent.change(screen.getByLabelText('Профиль модели'), { target: { value: 'm1' } });
    fireEvent.change(screen.getByLabelText('Политика инструментов'), { target: { value: 't1' } });
    fireEvent.change(screen.getByLabelText('Бюджет USD (обычные completions; не native)'), { target: { value: '3.5' } });
    await act(async () => { fireEvent.click(screen.getByRole('button', { name: 'Создать профиль' })); });
    await waitFor(() => expect(sent.some((x) => x.method === 'POST' && x.url.endsWith('/agents/definitions'))).toBe(true));
    const payload = sent.find((x) => x.method === 'POST' && x.url.endsWith('/agents/definitions'))?.body as Record<string, unknown>;
    expect(payload).toMatchObject({ name:'Developer', role:'developer', default_model_profile_id:'m1', default_tool_policy_id:'t1', max_concurrency:1, budget_limit:3.5 });
    expect(screen.getByText('Профиль сохранён в agent-management.')).toBeInTheDocument();
  });

  it('creates a deny-all policy without wildcard permissions and selects it', async () => {
    render(<AgentProfilesPage />);
    await screen.findByText('Профилей нет. Создайте первый.');
    fireEvent.change(screen.getByLabelText('Название политики'), { target: { value: 'deny-all' } });
    await act(async () => { fireEvent.click(screen.getByRole('button', { name: 'Создать политику' })); });
    await waitFor(() => expect(sent.some((x) => x.url.endsWith('/tool-policies') && x.method === 'POST')).toBe(true));
    const payload = sent.find((x) => x.url.endsWith('/tool-policies') && x.method === 'POST')?.body as Record<string, unknown>;
    expect(Object.values(payload.permissions as Record<string, unknown>).every((a: unknown) => Array.isArray(a) && a.length === 0)).toBe(true);
  });
});
