import { defineConfig } from 'vitepress'
import { installMermaidFence } from './mermaid-fence.mjs'
import anchor from 'markdown-it-anchor'
import toc from 'markdown-it-table-of-contents'
import taskLists from 'markdown-it-task-lists'
import footnote from 'markdown-it-footnote'
import container from 'markdown-it-container'
import abbr from 'markdown-it-abbr'
import deflist from 'markdown-it-deflist'
import mark from 'markdown-it-mark'
import sub from 'markdown-it-sub'
import sup from 'markdown-it-sup'

export default defineConfig({
    lang: 'ru-RU',
    title: 'Multi-Agent Workflow System',
    description: 'Платформа управляемой агентной разработки программного обеспечения',
    appearance: 'dark',
    
    head: [
      ['link', { rel: 'preconnect', href: 'https://fonts.googleapis.com' }],
      ['link', { rel: 'preconnect', href: 'https://fonts.gstatic.com', crossorigin: '' }],
      ['link', { rel: 'stylesheet', href: 'https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap' }],
      ['meta', { name: 'theme-color', content: '#1e1e2e' }],
      ['meta', { name: 'og:type', content: 'website' }],
      ['meta', { name: 'og:title', content: 'Multi-Agent Workflow System' }],
      ['meta', { name: 'og:description', content: 'Платформа управляемой агентной разработки программного обеспечения' }],
      ['meta', { name: 'twitter:card', content: 'summary_large_image' }]
    ],

    themeConfig: {
      logo: '/logo.svg',
      
      nav: [
        { text: 'Руководство', link: '/user-guide/getting-started', activeMatch: '^/user-guide/' },
        { text: 'Разработчикам', link: '/developer/api-reference', activeMatch: '^/developer/' },
        { text: 'Эксплуатация', link: '/operations/deployment-guide', activeMatch: '^/operations/' },
        { text: 'Архитектура', link: '/developer/architecture-decisions/adr-index', activeMatch: '^/(architecture|adr|developer/architecture-decisions)/' },
        { text: 'Безопасность', link: '/security/native-tool-dispatch', activeMatch: '^/security/' },
        { text: 'Требования и контракты', link: '/governance/requirements-and-contracts', activeMatch: '^/(product/|governance/requirements-and-contracts|architecture/contract-registry)' },
        { text: 'Документация', link: '/governance/documentation-policy', activeMatch: '^/governance/(documentation-|technical-document-boundaries)' },
        { text: 'Релизы', link: '/releases/v0.1.0-rc1', activeMatch: '^/releases/v0.1.0-rc1' },
        {
          text: 'v0.1.0-rc1',
          items: [
            { text: 'История изменений', link: '/releases/v0.1.0-rc1' },
            { text: 'Примечания к выпуску', link: '/releases/v0.1.0-rc1' },
            { text: 'GitHub', link: 'https://github.com/askarahodov/multi-agent-workflow' }
          ]
        }
      ],

      sidebar: {
        '/user-guide/': [
          {
            text: 'Начало работы',
            items: [
              { text: 'Введение', link: '/user-guide/getting-started' },
              { text: 'Справочник CLI', link: '/user-guide/cli-reference' },
              { text: 'Настройка', link: '/user-guide/configuration' },
              { text: 'Обзор архитектуры', link: '/user-guide/architecture-overview' },
              { text: 'Устранение проблем', link: '/user-guide/troubleshooting' },
              { text: 'Профили агентов', link: '/user-guide/agent-profiles' },
              { text: 'Доска задач', link: '/user-guide/kanban-runtime-board' },
              { text: 'Запуск workflow', link: '/user-guide/published-workflow-run' },
              { text: 'Каталог провайдеров', link: '/user-guide/provider-catalog' },
              { text: 'Шаблоны SDLC', link: '/user-guide/configured-sdlc-presets' },
              { text: 'Справочник нод', link: '/user-guide/node-guide' },
              { text: 'Клавиатура и история', link: '/user-guide/editor-keyboard-history' },
              { text: 'Настройка проекта', link: '/user-guide/project-setup' }
            ]
          }
        ],
        '/developer/': [
          {
            text: 'Справочник API',
            items: [
              { text: 'REST API', link: '/developer/api-reference' },
              { text: 'Разработка агентов', link: '/developer/agent-development' },
              { text: 'Интеграция Kanban', link: '/developer/kanban-integration' },
              { text: 'Контроль качества', link: '/developer/quality-gates' },
              { text: 'Версионирование', link: '/developer/versioning' }
            ]
          },
          {
            text: 'Архитектурные решения',
            items: [
              { text: 'Реестр ADR', link: '/developer/architecture-decisions/adr-index' },
              { text: 'ADR-001: Hermes Independence', link: '/adr/001-hermes-independence' },
              { text: 'ADR-010: Multi-Agent Orchestration', link: '/adr/ADR-010-multi-agent-orchestration' },
              { text: 'ADR-011: Agent Runtime Loop', link: '/adr/ADR-011-agent-runtime-loop' },
              { text: 'ADR-012: Tool Registry', link: '/adr/ADR-012-tool-registry' },
              { text: 'ADR-013: MVP Core Subsystems', link: '/adr/ADR-013-mvp-core-subsystems' },
              { text: 'ADR-014: Cross-Subsystem Integration', link: '/adr/ADR-014-cross-subsystem-integration' },
              { text: 'ADR-015: Management API Auth', link: '/adr/ADR-015-management-api-auth' },
              { text: 'ADR-016: SDLC Template Automation', link: '/adr/ADR-016-sdlc-template-automation' }
            ]
          }
        ],
        '/operations/': [
          {
            text: 'Развёртывание',
            items: [
              { text: 'Руководство по развёртыванию', link: '/operations/deployment-guide' },
              { text: 'Справочник Docker Compose', link: '/operations/docker-compose-reference' }
            ]
          },
          {
            text: 'Наблюдаемость',
            items: [
              { text: 'Мониторинг и оповещения', link: '/operations/monitoring-alerting' }
            ]
          },
          {
            text: 'Надёжность',
            items: [
              { text: 'Резервное копирование и восстановление', link: '/operations/backup-recovery' },
              { text: 'Масштабирование', link: '/operations/scaling-guide' }
            ]
          }
        ],
        '/governance/': [{ text: 'Продуктовые требования', items: [{ text: 'Требования и контракты', link: '/governance/requirements-and-contracts' }, { text: 'PRD', link: '/product/PRD' }, { text: 'Трассируемость', link: '/product/traceability' }, { text: 'Реестр контрактов', link: '/architecture/contract-registry' }] }, { text: 'Управление документацией', items: [{ text: 'Политика', link: '/governance/documentation-policy' }, { text: 'Реестр документов', link: '/governance/documentation-inventory' }, { text: 'Границы технических документов', link: '/governance/technical-document-boundaries' }, { text: 'Паспорта ролей', link: '/governance/role-passports' }, { text: 'Изменения и риски', link: '/governance/change-risk-management' }] }],
        '/product/': [{ text: 'Продуктовые требования', items: [{ text: 'Требования и контракты', link: '/governance/requirements-and-contracts' }, { text: 'PRD', link: '/product/PRD' }, { text: 'Трассируемость', link: '/product/traceability' }, { text: 'Реестр контрактов', link: '/architecture/contract-registry' }] }],
        '/security/': [{ text: 'Границы безопасности', items: [{ text: 'Native tool dispatch', link: '/security/native-tool-dispatch' }, { text: 'Файловая изоляция', link: '/security/scoped-filesystem' }, { text: 'Доверенные команды', link: '/security/trusted-command-boundary' }, { text: 'Stream tickets', link: '/security/stream-ticket-rollout-issue-209' }] }],
        '/adr/': [{ text: 'Архитектурные решения', items: [{ text: 'Реестр ADR', link: '/developer/architecture-decisions/adr-index' }, { text: 'ADR-111: единый оркестратор', link: '/adr/ADR-111-native-sdlc-dependencies' }] }],
        '/architecture/': [
          { text: 'Продуктовые требования', items: [{ text: 'Требования и контракты', link: '/governance/requirements-and-contracts' }, { text: 'PRD', link: '/product/PRD' }, { text: 'Трассируемость', link: '/product/traceability' }, { text: 'Реестр контрактов', link: '/architecture/contract-registry' }] },
          {
            text: 'Архитектурные решения',
            items: [
              { text: 'Реестр ADR', link: '/developer/architecture-decisions/adr-index' }
            ]
          }
        ],
        '/releases/v0.1.0-rc1': [
          {
            text: 'Релизы',
            items: [
              { text: 'v0.1.0-rc1', link: '/releases/v0.1.0-rc1' }
            ]
          }
        ]
      },

      editLink: {
        pattern: 'https://github.com/askarahodov/multi-agent-workflow/edit/main/docs/:path',
        text: 'Редактировать на GitHub'
      },

      lastUpdated: {
        text: 'Обновлено',
        formatOptions: {
          dateStyle: 'short',
          timeStyle: 'short'
        }
      },

      docFooter: {
        prev: 'Предыдущая страница',
        next: 'Следующая страница'
      },

      outline: {
        level: [2, 3],
        label: 'На этой странице'
      },

      socialLinks: [
        { icon: 'github', link: 'https://github.com/askarahodov/multi-agent-workflow' },
      ],

      footer: {
        message: 'Распространяется по лицензии MIT.',
        copyright: 'Copyright © 2025 Multi-Agent Workflow Team'
      },

      search: {
        provider: 'local',
        options: {
          detailedView: true,
          miniSearch: {
            options: {
              fuzzy: 0.2,
              prefix: true,
              combineWith: 'AND'
            }
          }
        }
      },

      carbonAds: {
        code: '',
        placement: ''
      }
    },

    markdown: {
      math: true,
      theme: {
        light: 'github-light',
        dark: 'github-dark'
      },
      lineNumbers: true,
      config: (md) => {
        installMermaidFence(md)
        md.use(anchor, {
          slugify: (s) => s.normalize('NFC').toLowerCase().replace(/\s+/g, '-').replace(/[^\p{L}\p{N}\p{M}_-]+/gu, '') || 'section',
          tabIndex: false
        })
        md.use(toc, {
          includeLevel: [2, 3],
          containerClass: 'table-of-contents'
        })
        md.use(taskLists, { disabled: false, label: true, labelAfter: false })
        md.use(footnote)
        md.use(container, 'tip', {
          validate: (params) => params.trim().match(/^tip\s+(.*)$/),
          render: (tokens, idx) => {
            const m = tokens[idx].info.trim().match(/^tip\s+(.*)$/)
            if (tokens[idx].nesting === 1) {
              return `<div class="custom-block tip"><p class="custom-block-title">${m[1] || 'Tip'}</p>\n`
            } else {
              return '</div>\n'
            }
          }
        })
        md.use(container, 'warning', {
          validate: (params) => params.trim().match(/^warning\s+(.*)$/),
          render: (tokens, idx) => {
            const m = tokens[idx].info.trim().match(/^warning\s+(.*)$/)
            if (tokens[idx].nesting === 1) {
              return `<div class="custom-block warning"><p class="custom-block-title">${m[1] || 'Warning'}</p>\n`
            } else {
              return '</div>\n'
            }
          }
        })
        md.use(container, 'danger', {
          validate: (params) => params.trim().match(/^danger\s+(.*)$/),
          render: (tokens, idx) => {
            const m = tokens[idx].info.trim().match(/^danger\s+(.*)$/)
            if (tokens[idx].nesting === 1) {
              return `<div class="custom-block danger"><p class="custom-block-title">${m[1] || 'Danger'}</p>\n`
            } else {
              return '</div>\n'
            }
          }
        })
        md.use(container, 'details', {
          validate: (params) => params.trim().match(/^details\s+(.*)$/),
          render: (tokens, idx) => {
            const m = tokens[idx].info.trim().match(/^details\s+(.*)$/)
            if (tokens[idx].nesting === 1) {
              return `<details class="custom-block details"><summary>${m[1] || 'Details'}</summary>\n`
            } else {
              return '</details>\n'
            }
          }
        })
        md.use(abbr)
        md.use(deflist)
        md.use(mark)
        md.use(sub)
        md.use(sup)
      }
    },

    vite: {
      optimizeDeps: {
        include: ['mermaid', 'katex']
      },
      ssr: {
        noExternal: ['mermaid', 'katex']
      },
      css: {
        preprocessorOptions: {
          scss: {
            additionalData: `@import "./theme/variables.scss";`
          }
        }
      }
    },

    sitemap: {
      hostname: 'https://docs.your-domain.com',
      transformItems: (items) => {
        return items.filter((item) => !item.url.includes('404'))
      }
    },

    cleanUrls: true,
    metaChunk: true
})
