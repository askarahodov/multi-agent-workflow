import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { ProblemDetailsError } from '../../api/client';
import type {
  ApiAdapter, ReconciliationRequest, ReconciliationResponse, TaskResponse,
} from '../../api/types';
import RecoverySection from './RecoverySection';

const task: TaskResponse = {
  id: 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa',
  workflow_run_id: 'bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb',
  title: 'Прерванная задача', status: 'blocked',
  priority: 0, attempt_count: 1, max_attempts: 2, version: 2,
};

const response: ReconciliationResponse = {
  task_id: task.id,
  decision: 'UNKNOWN',
  evidence_ref: 'qa/incident-123',
  evidence_sha256: 'a'.repeat(64),
  operator_subject: 'test-admin',
  decided_at: '2026-10-15T10:00:00Z',
};

function makeAdapter(overrides: Record<string, unknown> = {}) {
  const methods = {
    listRecoveryQuarantine: vi.fn().mockResolvedValue([task]),
    getRecoveryReconciliation: vi.fn().mockRejectedValue(
      new ProblemDetailsError({ status: 404, title: 'Not found' }),
    ),
    getRecoveryLedger: vi.fn().mockResolvedValue({
      task_id: task.id,
      ledger_status: 'AVAILABLE',
      attempts: [{ attempt_id: 'attempt-1', record_status: 'RECORDS', entries: [
        { call_ref: 'fingerprint-1234', tool: 'write_file', state: 'CLAIMED' },
      ] }],
    }),
    attestRecovery: vi.fn().mockResolvedValue(response),
    claimTask: vi.fn(),
    submitTask: vi.fn(),
    ...overrides,
  };
  return { adapter: methods as unknown as ApiAdapter, methods };
}

afterEach(() => vi.clearAllMocks());

describe('operator recovery console', () => {
  it('does not spend tokens, claim tasks or mutate anything on mount', async () => {
    const { adapter, methods } = makeAdapter({
      listRecoveryQuarantine: vi.fn().mockResolvedValue([]),
    });
    render(<RecoverySection adapter={adapter} />);
    expect(await screen.findByText('Карантинных задач нет.')).toBeInTheDocument();
    expect(methods.attestRecovery).not.toHaveBeenCalled();
    expect(methods.claimTask).not.toHaveBeenCalled();
    expect(methods.submitTask).not.toHaveBeenCalled();
  });

  it('requires review before recording UNKNOWN and keeps task blocked', async () => {
    const { adapter, methods } = makeAdapter();
    render(<RecoverySection adapter={adapter} />);
    fireEvent.click(await screen.findByTestId(`recovery-task-${task.id}`));
    expect(await screen.findByText(/Есть вызовы CLAIMED/)).toBeInTheDocument();

    const save = screen.getByTestId('recovery-attest') as HTMLButtonElement;
    expect(save).toBeDisabled();
    fireEvent.change(screen.getByLabelText('Идентификатор доказательства'), {
      target: { value: 'qa/incident-123' },
    });
    fireEvent.change(screen.getByLabelText('SHA-256 доказательства'), {
      target: { value: 'a'.repeat(64) },
    });
    expect(save).toBeDisabled();
    fireEvent.click(screen.getByRole('checkbox'));
    expect(save).toBeEnabled();
    fireEvent.click(save);
    await waitFor(() => expect(methods.attestRecovery).toHaveBeenCalledWith(task.id, {
      decision: 'UNKNOWN', evidence_ref: 'qa/incident-123',
      evidence_sha256: 'a'.repeat(64),
    } satisfies ReconciliationRequest));
    expect(await screen.findByTestId('recovery-decision')).toHaveTextContent('UNKNOWN');
    expect(methods.claimTask).not.toHaveBeenCalled();
    expect(methods.submitTask).not.toHaveBeenCalled();
  });

  it('does not permit confirmed decision with unavailable ledger', async () => {
    const { adapter, methods } = makeAdapter({
      getRecoveryLedger: vi.fn().mockRejectedValue(
        new ProblemDetailsError({ status: 503, title: 'Unconfigured' }),
      ),
    });
    render(<RecoverySection adapter={adapter} />);
    fireEvent.click(await screen.findByTestId(`recovery-task-${task.id}`));
    expect(await screen.findByText(/Журнал недоступен/)).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText('Решение'), {
      target: { value: 'CONFIRMED_SIDE_EFFECT' },
    });
    fireEvent.change(screen.getByLabelText('Идентификатор доказательства'), {
      target: { value: 'qa/incident-123' },
    });
    fireEvent.change(screen.getByLabelText('SHA-256 доказательства'), {
      target: { value: 'a'.repeat(64) },
    });
    fireEvent.click(screen.getByRole('checkbox'));
    expect(screen.getByTestId('recovery-attest')).toBeDisabled();
    expect(methods.attestRecovery).not.toHaveBeenCalled();
  });

  it('shows an immutable confirmed result without a new submission form', async () => {
    const { adapter, methods } = makeAdapter({
      getRecoveryReconciliation: vi.fn().mockResolvedValue({
        ...response, decision: 'CONFIRMED_SIDE_EFFECT',
      }),
    });
    render(<RecoverySection adapter={adapter} />);
    fireEvent.click(await screen.findByTestId(`recovery-task-${task.id}`));
    expect(await screen.findByText(/Решение подтверждено и неизменяемо/)).toBeInTheDocument();
    expect(screen.queryByTestId('recovery-attest')).not.toBeInTheDocument();
    expect(methods.attestRecovery).not.toHaveBeenCalled();
  });

  it('reports RBAC denial without exposing a form or retrying requests', async () => {
    const { adapter, methods } = makeAdapter({
      listRecoveryQuarantine: vi.fn().mockRejectedValue(
        new ProblemDetailsError({ status: 403, title: 'Forbidden' }),
      ),
    });
    render(<RecoverySection adapter={adapter} />);
    expect(await screen.findByRole('alert')).toHaveTextContent('Требуется доступ администратора.');
    expect(methods.attestRecovery).not.toHaveBeenCalled();
  });
});
