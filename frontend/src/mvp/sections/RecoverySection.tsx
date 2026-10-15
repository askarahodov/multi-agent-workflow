/** Operator-only recovery console (Issue #38).
 *
 * Read-only until the administrator explicitly submits an evidence attestation.
 * Never invokes claim/retry/requeue and never auto-spends model tokens.
 */
import { type FormEvent, useEffect, useState } from 'react';

import { ProblemDetailsError } from '../../api/client';
import type {
  ApiAdapter,
  ReconciliationDecision,
  ReconciliationResponse,
  RecoveryLedgerReport,
  TaskResponse,
} from '../../api/types';
import { useMvpStore } from '../mvpStore';
import { Card, PageHeader, StatusBadge } from '../ui';

const DECISIONS: Array<{ value: ReconciliationDecision; label: string }> = [
  { value: 'UNKNOWN', label: 'Исход неизвестен — оставить карантин' },
  { value: 'CONFIRMED_SIDE_EFFECT', label: 'Побочное действие подтверждено' },
  { value: 'CONFIRMED_NO_SIDE_EFFECT', label: 'Отсутствие побочного действия подтверждено' },
];

function detail(error: unknown): string {
  if (error instanceof ProblemDetailsError) {
    if (error.status === 401 || error.status === 403) return 'Требуется доступ администратора.';
    if (error.status === 503) return 'Сервис проверки недоступен или не настроен.';
    if (error.status === 404) return 'Запись не найдена.';
    return error.message;
  }
  return 'Запрос не выполнен. Проверьте соединение с Orchestration API.';
}

