import { useCallback, useEffect, useState, type FormEvent } from 'react';

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
  if (!response.ok) throw new Error(`Ошибка API (HTTP ${response.status}). Проверьте доступность agent-management и права доступа.`);
  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
}

const fieldStyle = { display: 'block', width: '100%', padding: 9, boxSizing: 'border-box' as const, marginBottom: 12 };
const buttonStyle = { padding: '9px 14px', cursor: 'pointer', marginRight: 8 };

export default function SettingsSection() {
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
    ]).then(([p,m,a]) => { if (mounted) { setProviders(p.items); setModels(m.items); setAgents(a.items); } })
      .catch(() => { if (mounted) setMessage('Не удалось загрузить настройки. Проверьте agent-management.'); });
    return () => { mounted = false; };
  }, []);

  async function saveProvider(event: FormEvent) {
    event.preventDefault();
    if (!apiKey.trim()) { setMessage('Укажите API key.'); return; }
    setBusy(true); setMessage('');
    try {
      await request('/api/v1/providers', {
        method: 'POST',
        body: JSON.stringify({ name: name.trim(), type: 'openrouter', is_active: true,
          auth_config: { api_key: apiKey } }),
      });
      setApiKey('');
      await load();
      setMessage('Подключение сохранено в backend. Ключ не возвращается в интерфейс.');
    } catch { setMessage('Сохранить подключение не удалось. Проверьте права и настройки шифрования сервера.'); }
    finally { setBusy(false); }
  }

  async function rotateKey(id: string, version: number) {
    if (!apiKey.trim()) { setMessage('Введите новый ключ для замены.'); return; }
    setBusy(true); setMessage('');
    try {
      await request(`/api/v1/providers/${encodeURIComponent(id)}`, {
        method: 'PATCH',
        body: JSON.stringify({ auth_config: { api_key: apiKey }, version }),
      });
      setApiKey('');
      await load();
      setMessage('Ключ заменён. Старый ключ недоступен в интерфейсе.');
    } catch { setMessage('Не удалось заменить ключ.'); }
    finally { setBusy(false); }
  }

  async function toggleProvider(provider: Provider) {
    setBusy(true); setMessage('');
    try {
      await request(`/api/v1/providers/${encodeURIComponent(provider.id)}`, {
        method: 'PATCH',
        body: JSON.stringify({ is_active: !provider.is_active, version: provider.version }),
      });
      await load();
      setMessage('Состояние подключения обновлено.');
    } catch { setMessage('Не удалось изменить состояние подключения.'); }
    finally { setBusy(false); }
  }

  async function testConnection() {
    const chosen = models.find(model => model.id === diagnosticModelId);
    if (!chosen) { setMessage('Для проверки выберите сохранённую модель.'); return; }
    if (!window.confirm('Проверка отправит короткий запрос в OpenRouter и может быть платной. Продолжить?')) return;
    setBusy(true); setMessage('');
    try {
      await request('/api/v1/completions', {
        method: 'POST',
        body: JSON.stringify({
          provider_id: chosen.provider_id, model_profile_id: chosen.id,
          messages: [{ role: 'user', content: 'Reply with OK.' }], max_tokens: 8,
        }),
      });
      setMessage('Проверка подключения прошла успешно.');
    } catch {
      setMessage('Проверка подключения не пройдена (ключ, модель, квота, сеть или timeout). Проверьте backend-журнал.');
    } finally { setBusy(false); }
  }

  async function removeProvider(provider: Provider) {
    if (!window.confirm('Удалить подключение? Связанные модели и агенты могут перестать работать.')) return;
    setBusy(true); setMessage('');
    try {
      await request(`/api/v1/providers/${encodeURIComponent(provider.id)}`, { method: 'DELETE' });
      await load();
      setMessage('Подключение удалено.');
    } catch { setMessage('Удалить подключение не удалось. Проверьте зависимости и права администратора.'); }
    finally { setBusy(false); }
  }

  async function removeModel(model: Model) {
    if (!window.confirm('Удалить профиль модели? Проверьте привязанные роли агентов.')) return;
    setBusy(true); setMessage('');
    try {
      await request(`/api/v1/model-profiles/${encodeURIComponent(model.id)}`, { method: 'DELETE' });
      await load();
      setMessage('Профиль модели удалён.');
    } catch { setMessage('Профиль не удалён. Проверьте зависимости и права администратора.'); }
    finally { setBusy(false); }
  }

  async function makeDefault(model: Model) {
    setBusy(true); setMessage('');
    try {
      await request(`/api/v1/model-profiles/${encodeURIComponent(model.id)}`, {
        method: 'PATCH',
        body: JSON.stringify({ is_default: true, version: model.version }),
      });
      await load();
      setMessage('Модель установлена по умолчанию.');
    } catch { setMessage('Не удалось установить модель по умолчанию.'); }
    finally { setBusy(false); }
  }

  async function assignModel(agent: AgentDefinition, profileId: string) {
    setBusy(true); setMessage('');
    try {
      await request(`/api/v1/agents/definitions/${encodeURIComponent(agent.id)}`, {
        method: 'PATCH',
        body: JSON.stringify({ default_model_profile_id: profileId, version: agent.version }),
      });
      await load();
      setMessage('Профиль модели назначен роли агента.');
    } catch { setMessage('Не удалось назначить модель агенту.'); }
    finally { setBusy(false); }
  }

  async function saveModel(event: FormEvent) {
    event.preventDefault();
    if (!providerId || !modelId.trim()) { setMessage('Выберите провайдера и идентификатор модели.'); return; }
    setBusy(true); setMessage('');
    try {
      await request('/api/v1/model-profiles', {
        method: 'POST',
        body: JSON.stringify({
          provider_id: providerId, name: modelName.trim() || modelId.trim(),
          model_id: modelId.trim(), is_default: models.length === 0,
          parameters: { temperature: Number(temperature), max_tokens: Number(maxTokens) },
        }),
      });
      setModelId(''); setModelName('');
      await load();
      setMessage('Профиль модели сохранён.');
    } catch { setMessage('Не удалось сохранить модель.'); }
    finally { setBusy(false); }
  }

  return <section style={{ maxWidth: 860, margin: '0 auto' }}>
    <h2>Настройки проекта</h2>
    <p>Подключения и модели хранятся в agent-management. Ключ API отправляется только в backend и никогда не показывается повторно.</p>
    {message && <p role="status" style={{ background: '#eef3fb', padding: 12 }}>{message}</p>}
    <div style={{ background: '#fff', padding: 20, border: '1px solid #ddd', borderRadius: 8, marginBottom: 16 }}>
      <h3>OpenRouter — подключение</h3>
      <form onSubmit={saveProvider}>
        <label>Имя подключения<input aria-label="Имя подключения" style={fieldStyle} maxLength={255} value={name} onChange={e => setName(e.target.value)} required /></label>
        <label>API key (новый или для замены)<input aria-label="API key" style={fieldStyle} type="password" autoComplete="new-password" value={apiKey} onChange={e => setApiKey(e.target.value)} /></label>
        <button style={buttonStyle} type="submit" disabled={busy || !name.trim() || !apiKey.trim()}>Добавить подключение</button>
      </form>
      <h4>Сохранённые подключения</h4>
      {providers.length === 0 ? <p>Подключений пока нет.</p> : <ul>
        {providers.map(p => <li key={p.id} style={{ marginBottom: 12 }}>
          <strong>{p.name}</strong> ({p.type}, {p.is_active ? 'включён' : 'выключен'})
          <div>
            <button style={buttonStyle} disabled={busy} onClick={() => toggleProvider(p)}>{p.is_active ? 'Отключить' : 'Включить'}</button>
            {p.type === 'openrouter' && <button style={buttonStyle} disabled={busy || !apiKey.trim()} onClick={() => rotateKey(p.id, p.version)}>Заменить ключ из поля выше</button>}
            <button style={buttonStyle} type="button" disabled={busy} onClick={() => removeProvider(p)}>Удалить</button>
          </div>
        </li>)}
      </ul>}
    </div>
    <div style={{ background: '#fff', padding: 20, border: '1px solid #ddd', borderRadius: 8 }}>
      <h3>Профили моделей</h3>
      <form onSubmit={saveModel}>
        <label>Подключение<select aria-label="Подключение" style={fieldStyle} value={providerId} onChange={e => setProviderId(e.target.value)} required>
          <option value="">Выберите подключение</option>
          {providers.filter(p => p.is_active).map(p => <option key={p.id} value={p.id}>{p.name}</option>)}
        </select></label>
        <label>Model ID<input aria-label="Model ID" placeholder="provider/model" style={fieldStyle} value={modelId} onChange={e => setModelId(e.target.value)} maxLength={255} required /></label>
        <label>Имя профиля<input aria-label="Имя профиля" style={fieldStyle} value={modelName} onChange={e => setModelName(e.target.value)} maxLength={255} /></label>
        <label>Temperature (0–2)<input aria-label="Temperature" style={fieldStyle} type="number" min="0" max="2" step="0.1" value={temperature} onChange={e => setTemperature(e.target.value)} required /></label>
        <label>Max tokens (1–32768)<input aria-label="Max tokens" style={fieldStyle} type="number" min="1" max="32768" step="1" value={maxTokens} onChange={e => setMaxTokens(e.target.value)} required /></label>
        <button style={buttonStyle} type="submit" disabled={busy || !providerId || !modelId.trim() || !temperature || !maxTokens || Number(temperature) < 0 || Number(temperature) > 2 || Number(maxTokens) < 1 || Number(maxTokens) > 32768}>Сохранить модель</button>
      </form>
      <h4>Проверка подключения</h4>
      <p>Запускается только вручную, использует до 8 токенов ответа и может тарифицироваться провайдером.</p>
      <select aria-label="Модель для диагностики" style={fieldStyle} value={diagnosticModelId} onChange={e => setDiagnosticModelId(e.target.value)}>
        <option value="">Выберите сохранённую модель</option>
        {models.map(m => <option key={m.id} value={m.id}>{m.name} — {m.model_id}</option>)}
      </select>
      <button style={buttonStyle} type="button" disabled={busy || !models.some(m => m.id === diagnosticModelId)} onClick={testConnection}>Проверить подключение</button>
      <ul>{models.map(m => <li key={m.id} style={{ marginBottom: 8 }}>{m.name} — {m.model_id}{m.is_default ? ' (по умолчанию)' : ''}
        {!m.is_default && <button style={buttonStyle} type="button" disabled={busy} onClick={() => makeDefault(m)}>По умолчанию</button>}
        <button style={buttonStyle} type="button" disabled={busy} onClick={() => removeModel(m)}>Удалить профиль</button>
      </li>)}</ul>
    </div>
    <div style={{ background: '#fff', padding: 20, border: '1px solid #ddd', borderRadius: 8, marginTop: 16 }}>
      <h3>Модели агентов</h3>
      <p>Назначение сохраняется в существующем определении агента без копирования API key.</p>
      {agents.length === 0 ? <p>Определений агентов пока нет.</p> : agents.map(agent =>
        <label key={agent.id} style={{ display: 'block', marginBottom: 12 }}>
          {agent.name}
          <select aria-label={`Модель агента ${agent.name}`} style={fieldStyle} disabled={busy}
            value={agent.default_model_profile_id ?? ''}
            onChange={e => { if (e.target.value) void assignModel(agent, e.target.value); }}>
            <option value="">Не назначена</option>
            {models.map(model => <option key={model.id} value={model.id}>{model.name} — {model.model_id}</option>)}
          </select>
        </label>)}
    </div>
  </section>;
}
