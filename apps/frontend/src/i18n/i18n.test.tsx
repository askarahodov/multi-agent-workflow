import { render, screen, cleanup } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it } from 'vitest';

import { I18nProvider, useI18n } from './I18nProvider';

afterEach(() => {
  cleanup();
  document.documentElement.lang = 'en';
  document.documentElement.dir = 'ltr';
});

function Probe() {
  const { t, locale, dir, setLocale } = useI18n();
  return (
    <div>
      <span data-testid="locale">{locale}</span>
      <span data-testid="dir">{dir}</span>
      <span data-testid="project">{t('nav.project')}</span>
      <span data-testid="missing">{t('does.not.exist')}</span>
      <button type="button" onClick={() => setLocale('en')}>
        en
      </button>
    </div>
  );
}

describe('I18nProvider', () => {
  it('defaults to ru and reflects lang/dir on <html>', () => {
    render(
      <I18nProvider>
        <Probe />
      </I18nProvider>,
    );
    expect(screen.getByTestId('locale')).toHaveTextContent('ru');
    expect(screen.getByTestId('project')).toHaveTextContent('Проект');
    expect(document.documentElement.lang).toBe('ru');
    expect(document.documentElement.dir).toBe('ltr');
    // Missing keys fall back to the key itself rather than crashing.
    expect(screen.getByTestId('missing')).toHaveTextContent('does.not.exist');
  });

  it('switches locale and updates visible strings', async () => {
    render(
      <I18nProvider>
        <Probe />
      </I18nProvider>,
    );
    await userEvent.click(screen.getByRole('button', { name: 'en' }));
    expect(screen.getByTestId('locale')).toHaveTextContent('en');
    expect(screen.getByTestId('project')).toHaveTextContent('Project');
    expect(document.documentElement.lang).toBe('en');
  });
});