export default function RecoverySection({ adapter }: { adapter?: ApiAdapter }) {
  const sharedAdapter = useMvpStore((state) => state.api);
  const api = adapter ?? sharedAdapter;

  const [tasks, setTasks] = useState<TaskResponse[]>([]);
  const [loading, setLoading] = useState(true);
  const [listError, setListError] = useState<string | null>(null);
  const [refresh, setRefresh] = useState(0);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [loadingDetail, setLoadingDetail] = useState(false);
  const [saved, setSaved] = useState<ReconciliationResponse | null>(null);
  const [ledger, setLedger] = useState<RecoveryLedgerReport | null>(null);
  const [ledgerWarning, setLedgerWarning] = useState<string | null>(null);
  const [detailError, setDetailError] = useState<string | null>(null);
  const [decision, setDecision] = useState<ReconciliationDecision>('UNKNOWN');
  const [evidenceRef, setEvidenceRef] = useState('');
  const [digest, setDigest] = useState('');
  const [reviewed, setReviewed] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);

  useEffect(() => {
    let current = true;
    setLoading(true);
    api.listRecoveryQuarantine().then(
      (items) => {
        if (current) {
          setTasks(items);
          setListError(null);
        }
      },
      (error: unknown) => {
        if (current) {
          setTasks([]);
          setListError(detail(error));
        }
      },
    ).finally(() => {
      if (current) setLoading(false);
    });
    return () => { current = false; };
  }, [api, refresh]);

  useEffect(() => {
    if (!selectedId) return;
    let current = true;
    setLoadingDetail(true);
    setSaved(null);
    setLedger(null);
    setLedgerWarning(null);
    setDetailError(null);
    setDecision('UNKNOWN');
    setEvidenceRef('');
    setDigest('');
    setReviewed(false);
    setSubmitError(null);

    Promise.allSettled([
      api.getRecoveryReconciliation(selectedId),
      api.getRecoveryLedger(selectedId),
    ]).then(([decisionResult, ledgerResult]) => {
      if (!current) return;
      if (decisionResult.status === 'fulfilled') {
        setSaved(decisionResult.value);
      } else if (
        !(decisionResult.reason instanceof ProblemDetailsError &&
          decisionResult.reason.status === 404)
      ) {
        setDetailError(detail(decisionResult.reason));
      }
      if (ledgerResult.status === 'fulfilled') {
        setLedger(ledgerResult.value);
      } else {
        setLedgerWarning(detail(ledgerResult.reason));
      }
    }).finally(() => {
      if (current) setLoadingDetail(false);
    });
    return () => { current = false; };
  }, [api, selectedId]);

  const selected = tasks.find((task) => task.id === selectedId);
  const confirmed = saved?.decision === 'CONFIRMED_SIDE_EFFECT' ||
    saved?.decision === 'CONFIRMED_NO_SIDE_EFFECT';
  const hasAmbiguousCalls = ledger?.attempts.some(
    (attempt) => attempt.entries.some((entry) => entry.state === 'CLAIMED'),
  ) ?? false;
  const canSubmit = !!selectedId && !loadingDetail && !submitting && !confirmed &&
    reviewed && /^[A-Za-z0-9][A-Za-z0-9._:/-]{2,159}$/.test(evidenceRef.trim()) &&
    /^[0-9a-f]{64}$/.test(digest.trim()) &&
    (decision === 'UNKNOWN' || ledger !== null);

  async function attest(event: FormEvent) {
    event.preventDefault();
    if (!selectedId || !canSubmit) return;
    setSubmitting(true);
    setSubmitError(null);
    try {
      const result = await api.attestRecovery(selectedId, {
        decision, evidence_ref: evidenceRef.trim(), evidence_sha256: digest.trim(),
      });
      setSaved(result);
      setReviewed(false);
      // No claim/retry/requeue: an attestation is never a task transition.
    } catch (error) {
      setSubmitError(detail(error));
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div>
      <PageHeader
        title="Аварийное восстановление"
        subtitle="Административная проверка прерванных задач. Ни одно решение не запускает агента повторно."
        actions={
          <button type="button" onClick={() => setRefresh((n) => n + 1)}
            data-testid="recovery-refresh" style={buttonStyle}>Обновить</button>
        }
      />
      <p role="note" style={{ color: '#8b4a12', background: '#fff5e9',
        border: '1px solid #e3c5a1', borderRadius: 8, padding: 12, fontSize: 13 }}>
        <strong>Карантин безопасен по умолчанию.</strong> Даже решение «побочное действие
        отсутствует» не снимает блокировку. Создание новой задачи допускается
        только после отдельной проверки оператором.
      </p>
      <div style={{ display: 'grid', gridTemplateColumns: 'minmax(220px, 1fr) minmax(320px, 2fr)',
        gap: 16, alignItems: 'start' }}>
        <Card title="Задачи в карантине">
          {loading && <p role="status">Загрузка списка…</p>}
          {listError && <p role="alert">{listError}</p>}
          {!loading && !listError && tasks.length === 0 &&
            <p>Карантинных задач нет.</p>}
          {tasks.map((task) => (
            <button key={task.id} type="button" onClick={() => setSelectedId(task.id)}
              data-testid={`recovery-task-${task.id}`}
              aria-pressed={selectedId === task.id}
              style={{ ...buttonStyle, width: '100%', textAlign: 'left', marginBottom: 8,
                background: selectedId === task.id ? '#edf4ff' : '#fff' }}>
              <strong>{task.title}</strong>
              <span style={{ display: 'block', margin: '5px 0' }}>
                <StatusBadge status={task.status} />
              </span>
              <span style={{ overflowWrap: 'anywhere', fontSize: 11 }}>{task.id}</span>
            </button>
          ))}
        </Card>
        <Card title="Проверка задачи">
          {!selected && <p>Выберите задачу слева.</p>}
          {selected && <>
            <h3 style={{ fontSize: 15, marginTop: 0 }}>{selected.title}</h3>
            <p style={{ fontSize: 12, overflowWrap: 'anywhere' }}>ID: {selected.id}</p>
            {loadingDetail && <p role="status">Загрузка данных проверки…</p>}
            {detailError && <p role="alert">{detailError}</p>}
            {!loadingDetail && saved && (
              <p data-testid="recovery-decision">
                Последнее решение: <strong>{saved.decision}</strong>
                {' · '}оператор {saved.operator_subject}
              </p>
            )}
            {!loadingDetail && (
              <>
                <h4 style={{ marginBottom: 6 }}>Tool Ledger (только чтение)</h4>
                {ledgerWarning && <p role="alert">
                  Журнал недоступен: {ledgerWarning}. Отсутствие данных не
                  доказывает безопасность повторного исполнения.
                </p>}
                {ledger && ledger.attempts.map((attempt) => (
                  <div key={attempt.attempt_id} style={{ fontSize: 12, marginBottom: 10 }}>
                    <strong>Попытка {attempt.attempt_id}</strong>
                    {attempt.record_status === 'NO_RECORDS' ?
                      <p>Нет записей. Исход побочных действий неизвестен.</p> :
                      <ul>
                        {attempt.entries.map((entry) => (
                          <li key={entry.call_ref}>
                            {entry.tool} — <StatusBadge status={entry.state}
                              tone={entry.state === 'CLAIMED' ? 'warn' : undefined} />
                            {' '}({entry.call_ref})
                          </li>
                        ))}
                      </ul>}
                  </div>
                ))}
                {hasAmbiguousCalls && <p role="alert" style={{ color: '#a3271c' }}>
                  Есть вызовы CLAIMED с неизвестным исходом. Сопоставьте
                  внешние артефакты и доказательства перед подтверждением.
                </p>}
                {confirmed ? (
                  <p role="status">Решение подтверждено и неизменяемо. Задача остаётся blocked.</p>
                ) : (
                  <form onSubmit={attest}>
                    <h4>Зафиксировать результат сверки</h4>
                    <label style={fieldStyle}>Решение
                      <select aria-label="Решение" value={decision}
                        onChange={(e) => { setDecision(e.target.value as ReconciliationDecision); setReviewed(false); }}
                        style={inputStyle}>
                        {DECISIONS.map((item) => <option key={item.value} value={item.value}>
                          {item.label}
                        </option>)}
                      </select>
                    </label>
                    <label style={fieldStyle}>Идентификатор доказательства
                      <input aria-label="Идентификатор доказательства" required
                        value={evidenceRef} onChange={(e) => setEvidenceRef(e.target.value)}
                        placeholder="qa/incident-123" style={inputStyle} />
                    </label>
                    <label style={fieldStyle}>SHA-256 доказательства (64 символа)
                      <input aria-label="SHA-256 доказательства" required
                        value={digest} onChange={(e) => setDigest(e.target.value)}
                        maxLength={64} spellCheck={false} style={inputStyle} />
                    </label>
                    {decision !== 'UNKNOWN' && !ledger &&
                      <p role="alert">Для подтверждения необходимо просмотреть доступный Tool Ledger.
                        Пока можно сохранить только UNKNOWN.</p>}
                    <label style={{ display: 'flex', alignItems: 'flex-start', gap: 8,
                      margin: '12px 0', fontSize: 12 }}>
                      <input type="checkbox" checked={reviewed}
                        onChange={(e) => setReviewed(e.target.checked)} />
                      Я проверил доказательства и понимаю, что это действие
                      не перезапускает задачу.
                    </label>
                    {submitError && <p role="alert">{submitError}</p>}
                    <button type="submit" disabled={!canSubmit}
                      data-testid="recovery-attest" style={buttonStyle}>
                      {submitting ? 'Сохранение…' : 'Зафиксировать решение'}
                    </button>
                  </form>
                )}
              </>
            )}
          </>}
        </Card>
      </div>
    </div>
  );
}

const buttonStyle = {
  padding: '8px 12px', borderRadius: 6, cursor: 'pointer',
  border: '1px solid #b6c5d5', color: '#173858',
};
const fieldStyle = { display: 'block', marginBottom: 12, fontSize: 12 };
const inputStyle = {
  display: 'block', padding: '8px 10px', width: '100%',
  boxSizing: 'border-box' as const, marginTop: 4,
  borderRadius: 6, border: '1px solid #c8ced6',
};
