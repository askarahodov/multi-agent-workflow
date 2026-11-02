/**
 * Settings layout (ADR-110 §3.6).
 *
 * Design-system implementation of the "Настройки" section: provider connections,
 * model profiles and per-agent model assignment, all rendered with the shared
 * token-driven components and consistent empty/loading/error handling. Secrets
 * (API keys) are only ever sent to the backend and are never persisted in the
 * browser — the key input is always cleared after a request.
 */

import { useCallback, useEffect, useState, type FormEvent } from 'react';

import { Button, Card, EmptyState, Field, Input, Select, StatusBadge, Tabs } from '../components';
import { PageHeader } from '../patterns';

type Provider = { id: string; name: string; type: string; is_active: boolean; version: number };
type Model = { id: string; provider_id: string; name: string; model_id: string; is_default: boolean; version: number };
type Page<T> = { items: T[] };
type AgentDefinition = { id: string; name: string; default_model_profile_id: string | null; version: number };

async function request<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetch(url, {
    ...init,
    headers: { 'Content-Type': 'application/json', ...init?.headers },
    credentials: 'same-origin',
  });
  if (!response.ok) {
    throw new Error(
      `Ошибка API (HTTP ${response.status}). Проверьте доступность agent-management и права доступа.`,
    );
  }
  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
}

