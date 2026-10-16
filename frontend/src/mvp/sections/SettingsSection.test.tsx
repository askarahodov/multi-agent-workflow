import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import SettingsSection from './SettingsSection';

const provider = {
  id: 'p-1', name: 'OpenRouter', type: 'openrouter', is_active: true, version: 1,
};
const json = (value: unknown, status = 200) => ({
  ok: status < 400, status,
  json: async () => value,
});

describe('SettingsSection', () => {
  beforeEach(() => {
    vi.stubGlobal('fetch', vi.fn(async (input: string, init?: RequestInit) => {
      if (init?.method === 'POST' && input === '/api/v1/providers') return json(provider, 201);
      if (input === '/api/v1/providers') return json({ items: [], total: 0 });
      if (input === '/api/v1/model-profiles') return json({ items: [], total: 0 });
      if (input === '/api/v1/agents/definitions') return json({ items: [], total: 0 });
      return json({}, 404);
    }));
  });
  afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

  it('does not expose or persist the API key in browser storage', async () => {
    const storage = vi.spyOn(Storage.prototype, 'setItem');
    render(<SettingsSection />);
    await screen.findByText('Подключений пока нет.');
    fireEvent.change(screen.getByLabelText('API key'), { target: { value: 'sensitive-test-value' } });
    fireEvent.click(screen.getByRole('button', { name: 'Добавить подключение' }));
    await waitFor(() => expect(screen.getByLabelText('API key')).toHaveValue(''));
    expect(storage).not.toHaveBeenCalled();
    expect(document.body.textContent).not.toContain('sensitive-test-value');
    const calls = vi.mocked(fetch).mock.calls;
    expect(calls.some(([url, init]) => url === '/api/v1/providers'
      && (init as RequestInit | undefined)?.method === 'POST')).toBe(true);
    storage.mockRestore();
  });

  it('does not call completion without explicit user action', async () => {
    render(<SettingsSection />);
    await screen.findByText('Подключений пока нет.');
    expect(vi.mocked(fetch).mock.calls.some(([url]) => url === '/api/v1/completions')).toBe(false);
  });
});
