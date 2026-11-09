import { afterEach, describe, expect, it, vi } from 'vitest';
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import SettingsPage from './SettingsPage';

afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

describe('provider catalogue and multi-provider configuration', () => {
  it('loads OpenRouter models from the backend and suggests safe supported defaults', async () => {
    const calls: string[] = [];
    vi.stubGlobal('fetch', vi.fn(async (url: string) => {
      calls.push(url);
      let data: unknown = { items: [] };
      if (url === '/api/v1/providers') data = { items: [{ id: 'p1', type: 'openrouter', name: 'OpenRouter', version: 1, is_active: true }] };
      if (url.endsWith('/model-catalog')) data = {
        provider_id: 'p1', source: 'openrouter', models: [{
          id: 'lab/code-model', name: 'Code Model', context_length: 120000,
          supported_parameters: ['temperature', 'tools', 'max_tokens'],
          default_parameters: { temperature: 0.5, max_tokens: 4096 },
          pricing_per_token: { prompt: '0.000001', completion: '0.000002' },
        }],
      };
      return { ok: true, status: 200, json: async () => data };
    }));
    render(<SettingsPage />);
    fireEvent.click(screen.getByRole('tab', { name: 'Модели' }));
    await waitFor(() => expect(screen.getByRole('option', { name: 'OpenRouter' })).toBeInTheDocument());
    fireEvent.change(screen.getByLabelText('Подключение'), { target: { value: 'p1' } });
    await screen.findByRole('option', { name: /Code Model \(lab\/code-model\)/ });
    fireEvent.change(screen.getByLabelText('Модель OpenRouter'), { target: { value: 'lab/code-model' } });
    expect(screen.getByLabelText('Model ID')).toHaveValue('lab/code-model');
    expect(screen.getByLabelText('Temperature')).toHaveValue(0.5);
    expect(screen.getByLabelText('Max tokens')).toHaveValue(4096);
    expect(screen.getByTestId('model-catalog-metadata')).toHaveTextContent('120000');
    fireEvent.change(screen.getByLabelText('Поиск моделей OpenRouter'), { target: { value: 'lab/code' } });
    expect(screen.getByRole('option', { name: /Code Model/ })).toBeInTheDocument();
    expect(calls).toContain('/api/v1/providers/p1/model-catalog');
    expect(calls.every((call) => !call.includes('openrouter.ai'))).toBe(true);
  });

  it('can create a custom OpenAI-compatible provider without invoking a model completion', async () => {
    const posts: unknown[] = [];
    vi.stubGlobal('fetch', vi.fn(async (url: string, init?: RequestInit) => {
      if (init?.method === 'POST' && url === '/api/v1/providers') {
        posts.push(JSON.parse(init.body as string));
        return { ok: true, status: 201, json: async () => ({ id: 'custom1', type: 'custom', name: 'Custom', is_active: true, version: 1 }) };
      }
      return { ok: true, status: 200, json: async () => ({ items: [] }) };
    }));
    render(<SettingsPage />);
    await screen.findByText('Подключений пока нет.');
    fireEvent.change(screen.getByLabelText('Тип провайдера'), { target: { value: 'custom' } });
    fireEvent.change(screen.getByLabelText('Base URL API'), { target: { value: 'https://llm.example.com/v1' } });
    fireEvent.change(screen.getByLabelText('Имя подключения'), { target: { value: 'Custom' } });
    fireEvent.click(screen.getByRole('button', { name: 'Добавить подключение' }));
    await waitFor(() => expect(posts).toHaveLength(1));
    expect(posts[0]).toMatchObject({ type: 'custom', base_url: 'https://llm.example.com/v1', name: 'Custom' });
    expect((posts[0] as {auth_config: object}).auth_config).toEqual({});
    await waitFor(() => expect(screen.getByRole('tab', { name: 'Модели' })).toHaveAttribute('aria-selected', 'true'));
  });
  it('persists OpenRouter provider even when unrelated model/agent lists fail', async () => {
    const requests: Array<{ url: string; method?: string }> = [];
    vi.stubGlobal('fetch', vi.fn(async (url: string, init?: RequestInit) => {
      requests.push({ url, method: init?.method });
      if (init?.method === 'POST' && url === '/api/v1/providers') {
        return { ok: true, status: 201, json: async () => ({
          id: 'saved-provider', name: 'OpenRouter', type: 'openrouter',
          is_active: true, version: 1,
        }) };
      }
      if (url === '/api/v1/model-profiles' || url === '/api/v1/agents/definitions') {
        return { ok: false, status: 503, json: async () => ({ detail: 'unavailable' }) };
      }
      if (url.includes('/model-catalog')) return {
        ok: true, status: 200, json: async () => ({ models: [] }),
      };
      return { ok: true, status: 200, json: async () => ({ items: [] }) };
    }));
    render(<SettingsPage />);
    await screen.findByText('Подключений пока нет.');
    fireEvent.change(screen.getByLabelText('API key'), { target: { value: 'sk-private-canary' } });
    fireEvent.click(screen.getByRole('button', { name: 'Добавить подключение' }));
    await waitFor(() => expect(screen.getByText(/Подключение сохранено/)).toBeInTheDocument());
    expect(screen.getByRole('tab', { name: 'Модели' })).toHaveAttribute('aria-selected', 'true');
    expect(requests.filter((r) => r.url === '/api/v1/providers' && r.method === 'POST')).toHaveLength(1);
    fireEvent.click(screen.getByRole('tab', { name: 'Подключения' }));
    expect(screen.getByLabelText('API key')).toHaveValue('');
    expect(screen.getByText('OpenRouter', { selector: 'strong' })).toBeInTheDocument();
    expect(document.body.textContent).not.toContain('sk-private-canary');
  });

  it('reports a duplicate provider by status without displaying server response or API key', async () => {
    vi.stubGlobal('fetch', vi.fn(async (url: string, init?: RequestInit) => {
      if (init?.method === 'POST' && url === '/api/v1/providers') return {
        ok: false, status: 409,
        json: async () => ({ detail: 'unsafe private api_key sk-private-canary' }),
      };
      return { ok: true, status: 200, json: async () => ({ items: [] }) };
    }));
    render(<SettingsPage />);
    await screen.findByText('Подключений пока нет.');
    fireEvent.change(screen.getByLabelText('API key'), { target: { value: 'sk-private-canary' } });
    fireEvent.click(screen.getByRole('button', { name: 'Добавить подключение' }));
    await screen.findByText(/Подключение с таким именем уже существует/);
    expect(document.body.textContent).not.toContain('unsafe private');
    expect(document.body.textContent).not.toContain('sk-private-canary');
    expect(screen.getByLabelText('API key')).toHaveValue('sk-private-canary');
  });

  it('shows a provider list while unrelated settings endpoints fail on initial load', async () => {
    vi.stubGlobal('fetch', vi.fn(async (url: string) => {
      if (url === '/api/v1/providers') return {
        ok: true, status: 200, json: async () => ({ items: [{
          id: 'p1', name: 'Visible provider', type: 'mock', version: 1, is_active: true,
        }] }),
      };
      return { ok: false, status: 503, json: async () => ({ detail: 'unavailable' }) };
    }));
    render(<SettingsPage />);
    expect(await screen.findByText('Visible provider')).toBeInTheDocument();
    expect(screen.queryByText(/Не удалось загрузить настройки/)).not.toBeInTheDocument();
  });

  it('completes provider to model setup with a broken agent list', async () => {
    const created: Array<{ url: string; payload: Record<string, unknown> }> = [];
    vi.stubGlobal('fetch', vi.fn(async (url: string, init?: RequestInit) => {
      if (init?.method === 'POST') {
        const payload = JSON.parse(init.body as string) as Record<string, unknown>;
        created.push({ url, payload });
        if (url === '/api/v1/providers') return {
          ok: true, status: 201, json: async () => ({
            id: 'p-created', name: 'OpenRouter', type: 'openrouter', is_active: true, version: 1,
          }),
        };
        if (url === '/api/v1/model-profiles') return {
          ok: true, status: 201, json: async () => ({
            id: 'm-created', provider_id: 'p-created', name: 'Demo model',
            model_id: 'openai/demo', is_default: true, version: 1,
          }),
        };
      }
      if (url === '/api/v1/agents/definitions') return {
        ok: false, status: 503, json: async () => ({ detail: 'unavailable' }),
      };
      if (url.endsWith('/model-catalog')) return {
        ok: true, status: 200, json: async () => ({ models: [] }),
      };
      return { ok: true, status: 200, json: async () => ({ items: [] }) };
    }));
    render(<SettingsPage />);
    await screen.findByText('Подключений пока нет.');
    fireEvent.change(screen.getByLabelText('API key'), { target: { value: 'sk-canary' } });
    fireEvent.click(screen.getByRole('button', { name: 'Добавить подключение' }));
    await waitFor(() => expect(screen.getByRole('tab', { name: 'Модели' })).toHaveAttribute('aria-selected', 'true'));
    fireEvent.change(screen.getByLabelText('Model ID'), { target: { value: 'openai/demo' } });
    fireEvent.change(screen.getByLabelText('Имя профиля'), { target: { value: 'Demo model' } });
    fireEvent.click(screen.getByRole('button', { name: 'Сохранить модель' }));
    await screen.findByText('Профиль модели сохранён.');
    expect(created.map((item) => item.url)).toEqual([
      '/api/v1/providers', '/api/v1/model-profiles',
    ]);
    expect(created[1].payload).toMatchObject({
      provider_id: 'p-created', model_id: 'openai/demo', name: 'Demo model',
    });
    expect(document.body.textContent).not.toContain('sk-canary');
  });

  it('does not reset a provider created while a stale initial GET is pending', async () => {
    let resolveOld: ((value: unknown) => void) | undefined;
    const old = new Promise<unknown>((resolve) => { resolveOld = resolve; });
    vi.stubGlobal('fetch', vi.fn(async (url: string, init?: RequestInit) => {
      if (init?.method === 'POST' && url === '/api/v1/providers') return {
        ok: true, status: 201, json: async () => ({
          id: 'new-provider', name: 'OpenRouter', type: 'openrouter', is_active: true, version: 1,
        }),
      };
      if (url === '/api/v1/providers') return old;
      if (url.endsWith('/model-catalog')) return {
        ok: true, status: 200, json: async () => ({ models: [] }),
      };
      return { ok: true, status: 200, json: async () => ({ items: [] }) };
    }));
    render(<SettingsPage />);
    fireEvent.change(screen.getByLabelText('API key'), { target: { value: 'sk-canary' } });
    fireEvent.click(screen.getByRole('button', { name: 'Добавить подключение' }));
    await screen.findByText(/Подключение сохранено/);
    await act(async () => {
      resolveOld?.({ ok: true, status: 200, json: async () => ({ items: [] }) });
      await old;
    });
    fireEvent.click(screen.getByRole('tab', { name: 'Подключения' }));
    expect(screen.getByText('OpenRouter', { selector: 'strong' })).toBeInTheDocument();
    fireEvent.click(screen.getByRole('tab', { name: 'Модели' }));
    expect(screen.getByRole('option', { name: 'OpenRouter' })).toBeInTheDocument();
  });

  it('never changes provider default when model list failed', async () => {
    let sent: Record<string, unknown> | undefined;
    vi.stubGlobal('fetch', vi.fn(async (url: string, init?: RequestInit) => {
      if (url === '/api/v1/providers') return {
        ok: true, status: 200, json: async () => ({ items: [{
          id: 'p-existing', name: 'OpenRouter', type: 'openrouter', is_active: true, version: 1,
        }] }),
      };
      if (url === '/api/v1/model-profiles' && init?.method !== 'POST') return {
        ok: false, status: 503, json: async () => ({ detail: 'broken' }),
      };
      if (url === '/api/v1/model-profiles' && init?.method === 'POST') {
        sent = JSON.parse(init.body as string) as Record<string, unknown>;
        return { ok: true, status: 201, json: async () => ({
          id: 'new-model', provider_id: 'p-existing', name: 'Test',
          model_id: 'offline/test', is_default: false, version: 1,
        }) };
      }
      if (url.endsWith('/model-catalog')) return {
        ok: true, status: 200, json: async () => ({ models: [] }),
      };
      return { ok: true, status: 200, json: async () => ({ items: [] }) };
    }));
    render(<SettingsPage />);
    await screen.findByText(/Список моделей недоступен/);
    fireEvent.click(screen.getByRole('tab', { name: 'Модели' }));
    fireEvent.change(screen.getByLabelText('Подключение'), { target: { value: 'p-existing' } });
    fireEvent.change(screen.getByLabelText('Model ID'), { target: { value: 'offline/test' } });
    fireEvent.click(screen.getByRole('button', { name: 'Сохранить модель' }));
    await screen.findByText('Профиль модели сохранён.');
    expect(sent?.is_default).toBe(false);
  });

  it('recovers pre-existing provider, model and agent after an invalidated startup load', async () => {
    let finishStale: ((value: unknown) => void) | undefined;
    const stale = new Promise<unknown>((resolve) => { finishStale = resolve; });
    let providerGets = 0;
    vi.stubGlobal('fetch', vi.fn(async (url: string, init?: RequestInit) => {
      if (url === '/api/v1/providers' && init?.method === 'POST') return {
        ok: true, status: 201, json: async () => ({
          id: 'new', name: 'OpenRouter', type: 'openrouter', is_active: true, version: 1,
        }),
      };
      if (url === '/api/v1/providers') {
        if (++providerGets === 1) return stale;
        return { ok: true, status: 200, json: async () => ({ items: [
          { id: 'legacy', name: 'Legacy', type: 'mock', is_active: true, version: 1 },
          { id: 'new', name: 'OpenRouter', type: 'openrouter', is_active: true, version: 1 },
        ] }) };
      }
      if (url === '/api/v1/model-profiles') return { ok: true, status: 200, json: async () => ({
        items: [{ id: 'old-model', provider_id: 'legacy', name: 'Legacy model',
          model_id: 'offline/legacy', is_default: true, version: 1 }],
      }) };
      if (url === '/api/v1/agents/definitions') return { ok: true, status: 200, json: async () => ({
        items: [{ id: 'agent1', name: 'Legacy agent', default_model_profile_id: 'old-model', version: 1 }],
      }) };
      if (url.endsWith('/model-catalog')) return {
        ok: true, status: 200, json: async () => ({ models: [] }),
      };
      return { ok: true, status: 200, json: async () => ({ items: [] }) };
    }));
    render(<SettingsPage />);
    fireEvent.change(screen.getByLabelText('API key'), { target: { value: 'sk-safe-fixture' } });
    fireEvent.click(screen.getByRole('button', { name: 'Добавить подключение' }));
    await screen.findByText(/Подключение сохранено/);
    // Complete the old snapshot only after the fresh post-save read has run.
    await screen.findByRole('option', { name: 'Legacy' });
    await act(async () => {
      finishStale?.({ ok: true, status: 200, json: async () => ({ items: [] }) });
      await stale;
    });
    fireEvent.click(screen.getByRole('tab', { name: 'Подключения' }));
    expect(screen.getByText('Legacy', { selector: 'strong' })).toBeInTheDocument();
    expect(screen.getByText('OpenRouter', { selector: 'strong' })).toBeInTheDocument();
    fireEvent.click(screen.getByRole('tab', { name: 'Роли агентов' }));
    expect(screen.getByLabelText('Модель агента Legacy agent')).toHaveValue('old-model');
  });

  it('does not revive a provider version from a pending post-create GET after PATCH', async () => {
    let finishStale: ((response: unknown) => void) | undefined;
    const stale = new Promise<unknown>((resolve) => { finishStale = resolve; });
    let listCount = 0;
    vi.stubGlobal('fetch', vi.fn(async (url: string, init?: RequestInit) => {
      if (url === '/api/v1/providers' && init?.method === 'POST') return {
        ok: true, status: 201, json: async () => ({
          id: 'p1', type: 'openrouter', name: 'OpenRouter', is_active: true, version: 1,
        }),
      };
      if (url === '/api/v1/providers' && !init?.method) {
        if (++listCount === 2) return stale;
        return { ok: true, status: 200, json: async () => ({ items: [] }) };
      }
      if (url === '/api/v1/providers/p1' && init?.method === 'PATCH') return {
        ok: true, status: 200, json: async () => ({
          id: 'p1', type: 'openrouter', name: 'OpenRouter', is_active: false, version: 2,
        }),
      };
      if (url.endsWith('/model-catalog')) return {
        ok: true, status: 200, json: async () => ({ models: [] }),
      };
      return { ok: true, status: 200, json: async () => ({ items: [] }) };
    }));
    render(<SettingsPage />);
    await screen.findByText('Подключений пока нет.');
    fireEvent.change(screen.getByLabelText('API key'), { target: { value: 'sk-canary' } });
    fireEvent.click(screen.getByRole('button', { name: 'Добавить подключение' }));
    await screen.findByText(/Подключение сохранено/);
    await waitFor(() => expect(listCount).toBe(2));
    fireEvent.click(screen.getByRole('tab', { name: 'Подключения' }));
    fireEvent.click(screen.getByRole('button', { name: 'Отключить' }));
    await screen.findByRole('button', { name: 'Включить' });
    await act(async () => {
      finishStale?.({ ok: true, status: 200, json: async () => ({ items: [
        { id: 'p1', name: 'OpenRouter', type: 'openrouter', is_active: true, version: 1 },
      ] }) });
      await stale;
    });
    expect(screen.getByRole('button', { name: 'Включить' })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Отключить' })).not.toBeInTheDocument();
  });

});
