/** Server-owned agent profiles. Native leased-worker capacity is NOT controlled
 * by these records; permissions and budgets require control-plane enforcement.
 */
import { useCallback, useEffect, useState, type FormEvent } from 'react';
import { Button, Card, Field, Input, Select, Textarea } from '../components';
import { PageHeader } from '../patterns';

type Agent = {
  id: string; name: string; description?: string; system_prompt?: string;
  role: string; default_model_profile_id?: string | null; default_tool_policy_id?: string | null;
  max_concurrency: number; budget_limit?: number | null;
  supported_stages: string[]; skills: string[]; version: number;
};
type Model = { id: string; name: string; model_id: string };
type Policy = { id: string; name: string; permissions: Record<string, string[]> };
type Page<T> = { items: T[]; next_cursor?: string | null };
type AgentForm = {
  name: string; description: string; system_prompt: string; role: string;
  model: string; policy: string; maxConcurrency: string; budget: string; stages: string; skills: string;
};
const blank: AgentForm = { name: '', description: '', system_prompt: '', role: 'developer',
  model: '', policy: '', maxConcurrency: '1', budget: '', stages: 'implementation', skills: '' };
const ROLES = ['generalist', 'researcher', 'architect', 'developer', 'tester', 'reviewer', 'security', 'release'] as const;
const KINDS = ['fs_read', 'fs_write', 'git', 'shell', 'network'] as const;

async function request<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetch(url, { ...init,
    credentials: 'same-origin', headers: { 'Content-Type': 'application/json', ...init?.headers } });
  if (!response.ok) throw new Error(`HTTP ${response.status}: сервер отклонил изменение. Проверьте права, версию и ссылки.`);
  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
}

/** No silently truncated catalogs or duplicate cursors: fail closed. */
async function allPages<T>(path: string): Promise<T[]> {
  let cursor: string | null = null;
  const seen = new Set<string>();
  const items: T[] = [];
  for (let pageIndex = 0; pageIndex < 100; pageIndex += 1) {
    const url: string = path + '?limit=100' + (cursor ? '&after=' + encodeURIComponent(cursor) : '');
    const page: Page<T> = await request<Page<T>>(url);
    if (!Array.isArray(page.items)) throw new Error('Некорректный ответ списка');
    items.push(...page.items);
    if (!page.next_cursor) return items;
    if (seen.has(page.next_cursor)) throw new Error('Повторяющийся курсор списка');
    seen.add(page.next_cursor);
    cursor = page.next_cursor;
  }
  throw new Error('Каталог превышает безопасный лимит страниц');
}

function commaList(raw: string): string[] {
  return [...new Set(raw.split(',').map((value) => value.trim()).filter(Boolean))];
}

