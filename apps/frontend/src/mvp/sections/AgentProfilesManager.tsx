/** Profile authoring is not worker registration. No provider completion is
 * sent from this screen and no raw credentials are read from the backend. */
import { useEffect, useRef, useState, type FormEvent } from 'react';
import { Button, Card, Field, Input, Select, Textarea } from '../../components';

export type AgentProfile = {
  id: string; name: string; role: string; version: number;
  system_prompt?: string | null;
  default_model_profile_id: string | null;
  default_tool_policy_id?: string | null;
  max_concurrency?: number;
  supported_stages?: string[];
};
export type AgentModel = { id: string; name: string; model_id: string; provider_id: string };
type Policy = {
  id: string; name: string; version: number;
  permissions: Record<string, string[]>;
};
type Page<T> = { items: T[]; next_cursor?: string | null };
const roles = ['researcher', 'architect', 'developer', 'tester', 'reviewer', 'security', 'release-prep'] as const;
const independentRoles = new Set<string>(['tester', 'reviewer', 'security']);
const restrictedPath = (value: string): boolean =>
  /^\/srv\/maw\/workspace\/[a-zA-Z0-9_.-]+(?:\/[a-zA-Z0-9_.-]+)*\/\*\*$/.test(value) &&
  !value.split('/').includes('..');

function policyEligible(role: string, policy: Policy): boolean {
  if (!independentRoles.has(role)) return true;
  // The UI must never silently assign write/shell/network capabilities to a
  // nominally independent checker. Backend policy remains the authority.
  return ['fs_write', 'git', 'shell', 'network'].every(
    kind => !(policy.permissions?.[kind] ?? []).length,
  );
}
function apiError(error: unknown): string {
  const status = error instanceof ProfileHttpError ? error.status : 0;
  if (status === 409) return 'Версия профиля изменена другим пользователем. Обновите страницу и повторите.';
  if (status === 422 || status === 400) return 'Настройки не приняты сервером. Проверьте ссылки, роль и ограничения.';
  if (status === 401 || status === 403) return 'Недостаточно прав для изменения профилей.';
  return status ? 'Сервис профилей вернул HTTP ' + status + '.' : 'Сервис профилей недоступен.';
}
class ProfileHttpError extends Error {
  constructor(readonly status: number) { super('HTTP ' + status); }
}
async function request<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetch(url, {
    ...init, credentials: 'same-origin',
    headers: { 'Content-Type': 'application/json', ...init?.headers },
  });
  if (!response.ok) throw new ProfileHttpError(response.status);
  return response.json() as Promise<T>;
}
type Props = {
  agents: AgentProfile[];
  models: AgentModel[];
  onSaved: (agent: AgentProfile) => void;
};

