/**
 * I18nProvider (ADR-110 §3.5).
 *
 * Holds the active locale, derives text direction (`ru`/`en` → `ltr`, `ar`/`he`
 * would be `rtl`) and reflects both onto `<html lang dir>` so RTL layouts are a
 * switch, not a rewrite. Logical CSS properties everywhere make that safe.
 */

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from 'react';

import { MESSAGES, type Locale } from './messages';

export type Direction = 'ltr' | 'rtl';

const RTL_LOCALES: readonly string[] = ['ar', 'he', 'fa', 'ur'];

function directionFor(locale: Locale): Direction {
  return RTL_LOCALES.includes(locale) ? 'rtl' : 'ltr';
}

interface I18nContextValue {
  locale: Locale;
  dir: Direction;
  setLocale: (locale: Locale) => void;
  t: (key: string, vars?: Record<string, string | number>) => string;
}

const I18nContext = createContext<I18nContextValue | null>(null);

export function I18nProvider({
  children,
  initialLocale = 'ru',
}: {
  children: ReactNode;
  initialLocale?: Locale;
}) {
  const [locale, setLocale] = useState<Locale>(initialLocale);
  const dir = directionFor(locale);

  useEffect(() => {
    const root = document.documentElement;
    root.lang = locale;
    root.dir = dir;
  }, [locale, dir]);

  const t = useCallback(
    (key: string, vars?: Record<string, string | number>) => {
      const template = MESSAGES[locale][key] ?? MESSAGES.en[key] ?? key;
      if (!vars) return template;
      return template.replace(/\{(\w+)\}/g, (_, name: string) => String(vars[name] ?? `{${name}}`));
    },
    [locale],
  );

  const setLocaleSafe = useCallback((next: Locale) => setLocale(next), []);

  const value = useMemo(
    () => ({ locale, dir, setLocale: setLocaleSafe, t }),
    [locale, dir, setLocaleSafe, t],
  );

  return <I18nContext.Provider value={value}>{children}</I18nContext.Provider>;
}

export function useI18n(): I18nContextValue {
  const context = useContext(I18nContext);
  if (!context) throw new Error('useI18n must be used within an <I18nProvider>');
  return context;
}
