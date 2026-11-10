import { act, cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import AgentBudgetOverview from './AgentBudgetOverview';

const valid = (id = 'p1', version = 1) => ({
  agent_definition_id: id, definition_version: version, currency: 'USD',
  limit_microusd: 1_000_000, spent_estimated_microusd: 400_000,
  reserved_microusd: 200_000, remaining_estimated_microusd: 400_000,
  unsettled_reservations: 1, completion_budget_status: 'available',
  native_budget_enforced: false,
});
function response(value: unknown, status = 200) {
  return { ok: status < 400, status, json: async () => value } as Response;
}
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });
describe('server budget evidence, never native paid readiness', () => {
  it('reads settled/held/remaining amounts without triggering a completion', async () => {
    const fetchImpl = vi.fn(async (_url: string) => response(valid()));
    vi.stubGlobal('fetch', fetchImpl);
    render(<AgentBudgetOverview agentId="p1" version={1}/>);
    expect(await screen.findByText(/Есть расчётный остаток/)).toBeInTheDocument();
    expect(screen.getByTestId('agent-budget-amounts')).toHaveTextContent('Незакрытых резервов: 1');
    expect(screen.getByTestId('agent-budget-native-boundary')).toHaveTextContent('НЕ контролируется');
    expect(fetchImpl).toHaveBeenCalledTimes(1);
    expect(fetchImpl.mock.calls[0][0]).toBe('/api/v1/agents/definitions/p1/budget');
    expect(String(fetchImpl.mock.calls[0][0])).not.toContain('completions');
  });
  it('fails closed for malformed ledgers, mismatched versions and unavailable server', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => response({ ...valid(), agent_definition_id: 'other' })));
    const first = render(<AgentBudgetOverview agentId="p1" version={1}/>);
    expect(await screen.findByRole('alert')).toHaveTextContent('Бюджет не подтверждён');
    first.unmount();
    vi.stubGlobal('fetch', vi.fn(async () => response(valid(), 503)));
    render(<AgentBudgetOverview agentId="p1" version={1}/>);
    expect(await screen.findByRole('alert')).toHaveTextContent('Бюджет не подтверждён');
  });
  it('never shows an old profile balance after selection changes', async () => {
    let complete!: (r: Response) => void;
    const fetchImpl = vi.fn(async (url: string) => {
      if (url.includes('/p1/')) return new Promise<Response>(resolve => { complete = resolve; });
      return response({ ...valid('p2', 2), completion_budget_status: 'exhausted',
        remaining_estimated_microusd: 0, reserved_microusd: 600_000 });
    });
    vi.stubGlobal('fetch', fetchImpl);
    const view = render(<AgentBudgetOverview agentId="p1" version={1}/>);
    view.rerender(<AgentBudgetOverview agentId="p2" version={2}/>);
    await screen.findByText(/Расчётный лимит исчерпан/);
    await act(async () => complete(response(valid())));
    expect(screen.getByTestId('agent-budget-amounts')).toHaveTextContent('Незакрытых резервов: 1');
    expect(screen.queryByText(/Есть расчётный остаток/)).not.toBeInTheDocument();
  });
  it('reloads from the server on explicit refresh without mutating balances', async () => {
    const fetchImpl = vi.fn(async (_url: string) => response(valid()));
    vi.stubGlobal('fetch', fetchImpl);
    render(<AgentBudgetOverview agentId="p1" version={1}/>);
    await screen.findByText(/Есть расчётный остаток/);
    fireEvent.click(screen.getByTestId('agent-budget-refresh'));
    await screen.findByText(/Есть расчётный остаток/);
    expect(fetchImpl).toHaveBeenCalledTimes(2);
  });
});
