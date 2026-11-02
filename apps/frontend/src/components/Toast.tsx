/**
 * Toast notifications (ADR-110 §3.2).
 *
 * `ToastProvider` mounts one polite live region; `useToast()` returns a
 * `notify()` function. Errors additionally use `role="alert"` (assertive) so
 * failures are announced immediately. Toasts auto-dismiss after `duration` ms
 * and can be dismissed manually with a labelled icon button.
 */

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from 'react';

import styles from './overlays.module.css';
import { cx } from './cx';
import { IconButton } from './IconButton';

export type ToastTone = 'info' | 'success' | 'warn' | 'error';

export interface ToastInput {
  title: string;
  message?: string;
  tone?: ToastTone;
  duration?: number;
}

interface ToastRecord extends Required<Omit<ToastInput, 'message'>> {
  id: number;
  message?: string;
}

interface ToastContextValue {
  notify: (toast: ToastInput) => void;
}

const ToastContext = createContext<ToastContextValue | null>(null);

const TONE_CLASS: Record<ToastTone, string> = {
  info: styles.toastInfo,
  success: styles.toastSuccess,
  warn: styles.toastWarn,
  error: styles.toastError,
};

function ToastCard({ toast, onDismiss }: { toast: ToastRecord; onDismiss: (id: number) => void }) {
  const { id, title, message, tone } = toast;
  return (
    <div
      className={cx(styles.toast, TONE_CLASS[tone])}
      role={tone === 'error' ? 'alert' : 'status'}
    >
      <div className={styles.toastBody}>
        <div className={styles.toastTitle}>{title}</div>
        {message ? <div className={styles.toastMessage}>{message}</div> : null}
      </div>
      <IconButton label="Закрыть уведомление" onClick={() => onDismiss(id)}>
        ✕
      </IconButton>
    </div>
  );
}

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<ToastRecord[]>([]);
  const counter = useRef(0);
  const timers = useRef(new Map<number, ReturnType<typeof setTimeout>>());

  const dismiss = useCallback((id: number) => {
    const timer = timers.current.get(id);
    if (timer) {
      clearTimeout(timer);
      timers.current.delete(id);
    }
    setToasts((current) => current.filter((toast) => toast.id !== id));
  }, []);

  const notify = useCallback(
    ({ title, message, tone = 'info', duration = 5000 }: ToastInput) => {
      const id = (counter.current += 1);
      setToasts((current) => [...current, { id, title, message, tone, duration }]);
      const timer = setTimeout(() => dismiss(id), duration);
      timers.current.set(id, timer);
    },
    [dismiss],
  );

  useEffect(() => {
    const map = timers.current;
    return () => {
      map.forEach((timer) => clearTimeout(timer));
      map.clear();
    };
  }, []);

  const value = useMemo(() => ({ notify }), [notify]);

  return (
    <ToastContext.Provider value={value}>
      {children}
      <div className={styles.toastRegion} role="region" aria-label="Уведомления" aria-live="polite">
        {toasts.map((toast) => (
          <ToastCard key={toast.id} toast={toast} onDismiss={dismiss} />
        ))}
      </div>
    </ToastContext.Provider>
  );
}

export function useToast(): ToastContextValue {
  const context = useContext(ToastContext);
  if (!context) {
    throw new Error('useToast must be used within a <ToastProvider>');
  }
  return context;
}