export default function AgentProfilesPage() {
  const [agents, setAgents] = useState<Agent[]>([]);
  const [models, setModels] = useState<Model[]>([]);
  const [policies, setPolicies] = useState<Policy[]>([]);
  const [selected, setSelected] = useState<Agent | null>(null);
  const [form, setForm] = useState<AgentForm>(blank);
  const [policyName, setPolicyName] = useState('');
  const [permissionLines, setPermissionLines] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState('');

  const reload = useCallback(async () => {
    setLoading(true);
    try {
      const [a, m, p] = await Promise.all([
        allPages<Agent>('/api/v1/agents/definitions'),
        allPages<Model>('/api/v1/model-profiles'),
        allPages<Policy>('/api/v1/tool-policies'),
      ]);
      setAgents(a); setModels(m); setPolicies(p); setError(null);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Невозможно загрузить профили.');
    } finally { setLoading(false); }
  }, []);
  useEffect(() => { void reload(); }, [reload]);

  function edit(item: Agent) {
    setSelected(item);
    setForm({
      name: item.name, description: item.description ?? '', system_prompt: item.system_prompt ?? '',
      role: item.role, model: item.default_model_profile_id ?? '',
      policy: item.default_tool_policy_id ?? '', maxConcurrency: String(item.max_concurrency),
      budget: item.budget_limit == null ? '' : String(item.budget_limit),
      stages: (item.supported_stages ?? []).join(', '), skills: (item.skills ?? []).join(', '),
    });
    setError(null); setNotice('');
  }

  async function saveProfile(event: FormEvent) {
    event.preventDefault();
    if (busy) return;
    const count = Number(form.maxConcurrency);
    const budget = form.budget.trim() ? Number(form.budget) : null;
    const stages = commaList(form.stages);
    const skills = commaList(form.skills);
    if (!form.name.trim() || !form.model || !form.policy ||
        !Number.isInteger(count) || count < 1 || count > 100 ||
        (budget !== null && (!Number.isFinite(budget) || budget < 0 || budget > 1000000)) ||
        stages.length > 32 || skills.length > 32 ||
        [...stages, ...skills].some((value) => value.length > 64)) {
      setError('Заполните имя, модель и политику; проверьте бюджет, параллелизм и список навыков.');
      return;
    }
    setBusy(true); setError(null); setNotice('');
    try {
      const payload = {
        name: form.name.trim(), description: form.description.trim() || null,
        system_prompt: form.system_prompt.trim() || null, role: form.role,
        default_model_profile_id: form.model, default_tool_policy_id: form.policy,
        max_concurrency: count, budget_limit: budget,
        supported_stages: stages, skills,
      };
      const saved = selected
        ? await request<Agent>(`/api/v1/agents/definitions/${encodeURIComponent(selected.id)}`, {
            method: 'PATCH', body: JSON.stringify({ ...payload, version: selected.version }),
          })
        : await request<Agent>('/api/v1/agents/definitions', {
            method: 'POST', body: JSON.stringify(payload),
          });
      setSelected(saved); setNotice('Профиль сохранён в agent-management.');
      await reload();
      edit(saved);
      setNotice('Профиль сохранён в agent-management.');
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Ошибка сохранения.');
    } finally { setBusy(false); }
  }

  async function savePolicy(event: FormEvent) {
    event.preventDefault();
    if (busy || !policyName.trim()) return;
    const permissions: Record<string, string[]> = {};
    for (const kind of KINDS) {
      const values = (permissionLines[kind] ?? '').split('\n').map((line) => line.trim()).filter(Boolean);
      if (values.some((line) => line === '*' || line === '**')) {
        setError('Не используйте глобальные wildcard-права. Укажите ограниченные ресурсы.');
        return;
      }
      permissions[kind] = values;
    }
    setBusy(true); setError(null);
    try {
      const policy = await request<Policy>('/api/v1/tool-policies', {
        method: 'POST', body: JSON.stringify({ name: policyName.trim(), permissions }),
      });
      setPolicyName(''); setPermissionLines({});
      await reload();
      setForm((prev) => ({ ...prev, policy: policy.id }));
      setNotice('Политика инструментов сохранена с явным allowlist; остальные операции запрещены.');
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Ошибка сохранения политики.');
    } finally { setBusy(false); }
  }

  return (
    <div>
      <PageHeader title="Профили агентов" subtitle="Определения AI-ролей, модели, инструкции и политики инструментов." />
      <p>Профиль описывает логического агента, а не работающий leased worker. Настройка не делает платного вызова и не запускает задачи.</p>
      <p><strong>Важно:</strong> max concurrency и бюджет сохраняются как данные профиля, но до контроля native-dispatch эти значения не являются гарантированными лимитами расходов. Права инструментов дополнительно проверяет backend/gateway.</p>
      {loading ? <p role="status">Загрузка…</p> : null}
      {error ? <p role="alert" style={{ color: 'var(--color-error)' }}>{error}</p> : null}
      {notice ? <p role="status">{notice}</p> : null}
      <div style={{ display: 'grid', gridTemplateColumns: 'minmax(240px, 1fr) minmax(320px, 2fr)', gap: 16 }}>
        <Card title="Сохранённые профили">
          <Button variant="secondary" onClick={() => { setSelected(null); setForm(blank); setError(null); }}>Новый профиль</Button>
          <p>{agents.length ? 'Выберите профиль для изменения настроек.' : 'Профилей нет. Создайте первый.'}</p>
          <ul style={{ paddingInlineStart: 20 }}>
            {agents.map((agent) => <li key={agent.id}>
              <button type="button" onClick={() => edit(agent)} aria-current={selected?.id === agent.id ? 'true' : undefined}>
                {agent.name} · {agent.role} · v{agent.version}
              </button>
            </li>)}
          </ul>
        </Card>
        <Card title={selected ? 'Изменить профиль' : 'Создать профиль'}>
          <form onSubmit={saveProfile}>
            <Field label="Название" required>{({ id, ...aria }) =>
              <Input id={id} value={form.name} onChange={(e) => setForm((v) => ({ ...v, name: e.target.value }))} required {...aria} />}</Field>
            <Field label="Описание">{({ id, ...aria }) =>
              <Input id={id} value={form.description} onChange={(e) => setForm((v) => ({ ...v, description: e.target.value }))} {...aria} />}</Field>
            <Field label="Роль">{({ id, ...aria }) =>
              <Select id={id} value={form.role} onChange={(e) => setForm((v) => ({ ...v, role: e.target.value }))} {...aria}>
                {ROLES.map((role) => <option key={role} value={role}>{role}</option>)}
              </Select>}</Field>
            <Field label="Системные инструкции" hint="Применение инструкций зависит от исполнительного runtime; не вводите секреты.">
              {({ id, ...aria }) => <Textarea id={id} value={form.system_prompt} rows={4}
                onChange={(e) => setForm((v) => ({ ...v, system_prompt: e.target.value }))} {...aria} />}</Field>
            <Field label="Профиль модели" required>{({ id, ...aria }) =>
              <Select id={id} value={form.model} onChange={(e) => setForm((v) => ({ ...v, model: e.target.value }))} {...aria}>
                <option value="">Выберите модель в «Настройках»</option>
                {models.map((model) => <option key={model.id} value={model.id}>{model.name} — {model.model_id}</option>)}
              </Select>}</Field>
            <Field label="Политика инструментов" required>{({ id, ...aria }) =>
              <Select id={id} value={form.policy} onChange={(e) => setForm((v) => ({ ...v, policy: e.target.value }))} {...aria}>
                <option value="">Выберите ограниченную политику</option>
                {policies.map((policy) => <option key={policy.id} value={policy.id}>{policy.name}</option>)}
              </Select>}</Field>
            <Field label="Максимальный параллелизм (конфигурация)">
              {({ id, ...aria }) => <Input id={id} type="number" min={1} max={100} value={form.maxConcurrency}
                onChange={(e) => setForm((v) => ({ ...v, maxConcurrency: e.target.value }))} {...aria} />}</Field>
            <Field label="Бюджет (метаданные, пока без enforcement)">
              {({ id, ...aria }) => <Input id={id} type="number" min={0} max={1000000} step="0.01" value={form.budget}
                onChange={(e) => setForm((v) => ({ ...v, budget: e.target.value }))} {...aria} />}</Field>
            <Field label="Стадии (через запятую)">
              {({ id, ...aria }) => <Input id={id} value={form.stages}
                onChange={(e) => setForm((v) => ({ ...v, stages: e.target.value }))} {...aria} />}</Field>
            <Field label="Навыки (через запятую)">
              {({ id, ...aria }) => <Input id={id} value={form.skills}
                onChange={(e) => setForm((v) => ({ ...v, skills: e.target.value }))} {...aria} />}</Field>
            <Button type="submit" disabled={busy || !form.name.trim() || !form.model || !form.policy}>
              {busy ? 'Сохранение…' : selected ? 'Сохранить новую версию профиля' : 'Создать профиль'}
            </Button>
          </form>
        </Card>
      </div>
      <div style={{ marginTop: 20 }}>
        <Card title="Создать allowlist политику инструментов">
          <p>Разрешены только указанные действия/пути. Пустые поля означают запрет. Существующие политики не изменяются.</p>
          <form onSubmit={savePolicy}>
            <Field label="Название политики" required>{({ id, ...aria }) =>
              <Input id={id} value={policyName} onChange={(e) => setPolicyName(e.target.value)} {...aria} />}</Field>
            {KINDS.map((kind) => (
              <Field key={kind} label={kind} hint="Одна разрешённая команда, операция или ограниченный шаблон на строку.">
                {({ id, ...aria }) => <Textarea id={id} rows={2} value={permissionLines[kind] ?? ''}
                  onChange={(e) => setPermissionLines((v) => ({ ...v, [kind]: e.target.value }))} {...aria} />}
              </Field>
            ))}
            <Button type="submit" disabled={busy || !policyName.trim()}>Создать политику</Button>
          </form>
        </Card>
      </div>
    </div>
  );
}
