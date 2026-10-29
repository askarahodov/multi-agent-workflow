/**
 * i18n message catalog (ADR-110 §3.5).
 *
 * A small, typed, dependency-free catalog: default `ru`, fallback `en`.
 * `t(key)` returns the locale string, then the `en` string, then the key, so a
 * missing translation degrades visibly but never crashes.
 */

export type Locale = 'ru' | 'en';

export const LOCALES: Locale[] = ['ru', 'en'];

export const MESSAGES: Record<Locale, Record<string, string>> = {
  ru: {
    'shell.brand': 'Multi-Agent Platform',
    'shell.subtitle': 'Панель управления',
    'shell.skipToContent': 'Перейти к содержимому',
    'shell.notifications': 'Уведомления',
    'shell.language': 'Язык',
    'nav.project': 'Проект',
    'nav.board': 'Kanban-доска',
    'nav.conveyor': 'Конвейер и роли',
    'nav.runs': 'Запуски',
    'nav.task': 'Карточка задачи',
    'nav.agentLog': 'Живой журнал',
    'nav.recovery': 'Восстановление',
    'nav.settings': 'Настройки',
    'nav.editor': 'Редактор',
    'common.retry': 'Повторить',
    'common.loading': 'Загрузка данных',
    'project.title': 'Проект',
    'project.subtitle': 'Проекты и рабочие пространства платформы.',
    'board.title': 'Kanban-доска',
    'board.subtitle': 'Состояние задач на каждом этапе жизненного цикла.',
    'board.empty': 'Задач пока нет.',
    'agentMonitor.title': 'Живой журнал агента',
    'agentMonitor.subtitle': 'События жизненного цикла выбранного запуска в реальном времени.',
    'settings.title': 'Настройки проекта',
    'settings.subtitle': 'Подключения, модели и определения агентов.',
  },
  en: {
    'shell.brand': 'Multi-Agent Platform',
    'shell.subtitle': 'Control panel',
    'shell.skipToContent': 'Skip to content',
    'shell.notifications': 'Notifications',
    'shell.language': 'Language',
    'nav.project': 'Project',
    'nav.board': 'Task board',
    'nav.conveyor': 'Conveyor & roles',
    'nav.runs': 'Runs',
    'nav.task': 'Task card',
    'nav.agentLog': 'Agent monitor',
    'nav.recovery': 'Recovery',
    'nav.settings': 'Settings',
    'nav.editor': 'Editor',
    'common.retry': 'Retry',
    'common.loading': 'Loading data',
    'project.title': 'Project',
    'project.subtitle': 'Platform projects and workspaces.',
    'board.title': 'Task board',
    'board.subtitle': 'Task state across every lifecycle stage.',
    'board.empty': 'No tasks yet.',
    'agentMonitor.title': 'Agent monitor',
    'agentMonitor.subtitle': 'Live lifecycle events for the selected run.',
    'settings.title': 'Project settings',
    'settings.subtitle': 'Connections, models and agent definitions.',
  },
};