export default function AgentProfilesManager({ agents, models, onSaved }: Props) {
  const [policies, setPolicies] = useState<Policy[]>([]);
  const policyMutation = useRef(0);
  const [policyLoadError, setPolicyLoadError] = useState(false);
  const [policyName, setPolicyName] = useState('');
  const [readPath, setReadPath] = useState('');
  const [writePath, setWritePath] = useState('');
  const [name, setName] = useState('');
  const [role, setRole] = useState<string>('developer');
  const [prompt, setPrompt] = useState('');
  const [model, setModel] = useState('');
  const [policy, setPolicy] = useState('');
  const [concurrency, setConcurrency] = useState(1);
  const [editing, setEditing] = useState<AgentProfile | null>(null);
  const [busy, setBusy] = useState(false);
  const [status, setStatus] = useState('');

  useEffect(() => {
    let mounted = true;
    const startedAtMutation = policyMutation.current;
    async function loadPolicies() {
      const all: Policy[] = [];
      const visited = new Set<string>();
      let cursor: string | null = null;
      // Do not silently hide the policy referenced by an older profile.
      // Cap untrusted pagination, reject cycles and expose no partial catalog.
      for (let page = 0; page < 100; page++) {
        const url = cursor === null ? '/api/v1/tool-policies'
          : '/api/v1/tool-policies?after=' + encodeURIComponent(cursor);
        const result: Page<Policy> = await request<Page<Policy>>(url);
        if (!Array.isArray(result.items) || result.items.length > 100 ||
            result.items.some(item => !item || typeof item.id !== 'string')) {
          throw new Error('Invalid tool policy page');
        }
        all.push(...result.items);
        const next = result.next_cursor;
        if (next == null) {
          if (mounted) {
            // A policy may be created while the paged GET is pending.
            // Keep that confirmed POST result instead of reviving an older
            // inventory which does not contain it yet.
            setPolicies(current => startedAtMutation === policyMutation.current
              ? all
              : [...all, ...current.filter(item => !all.some(p => p.id === item.id))]);
            setPolicyLoadError(false);
          }
          return;
        }
        if (typeof next !== 'string' || !next || next.length > 512 ||
            visited.has(next)) throw new Error('Invalid tool policy cursor');
        visited.add(next);
        cursor = next;
      }
      throw new Error('Tool policy pagination limit exceeded');
    }
    void loadPolicies().catch(() => {
      if (mounted) {
        setPolicies([]);
        setPolicyLoadError(true);
      }
    });
    return () => { mounted = false; };
  }, []);

  const eligible = policies.filter(item => policyEligible(role, item));
  const selectedPolicy = eligible.find(item => item.id === policy);

  function resetForm() {
    setEditing(null);
    setName('');
    setRole('developer');
    setPrompt('');
    setModel('');
    setPolicy('');
    setConcurrency(1);
  }

  function beginEdit(agent: AgentProfile, duplicate: boolean) {
    setEditing(duplicate ? null : agent);
    setName(agent.name + (duplicate ? ' — копия' : ''));
    setRole(agent.role);
    setPrompt(agent.system_prompt ?? '');
    setModel(agent.default_model_profile_id ?? '');
    setPolicy(agent.default_tool_policy_id ?? '');
    setConcurrency(agent.max_concurrency ?? 1);
    setStatus('');
  }

  async function createPolicy(event: FormEvent) {
    event.preventDefault();
    if (!policyName.trim()) return;
    if ((readPath && !restrictedPath(readPath)) ||
        (writePath && !restrictedPath(writePath))) {
      setStatus('Путь должен иметь вид /srv/maw/workspace/project/** без ".." и без глобальных разрешений.');
      return;
    }
    if (independentRoles.has(role) && writePath) {
      setStatus('Независимым tester/reviewer/security запрещена политика записи.');
      return;
    }
    setBusy(true);
    setStatus('');
    try {
      const created = await request<Policy>('/api/v1/tool-policies', {
        method: 'POST',
        body: JSON.stringify({
          name: policyName.trim(),
          // Explicit deny-all for unspecified tool kinds.
          permissions: {
            fs_read: readPath ? [readPath] : [],
            fs_write: writePath ? [writePath] : [],
            git: [], shell: [], network: [],
          },
          is_default: false,
        }),
      });
      policyMutation.current++;
      setPolicies(current => [...current.filter(p => p.id !== created.id), created]);
      setPolicy(created.id);
      setPolicyName('');
      setReadPath('');
      setWritePath('');
      setStatus('Политика сохранена. Доступ к инструментам ещё зависит от отдельного gateway allowlist.');
    } catch (error) {
      setStatus(apiError(error));
    } finally {
      setBusy(false);
    }
  }

  async function saveProfile(event: FormEvent) {
    event.preventDefault();
    if (!name.trim() || !prompt.trim() || prompt.length > 4096 ||
        !model || !selectedPolicy ||
        !Number.isInteger(concurrency) || concurrency < 1 || concurrency > 100) {
      setStatus('Укажите имя, инструкции 1–4096 символов, сохранённую модель, допустимую политику и concurrency 1–100.');
      return;
    }
    setBusy(true);
    setStatus('');
    const payload = {
      name: name.trim(), role, system_prompt: prompt.trim(),
      default_model_profile_id: model,
      default_tool_policy_id: selectedPolicy.id,
      max_concurrency: concurrency,
      supported_stages: [role],
    };
    try {
      const saved = editing
        ? await request<AgentProfile>(
          '/api/v1/agents/definitions/' + encodeURIComponent(editing.id),
          { method: 'PATCH', body: JSON.stringify({ ...payload, version: editing.version }) },
        )
        : await request<AgentProfile>('/api/v1/agents/definitions', {
          method: 'POST', body: JSON.stringify(payload),
        });
      onSaved(saved);
      resetForm();
      setStatus('Профиль сохранён и доступен в редакторе. Это не запуск native worker.');
    } catch (error) {
      setStatus(apiError(error));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div style={{ display: 'grid', gap: 'var(--space-4)' }}>
      <Card title="Профили AI-агентов">
        <p>Определение роли — это не зарегистрированный worker. Настройки будут
          применены при запуске только после server preflight и проверки native
          worker policy. Tester, reviewer и security должны быть независимыми.</p>
        {agents.length === 0 ? <p>Профилей пока нет.</p> : (
          <ul data-testid="saved-agent-profiles">
            {agents.map(agent => (
              <li key={agent.id}>
                <strong>{agent.name}</strong> — {agent.role} (v{agent.version})
                {' '}<Button size="sm" variant="secondary" onClick={() => beginEdit(agent, false)}>Изменить</Button>
                {' '}<Button size="sm" variant="secondary" onClick={() => beginEdit(agent, true)}>Копировать</Button>
              </li>
            ))}
          </ul>
        )}
      </Card>
      <Card title={editing ? 'Изменить профиль агента' : 'Создать профиль агента'}>
        <form onSubmit={saveProfile}>
          <Field label="Имя профиля" required>{({ id, ...aria }) =>
            <Input id={id} {...aria} value={name} onChange={event => setName(event.target.value)} maxLength={255} required />}</Field>
          <Field label="Роль агента" required>{({ id, ...aria }) =>
            <Select id={id} {...aria} value={role} onChange={event => {
              setRole(event.target.value); setPolicy('');
            }}>{roles.map(item => <option key={item} value={item}>{item}</option>)}</Select>}</Field>
          <Field label="System instructions" required>{({ id, ...aria }) =>
            <Textarea id={id} {...aria} rows={4} maxLength={4096} required value={prompt}
              onChange={event => setPrompt(event.target.value)} />}</Field>
          <Field label="Модель профиля" required>{({ id, ...aria }) =>
            <Select id={id} {...aria} value={model} onChange={event => setModel(event.target.value)}>
              <option value="">Выберите сохранённую модель</option>
              {models.map(item => <option key={item.id} value={item.id}>{item.name} — {item.model_id}</option>)}
            </Select>}</Field>
          <Field label="Tool policy" required>{({ id, ...aria }) =>
            <Select id={id} {...aria} value={policy} onChange={event => setPolicy(event.target.value)}>
              <option value="">Выберите разрешённую политику</option>
              {eligible.map(item => <option key={item.id} value={item.id}>{item.name}</option>)}
            </Select>}</Field>
          {policyLoadError ? <p role="alert">Список tool-policy недоступен. Создание профиля без политики запрещено.</p> : null}
          <Field label="Максимум параллельных задач">{({ id, ...aria }) =>
            <Input id={id} {...aria} type="number" min={1} max={100} value={concurrency}
              onChange={event => setConcurrency(Number(event.target.value))} />}</Field>
          <Button type="submit" disabled={busy || !name.trim() || !prompt.trim() ||
            prompt.length > 4096 || !model || !selectedPolicy || policyLoadError}>
            {editing ? 'Сохранить изменения профиля' : 'Создать профиль'}
          </Button>
          {editing ? <Button variant="secondary" onClick={resetForm}>Отмена изменений</Button> : null}
        </form>
      </Card>
      <Card title="Создать ограниченную tool-policy">
        <p>Без перечисленных разрешений действует deny-all. Шаблоны не дают shell,
          git или network доступа. Native worker дополнительно ограничен
          доверенным gateway allowlist.</p>
        <form onSubmit={createPolicy}>
          <Field label="Имя политики" required>{({ id, ...aria }) =>
            <Input id={id} {...aria} value={policyName} onChange={event => setPolicyName(event.target.value)} required />}</Field>
          <Field label="Разрешённое чтение (необязательно)">{({ id, ...aria }) =>
            <Input id={id} {...aria} placeholder="/srv/maw/workspace/project/**" value={readPath}
              onChange={event => setReadPath(event.target.value)} />}</Field>
          <Field label="Разрешённая запись (только developer)">{({ id, ...aria }) =>
            <Input id={id} {...aria} placeholder="/srv/maw/workspace/project/out/**" value={writePath}
              disabled={independentRoles.has(role)} onChange={event => setWritePath(event.target.value)} />}</Field>
          <Button type="submit" disabled={busy || !policyName.trim()}>Создать tool-policy</Button>
        </form>
      </Card>
      {status ? <p role="status" data-testid="agent-profile-status">{status}</p> : null}
    </div>
  );
}
