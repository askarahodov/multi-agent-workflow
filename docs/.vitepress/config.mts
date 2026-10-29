import { defineConfig } from 'vitepress'
import { withMermaid } from 'vitepress-plugin-mermaid'
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
import katex from 'markdown-it-katex'

export default withMermaid(
  defineConfig({
    lang: 'en-US',
    title: 'Multi-Agent Workflow System',
    description: 'Autonomous AI agent orchestration platform for software engineering',
    appearance: 'dark',
    
    head: [
      ['link', { rel: 'icon', href: '/favicon.ico' }],
      ['link', { rel: 'preconnect', href: 'https://fonts.googleapis.com' }],
      ['link', { rel: 'preconnect', href: 'https://fonts.gstatic.com', crossorigin: '' }],
      ['link', { rel: 'stylesheet', href: 'https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap' }],
      ['meta', { name: 'theme-color', content: '#1e1e2e' }],
      ['meta', { name: 'og:type', content: 'website' }],
      ['meta', { name: 'og:title', content: 'Multi-Agent Workflow System' }],
      ['meta', { name: 'og:description', content: 'Autonomous AI agent orchestration platform for software engineering' }],
      ['meta', { name: 'twitter:card', content: 'summary_large_image' }]
    ],

    themeConfig: {
      logo: '/logo.svg',
      
      nav: [
        { text: 'Guide', link: '/guide/getting-started', activeMatch: '^/guide/' },
        { text: 'Developer', link: '/developer/api-reference', activeMatch: '^/developer/' },
        { text: 'Operations', link: '/operations/deployment-guide', activeMatch: '^/operations/' },
        { text: 'Architecture', link: '/architecture/adr-index', activeMatch: '^/architecture/' },
        { text: 'Releases', link: '/releases/', activeMatch: '^/releases/' },
        {
          text: 'v0.1.0-rc1',
          items: [
            { text: 'Changelog', link: '/changelog' },
            { text: 'Release Notes', link: '/releases/v0.1.0-rc1' },
            { text: 'GitHub', link: 'https://github.com/your-org/multi-agent-workflow' }
          ]
        }
      ],

      sidebar: {
        '/guide/': [
          {
            text: 'Getting Started',
            items: [
              { text: 'Introduction', link: '/guide/getting-started' },
              { text: 'CLI Reference', link: '/guide/cli-reference' },
              { text: 'Configuration', link: '/guide/configuration' },
              { text: 'Architecture Overview', link: '/guide/architecture-overview' },
              { text: 'Troubleshooting', link: '/guide/troubleshooting' }
            ]
          }
        ],
        '/developer/': [
          {
            text: 'API Reference',
            items: [
              { text: 'REST API', link: '/developer/api-reference' },
              { text: 'Agent Development', link: '/developer/agent-development' },
              { text: 'Kanban Integration', link: '/developer/kanban-integration' },
              { text: 'Quality Gates', link: '/developer/quality-gates' }
            ]
          },
          {
            text: 'Architecture Decisions',
            items: [
              { text: 'ADR Index', link: '/developer/architecture-decisions/adr-index' },
              { text: 'ADR-001: Hermes Independence', link: '/developer/architecture-decisions/001-hermes-independence' },
              { text: 'ADR-010: Multi-Agent Orchestration', link: '/developer/architecture-decisions/ADR-010-multi-agent-orchestration' },
              { text: 'ADR-011: Agent Runtime Loop', link: '/developer/architecture-decisions/ADR-011-agent-runtime-loop' },
              { text: 'ADR-012: Tool Registry', link: '/developer/architecture-decisions/ADR-012-tool-registry' },
              { text: 'ADR-013: MVP Core Subsystems', link: '/developer/architecture-decisions/ADR-013-mvp-core-subsystems' },
              { text: 'ADR-014: Cross-Subsystem Integration', link: '/developer/architecture-decisions/ADR-014-cross-subsystem-integration' },
              { text: 'ADR-015: Management API Auth', link: '/developer/architecture-decisions/ADR-015-management-api-auth' },
              { text: 'ADR-016: SDLC Template Automation', link: '/developer/architecture-decisions/ADR-016-sdlc-template-automation' }
            ]
          }
        ],
        '/operations/': [
          {
            text: 'Deployment',
            items: [
              { text: 'Deployment Guide', link: '/operations/deployment-guide' },
              { text: 'Docker Compose Reference', link: '/operations/docker-compose-reference' }
            ]
          },
          {
            text: 'Observability',
            items: [
              { text: 'Monitoring & Alerting', link: '/operations/monitoring-alerting' }
            ]
          },
          {
            text: 'Reliability',
            items: [
              { text: 'Backup & Recovery', link: '/operations/backup-recovery' },
              { text: 'Scaling Guide', link: '/operations/scaling-guide' }
            ]
          }
        ],
        '/architecture/': [
          {
            text: 'Architecture Decisions',
            items: [
              { text: 'ADR Index', link: '/architecture/adr-index' }
            ]
          }
        ],
        '/releases/': [
          {
            text: 'Releases',
            items: [
              { text: 'v0.1.0-rc1', link: '/releases/v0.1.0-rc1' }
            ]
          }
        ]
      },

      editLink: {
        pattern: 'https://github.com/your-org/multi-agent-workflow/edit/main/docs/:path',
        text: 'Edit this page on GitHub'
      },

      lastUpdated: {
        text: 'Last updated',
        formatOptions: {
          dateStyle: 'short',
          timeStyle: 'short'
        }
      },

      docFooter: {
        prev: 'Previous page',
        next: 'Next page'
      },

      outline: {
        level: [2, 3],
        label: 'On this page'
      },

      socialLinks: [
        { icon: 'github', link: 'https://github.com/your-org/multi-agent-workflow' },
        { icon: 'discord', link: 'https://discord.gg/your-invite' },
        { icon: 'twitter', link: 'https://twitter.com/your-handle' }
      ],

      footer: {
        message: 'Released under the MIT License.',
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
      theme: {
        light: 'github-light',
        dark: 'github-dark'
      },
      lineNumbers: true,
      config: (md) => {
        md.use(anchor, {
          slugify: (s) => s.toLowerCase().replace(/\s+/g, '-').replace(/[^\w-]+/g, ''),
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
        md.use(katex, { throwOnError: false, errorColor: ' #cc0000' })
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
)