export default function SettingsPage() {
  const [providers, setProviders] = useState<Provider[]>([]);
  const [models, setModels] = useState<Model[]>([]);
  const [agents, setAgents] = useState<AgentDefinition[]>([]);
  const [name, setName] = useState('OpenRouter');
  const [apiKey, setApiKey] = useState('');
  const [providerId, setProviderId] = useState('');
  const [modelId, setModelId] = useState('');
  const [diagnosticModelId, setDiagnosticModelId] = useState('');
  const [modelName, setModelName] = useState('');
  const [temperature, setTemperature] = useState('0.2');
  const [maxTokens, setMaxTokens] = useState('1024');
  const [message, setMessage] = useState('');
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    const [p, m, a] = await Promise.all([
      request<Page<Provider>>('/api/v1/providers'),
      request<Page<Model>>('/api/v1/model-profiles'),
      request<Page<AgentDefinition>>('/api/v1/agents/definitions'),
    ]);
    setProviders(p.items);
    setModels(m.items);
    setAgents(a.items);
  }, []);

  useEffect(() => {
    let mounted = true;
    Promise.all([
      request<Page<Provider>>('/api/v1/providers'),
      request<Page<Model>>('/api/v1/model-profiles'),
      request<Page<AgentDefinition>>('/api/v1/agents/definitions'),
    ])
      .then(([p, m, a]) => {
        if (mounted) {
          setProviders(p.items);
          setModels(m.items);
          setAgents(a.items);
        }
      })
      .catch(() => {
        if (mounted) setMessage('Не удалось загрузить настройки. Проверьте agent-management.');
      });
    return () => {
      mounted = false;
    };
  }, []);

  async function saveProvider(event: FormEvent) {
    event.preventDefault();
    if (!apiKey.trim()) {
      setMessage('Укажите API key.');
      return;
    }
    setBusy(true);
    setMessage('');
    try {
      await request('/api/v1/providers', {
        method: 'POST',
        body: JSON.stringify({
          name: name.trim(),
          type: 'openrouter',
          is_active: true,
          auth_config: { api_key: apiKey },
        }),
      });
      setApiKey('');
      await load();
      setMessage('Подключение сохранено в backend. Ключ не возвращается в интерфейс.');
    } catch {
      setMessage('Сохранить подключение не удалось. Проверьте права и настройки шифрования сервера.');
    } finally {
      setBusy(false);
    }
  }

  async function rotateKey(id: string, version: number) {
    if (!apiKey.trim()) {
      setMessage('Введите новый ключ для замены.');
      return;
    }
    setBusy(true);
    setMessage('');
    try {
      await request(`/api/v1/providers/${encodeURIComponent(id)}`, {
        method: 'PATCH',
        body: JSON.stringify({ auth_config: { api_key: apiKey }, version }),
      });
      setApiKey('');
      await load();
      setMessage('Ключ заменён. Старый ключ недоступен в интерфейсе.');
    } catch {
      setMessage('Не удалось заменить ключ.');
    } finally {
      setBusy(false);
    }
  }

  async function toggleProvider(provider: Provider) {
    setBusy(true);
    setMessage('');
    try {
      await request(`/api/v1/providers/${encodeURIComponent(provider.id)}`, {
        method: 'PATCH',
        body: JSON.stringify({ is_active: !provider.is_active, version: provider.version }),
      });
      await load();
      setMessage('Состояние подключения обновлено.');
    } catch {
      setMessage('Не удалось изменить состояние подключения.');
    } finally {
      setBusy(false);
    }
  }

  async function testConnection() {
    const chosen = models.find((model) => model.id === diagnosticModelId);
    if (!chosen) {
      setMessage('Для проверки выберите сохранённую модель.');
      return;
    }
    if (!window.confirm('Проверка отправит короткий запрос в OpenRouter и может быть платной. Продолжить?'))
      return;
    setBusy(true);
    setMessage('');
    try {
      await request('/api/v1/completions', {
        method: 'POST',
        body: JSON.stringify({
          provider_id: chosen.provider_id,
          model_profile_id: chosen.id,
          messages: [{ role: 'user', content: 'Reply with OK.' }],
          max_tokens: 8,
        }),
      });
      setMessage('Проверка подключения прошла успешно.');
    } catch {
      setMessage('Проверка подключения не пройдена (ключ, модель, квота, сеть или timeout). Проверьте backend-журнал.');
    } finally {
      setBusy(false);
    }
  }

  async function removeProvider(provider: Provider) {
    if (!window.confirm('Удалить подключение? Связанные модели и агенты могут перестать работать.')) return;
    setBusy(true);
    setMessage('');
    try {
      await request(`/api/v1/providers/${encodeURIComponent(provider.id)}`, { method: 'DELETE' });
      await load();
      setMessage('Подключение удалено.');
    } catch {
      setMessage('Удалить подключение не удалось. Проверьте зависимости и права администратора.');
    } finally {
      setBusy(false);
    }
  }

  async function removeModel(model: Model) {
    if (!window.confirm('Удалить профиль модели? Проверьте привязанные роли агентов.')) return;
    setBusy(true);
    setMessage('');
    try {
      await request(`/api/v1/model-profiles/${encodeURIComponent(model.id)}`, { method: 'DELETE' });
      await load();
      setMessage('Профиль модели удалён.');
    } catch {
      setMessage('Профиль не удалён. Проверьте зависимости и права администратора.');
    } finally {
      setBusy(false);
    }
  }

  async function makeDefault(model: Model) {
    setBusy(true);
    setMessage('');
    try {
      await request(`/api/v1/model-profiles/${encodeURIComponent(model.id)}`, {
        method: 'PATCH',
        body: JSON.stringify({ is_default: true, version: model.version }),
      });
      await load();
      setMessage('Модель установлена по умолчанию.');
    } catch {
      setMessage('Не удалось установить модель по умолчанию.');
    } finally {
      setBusy(false);
    }
  }

  async function assignModel(agent: AgentDefinition, profileId: string) {
    setBusy(true);
    setMessage('');
    try {
      await request(`/api/v1/agents/definitions/${encodeURIComponent(agent.id)}`, {
        method: 'PATCH',
        body: JSON.stringify({ default_model_profile_id: profileId, version: agent.version }),
      });
      await load();
      setMessage('Профиль модели назначен роли агента.');
    } catch {
      setMessage('Не удалось назначить модель агенту.');
    } finally {
      setBusy(false);
    }
  }

  async function saveModel(event: FormEvent) {
    event.preventDefault();
    if (!providerId || !modelId.trim()) {
      setMessage('Выберите провайдера и идентификатор модели.');
      return;
    }
    setBusy(true);
    setMessage('');
    try {
      await request('/api/v1/model-profiles', {
        method: 'POST',
        body: JSON.stringify({
          provider_id: providerId,
          name: modelName.trim() || modelId.trim(),
          model_id: modelId.trim(),
          is_default: models.length === 0,
          parameters: { temperature: Number(temperature), max_tokens: Number(maxTokens) },
        }),
      });
      setModelId('');
      setModelName('');
      await load();
      setMessage('Профиль модели сохранён.');
    } catch {
      setMessage('Не удалось сохранить модель.');
    } finally {
      setBusy(false);
    }
  }

  const connections = (
    <div style={{ display: 'grid', gap: 'var(--space-4)' }}>
      <Card title="OpenRouter — подключение">
        <p style={{ marginBlockStart: 0, color: 'var(--color-text-muted)', fontSize: 'var(--font-size-md)' }}>
          Подключения и модели хранятся в agent-management. Ключ API отправляется только в backend и никогда не
          показывается повторно.
        </p>
        <form onSubmit={saveProvider}>
          <Field label="Имя подключения" required>
            {({ id, ...aria }) => (
              <Input
                id={id}
                aria-label="Имя подключения"
                maxLength={255}
                value={name}
                onChange={(e) => setName(e.target.value)}
                required
                {...aria}
              />
            )}
          </Field>
          <Field label="API key (новый или для замены)">
            {({ id, ...aria }) => (
              <Input
                id={id}
                aria-label="API key"
                type="password"
                autoComplete="new-password"
                value={apiKey}
                onChange={(e) => setApiKey(e.target.value)}
                {...aria}
              />
            )}
          </Field>
          <Button type="submit" disabled={busy || !name.trim() || !apiKey.trim()}>
            Добавить подключение
          </Button>
        </form>
      </Card>

      <Card title="Сохранённые подключения">
        {providers.length === 0 ? (
          <EmptyState title="Подключений пока нет." icon="🔌" />
        ) : (
          <ul style={{ listStyle: 'none', margin: 0, padding: 0, display: 'grid', gap: 'var(--space-3)' }}>
            {providers.map((p) => (
              <li key={p.id} style={{ display: 'grid', gap: 'var(--space-2)' }}>
                <span style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-2)' }}>
                  <strong>{p.name}</strong> ({p.type})
                  <StatusBadge status={p.is_active ? 'ok' : 'idle'} label={p.is_active ? 'включён' : 'выключен'} />
                </span>
                <span style={{ display: 'flex', gap: 'var(--space-2)', flexWrap: 'wrap' }}>
                  <Button variant="secondary" size="sm" disabled={busy} onClick={() => toggleProvider(p)}>
                    {p.is_active ? 'Отключить' : 'Включить'}
                  </Button>
                  {p.type === 'openrouter' ? (
                    <Button
                      variant="secondary"
                      size="sm"
                      disabled={busy || !apiKey.trim()}
                      onClick={() => rotateKey(p.id, p.version)}
                    >
                      Заменить ключ из поля выше
                    </Button>
                  ) : null}
                  <Button variant="danger" size="sm" disabled={busy} onClick={() => removeProvider(p)}>
                    Удалить
                  </Button>
                </span>
              </li>
            ))}
          </ul>
        )}
      </Card>
    </div>
  );

  const modelProfiles = (
    <div style={{ display: 'grid', gap: 'var(--space-4)' }}>
      <Card title="Профили моделей">
        <form onSubmit={saveModel}>
          <Field label="Подключение" required>
            {({ id, ...aria }) => (
              <Select id={id} aria-label="Подключение" value={providerId} onChange={(e) => setProviderId(e.target.value)} required {...aria}>
                <option value="">Выберите подключение</option>
                {providers.filter((p) => p.is_active).map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.name}
                  </option>
                ))}
              </Select>
            )}
          </Field>
          <Field label="Model ID" required>
            {({ id, ...aria }) => (
              <Input
                id={id}
                aria-label="Model ID"
                placeholder="provider/model"
                value={modelId}
                onChange={(e) => setModelId(e.target.value)}
                maxLength={255}
                required
                {...aria}
              />
            )}
          </Field>
          <Field label="Имя профиля">
            {({ id, ...aria }) => (
              <Input id={id} aria-label="Имя профиля" value={modelName} onChange={(e) => setModelName(e.target.value)} maxLength={255} {...aria} />
            )}
          </Field>
          <Field label="Temperature (0–2)" required>
            {({ id, ...aria }) => (
              <Input
                id={id}
                aria-label="Temperature"
                type="number"
                min="0"
                max="2"
                step="0.1"
                value={temperature}
                onChange={(e) => setTemperature(e.target.value)}
                required
                {...aria}
              />
            )}
          </Field>
          <Field label="Max tokens (1–32768)" required>
            {({ id, ...aria }) => (
              <Input
                id={id}
                aria-label="Max tokens"
                type="number"
                min="1"
                max="32768"
                step="1"
                value={maxTokens}
                onChange={(e) => setMaxTokens(e.target.value)}
                required
                {...aria}
              />
            )}
          </Field>
          <Button
            type="submit"
            disabled={
              busy ||
              !providerId ||
              !modelId.trim() ||
              !temperature ||
              !maxTokens ||
              Number(temperature) < 0 ||
              Number(temperature) > 2 ||
              Number(maxTokens) < 1 ||
              Number(maxTokens) > 32768
            }
          >
            Сохранить модель
          </Button>
        </form>
      </Card>

      <Card title="Проверка подключения">
        <p style={{ marginBlockStart: 0, color: 'var(--color-text-muted)', fontSize: 'var(--font-size-md)' }}>
          Запускается только вручную, использует до 8 токенов ответа и может тарифицироваться провайдером.
        </p>
        <Field label="Модель для диагностики">
          {({ id, ...aria }) => (
            <Select
              id={id}
              aria-label="Модель для диагностики"
              value={diagnosticModelId}
              onChange={(e) => setDiagnosticModelId(e.target.value)}
              {...aria}
            >
              <option value="">Выберите сохранённую модель</option>
              {models.map((m) => (
                <option key={m.id} value={m.id}>
                  {m.name} — {m.model_id}
                </option>
              ))}
            </Select>
          )}
        </Field>
        <Button
          variant="secondary"
          disabled={busy || !models.some((m) => m.id === diagnosticModelId)}
          onClick={testConnection}
        >
          Проверить подключение
        </Button>
        <ul style={{ listStyle: 'none', margin: 'var(--space-3) 0 0', padding: 0, display: 'grid', gap: 'var(--space-2)' }}>
          {models.map((m) => (
            <li key={m.id} style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-2)', flexWrap: 'wrap' }}>
              <span>
                {m.name} — {m.model_id}
                {m.is_default ? ' (по умолчанию)' : ''}
              </span>
              {!m.is_default ? (
                <Button variant="secondary" size="sm" disabled={busy} onClick={() => makeDefault(m)}>
                  По умолчанию
                </Button>
              ) : null}
              <Button variant="danger" size="sm" disabled={busy} onClick={() => removeModel(m)}>
                Удалить профиль
              </Button>
            </li>
          ))}
        </ul>
      </Card>
    </div>
  );

  const agentRoles = (
    <Card title="Модели агентов">
      <p style={{ marginBlockStart: 0, color: 'var(--color-text-muted)', fontSize: 'var(--font-size-md)' }}>
        Назначение сохраняется в существующем определении агента без копирования API key.
      </p>
      {agents.length === 0 ? (
        <EmptyState title="Определений агентов пока нет." icon="🤖" />
      ) : (
        agents.map((agent) => (
          <Field key={agent.id} label={agent.name}>
            {({ id, ...aria }) => (
              <Select
                id={id}
                aria-label={`Модель агента ${agent.name}`}
                disabled={busy}
                value={agent.default_model_profile_id ?? ''}
                onChange={(e) => {
                  if (e.target.value) void assignModel(agent, e.target.value);
                }}
                {...aria}
              >
                <option value="">Не назначена</option>
                {models.map((model) => (
                  <option key={model.id} value={model.id}>
                    {model.name} — {model.model_id}
                  </option>
                ))}
              </Select>
            )}
          </Field>
        ))
      )}
    </Card>
  );

  return (
    <div>
      <PageHeader
        title="Настройки проекта"
        subtitle="Подключения, модели и определения агентов."
        breadcrumbs={[{ label: 'Платформа' }, { label: 'Настройки' }]}
      />
      {message ? (
        <p
          role="status"
          data-testid="settings-status"
          style={{
            background: 'var(--color-primary-weak)',
            padding: 'var(--space-3)',
            borderRadius: 'var(--radius-md)',
            marginBlockEnd: 'var(--space-4)',
          }}
        >
          {message}
        </p>
      ) : null}
      <Tabs
        label="Настройки"
        items={[
          { id: 'connections', label: 'Подключения', content: connections },
          { id: 'models', label: 'Модели', content: modelProfiles },
          { id: 'roles', label: 'Роли агентов', content: agentRoles },
        ]}
      />
    </div>
  );
}
