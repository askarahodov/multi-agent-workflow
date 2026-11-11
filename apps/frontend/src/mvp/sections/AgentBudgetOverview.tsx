/** Read-only cost ledger for server-owned completions, not a live worker grant.
 *
 * Every sum comes from the agent-management SQL ledger; outstanding provider
 * side effects remain reserved after restart until independently reconciled.
 */
import { useEffect, useState } from 'react';

type BudgetStatus = {
  agent_definition_id: string;
  definition_version: number;
  currency: 'USD';
  limit_microusd: number | null;
  spent_estimated_microusd: number;
  reserved_microusd: number;
  remaining_estimated_microusd: number | null;
  unsettled_reservations: number;
  completion_budget_status: 'not_configured' | 'available' | 'exhausted';
  native_budget_enforced: false;
};

function validBudget(value: unknown, id: string, version: number): value is BudgetStatus {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return false;
  const v = value as Record<string, unknown>;
  const micros = (n: unknown) => Number.isSafeInteger(n) &&
    typeof n === 'number' && n >= 0 && n <= 1_000_000_000_000_000;
  if (v.agent_definition_id !== id || v.definition_version !== version ||
      v.currency !== 'USD' || v.native_budget_enforced !== false ||
      !micros(v.spent_estimated_microusd) || !micros(v.reserved_microusd) ||
      !micros(v.unsettled_reservations)) return false;
  if (v.limit_microusd === null) {
    return v.remaining_estimated_microusd === null &&
      v.completion_budget_status === 'not_configured';
  }
  if (!micros(v.limit_microusd) || !micros(v.remaining_estimated_microusd)) return false;
  const remaining = Math.max(
    0, (v.limit_microusd as number) -
    (v.spent_estimated_microusd as number) - (v.reserved_microusd as number),
  );
  return v.remaining_estimated_microusd === remaining &&
    v.completion_budget_status === (remaining === 0 ? 'exhausted' : 'available');
}

const usd = (value: number) => (value / 1_000_000).toLocaleString('ru-RU', {
  minimumFractionDigits: 2, maximumFractionDigits: 6,
});

type State = {
  id: string;
  version: number;
  data: BudgetStatus | null;
  error: boolean;
  loading: boolean;
};

export default function AgentBudgetOverview({ agentId, version }: {
  agentId: string | null; version: number | null;
}) {
  const [snapshot, setSnapshot] = useState<State | null>(null);
  const [refresh, setRefresh] = useState(0);

  useEffect(() => {
    if (!agentId || version === null) {
      setSnapshot(null);
      return;
    }
    let active = true;
    setSnapshot({ id: agentId, version, data: null, error: false, loading: true });
    void fetch('/api/v1/agents/definitions/' + encodeURIComponent(agentId) + '/budget', {
      credentials: 'same-origin',
      headers: { Accept: 'application/json' },
    }).then(async response => {
      if (!response.ok) throw new Error('Budget status unavailable');
      const raw: unknown = await response.json();
      if (!validBudget(raw, agentId, version)) throw new Error('Budget ledger inconsistent');
      if (active) setSnapshot({ id: agentId, version, data: raw, error: false, loading: false });
    }).catch(() => {
      if (active) setSnapshot({ id: agentId, version, data: null, error: true, loading: false });
    });
    return () => { active = false; };
  }, [agentId, version, refresh]);

  const current = snapshot?.id === agentId && snapshot.version === version ? snapshot : null;
  return <section data-testid="agent-budget-overview" aria-label="Серверный бюджет профиля">
    <strong>Бюджет исполнения (USD, серверный учёт)</strong>
    {' '}<button type="button" data-testid="agent-budget-refresh"
      disabled={!agentId} onClick={() => setRefresh(n => n + 1)}>Обновить остаток</button>
    {!agentId || version === null ? <p>Выберите сохранённый профиль для проверки расходов.</p> :
      !current || current.loading ? <p role="status">Проверка расходов и резервов…</p> :
      current.error || !current.data ? <p role="alert">
        Бюджет не подтверждён сервером. Не запускайте платную работу по этим данным.
      </p> : <>
        <p data-testid="agent-budget-state">
          {current.data.completion_budget_status === 'not_configured'
            ? 'USD-лимит не задан: оплачиваемое выполнение не разрешено этим экраном.'
            : current.data.completion_budget_status === 'exhausted'
              ? 'Расчётный лимит исчерпан: новые завершения запрещаются серверным контролем бюджета.'
              : 'Есть расчётный остаток для обычных completions. Допуск конкретного вызова проверяется отдельно.'}
        </p>
        <p data-testid="agent-budget-amounts">
          Лимит: {current.data.limit_microusd === null ? 'не установлен' :
            usd(current.data.limit_microusd) + ' USD'}.
          {' '}Учтено: {usd(current.data.spent_estimated_microusd)} USD.
          {' '}Зарезервировано: {usd(current.data.reserved_microusd)} USD.
          {' '}Остаток: {current.data.remaining_estimated_microusd === null ? 'не определён' :
            usd(current.data.remaining_estimated_microusd) + ' USD'}.
          {' '}Незакрытых резервов: {current.data.unsettled_reservations}.
        </p>
      </>}
    <p data-testid="agent-budget-native-boundary">
      Native streaming-worker: общий USD-лимит здесь НЕ контролируется.
      Для нативного исполнения с установленным бюджетом экспорт профиля
      заблокирован до отдельного backend enforcement. Эти цифры не
      подтверждают readiness worker, платного провайдера или выпуск.
    </p>
  </section>;
}
