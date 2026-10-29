# Configuration Guide

Complete reference for configuring the Multi-Agent Workflow System.

## Configuration Hierarchy

```
config/
├── profiles/              # Agent profiles
│   ├── sdlc-planner.yaml
│   ├── sdlc-architect.yaml
│   ├── sdlc-developer.yaml
│   ├── sdlc-reviewer.yaml
│   ├── sdlc-tester.yaml
│   ├── sdlc-release.yaml
│   └── sdlc-security.yaml
├── tools/                 # Tool configurations
│   ├── kanban.yaml
│   ├── terminal.yaml
│   ├── web.yaml
│   └── ...
├── skills/                # Skill definitions
├── dispatcher.yaml        # Dispatcher settings
├── quality-gates.yaml     # Quality gate thresholds
└── logging.yaml           # Logging configuration
```

## Environment Variables (`.env`)

### Required
```bash
# LLM Provider
OPENROUTER_API_KEY=sk-or-v1-xxxxxxxxxxxxx
DEFAULT_MODEL=nvidia/nemotron-3-ultra-550b-a55b:free

# Database
DATABASE_URL=sqlite:///data/kanban.db
```

### Optional — Core
```bash
# Server
HOST=0.0.0.0
PORT=8000
FRONTEND_PORT=3000

# Logging
LOG_LEVEL=INFO
LOG_FORMAT=json

# Dispatcher
DISPATCHER_POLL_INTERVAL=5
DISPATCHER_MAX_CONCURRENT=10
DISPATCHER_HEARTBEAT_INTERVAL=60

# Workspace
WORKSPACE_BASE_DIR=/tmp/hermes-workspaces
WORKSPACE_CLEANUP_TTL=86400
```

### Optional — LLM Providers
```bash
# OpenRouter
OPENROUTER_BASE_URL=https://openrouter.ai/api/v1
OPENROUTER_DEFAULT_PROVIDER=openrouter

# Anthropic (direct)
ANTHROPIC_API_KEY=sk-ant-xxxxxxxxxxxxx

# Ollama (local)
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_DEFAULT_MODEL=llama3.1:70b

# Custom OpenAI-compatible
CUSTOM_API_BASE=https://api.example.com/v1
CUSTOM_API_KEY=sk-xxxxxxxxxxxxx
```

### Optional — Integrations
```bash
# GitHub
GITHUB_TOKEN=ghp_xxxxxxxxxxxxx
GITHUB_WEBHOOK_SECRET=xxxxxxxxxxxxx

# GitLab
GITLAB_TOKEN=glpat-xxxxxxxxxxxxx
GITLAB_URL=https://gitlab.com

# Slack
SLACK_BOT_TOKEN=xoxb-xxxxxxxxxxxxx
SLACK_SIGNING_SECRET=xxxxxxxxxxxxx
```

## Agent Profiles (`config/profiles/*.yaml`)

Each profile defines an agent's behavior, capabilities, and model.

### Schema
```yaml
name: string                    # Profile identifier (matches assignee)
model:
  provider: string              # openrouter, anthropic, ollama, custom
  name: string                  # Model identifier
  temperature: float            # 0.0-2.0 (default: 0.3)
  max_tokens: integer           # Max response tokens (default: 8192)
  top_p: float                  # Nucleus sampling (default: 0.95)
tools:                          # List of enabled toolsets
  - string
skills:                         # Pre-loaded skills
  - string
prompt: string                  # System prompt (multi-line)
env:                            # Profile-specific env vars
  KEY: value
```

### Example: `sdlc-developer.yaml`
```yaml
name: sdlc-developer
model:
  provider: openrouter
  name: nvidia/nemotron-3-ultra-550b-a55b:free
  temperature: 0.2
  max_tokens: 16384
tools:
  - kanban
  - terminal
  - read_file
  - write_file
  - patch
  - search_files
  - execute_code
  - skill_view
  - skill_manage
skills:
  - python
  - test-driven-development
  - systematic-debugging
  - codebase-inspection
  - requesting-code-review
prompt: |
  You are DEVELOPER, a senior-level autonomous software engineering agent
  operating inside a controlled multi-agent development pipeline.
  ...
  [Full prompt from SYSTEM PROMPT — DEVELOPER v2]
env:
  PYTHONPATH: /workspace
  UV_CACHE_DIR: /tmp/uv-cache
```

### Profile Inheritance
Profiles can extend a base profile:
```yaml
extends: base-developer
model:
  name: anthropic/claude-3.5-sonnet
tools:
  - browser  # Additional tool
```

## Tool Configuration (`config/tools/*.yaml`)

### Terminal Tool (`terminal.yaml`)
```yaml
default_timeout: 180
max_timeout: 600
default_workdir: /workspace
allow_background: true
pty_enabled: true
shell: /bin/bash
env:
  TERM: xterm-256color
  PYTHONUNBUFFERED: "1"
```

### Kanban Tool (`kanban.yaml`)
```yaml
default_board: default
default_tenant: ""
auto_create_board: true
max_task_limit: 200
attachment_max_size: 26214400  # 25 MB
attachment_allowed_types:
  - application/pdf
  - image/*
  - text/*
  - application/json
```

### Web Tool (`web.yaml`)
```yaml
search_backend: duckduckgo
search_max_results: 10
extract_char_limit: 15000
timeout: 30
user_agent: Hermes-Agent/1.0
```

## Dispatcher Configuration (`dispatcher.yaml`)

```yaml
poll_interval_seconds: 5
max_concurrent_workers: 10
worker_timeout_seconds: 3600
heartbeat_interval_seconds: 60
heartbeat_timeout_seconds: 300
retry_policy:
  max_attempts: 3
  base_delay_seconds: 60
  max_delay_seconds: 3600
  exponential_base: 2
queue:
  ready_priority_boost: 10
  blocked_retry_delay: 300
workspace:
  default_kind: scratch
  base_dir: /tmp/hermes-workspaces
  cleanup_on_complete: true
  cleanup_ttl_hours: 24
health_check:
  enabled: true
  interval_seconds: 30
  endpoint: /health
```

## Quality Gates Configuration (`quality-gates.yaml`)

```yaml
security_gate:
  enabled: true
  tools:
    - bandit
    - safety
    - trivy
  severity_threshold: high
  fail_on: [critical, high]

review_gate:
  enabled: true
  linters:
    - ruff
    - mypy
    - eslint
  formatters:
    - ruff_format
    - prettier
  max_line_length: 120
  fail_on_error: true
  fail_on_warning: false

quality_gate:
  enabled: true
  test_frameworks:
    - pytest
    - vitest
  coverage_threshold: 80
  coverage_type: line
  fail_on_coverage_below: true
  run_integration: true
  timeout_seconds: 300
```

## Skills Configuration

Skills are stored in `config/skills/` or `~/.hermes/skills/`. Each skill has:
```
skill-name/
├── SKILL.md           # Main skill definition
├── references/        # Reference files
├── templates/         # Template files
├── scripts/           # Executable scripts
└── assets/            # Static assets
```

### Loading Skills
```yaml
# In profile
skills:
  - python
  - test-driven-development
  - my-custom-skill
```

### Creating Skills
```bash
hermes-kanban skill create --name my-skill --category development
```

## Logging Configuration (`logging.yaml`)

```yaml
version: 1
disable_existing_loggers: false
formatters:
  json:
    format: "%(asctime)s %(levelname)s %(name)s %(message)s"
    class: pythonjsonlogger.jsonlogger.JsonFormatter
  console:
    format: "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    datefmt: "%H:%M:%S"
handlers:
  console:
    class: logging.StreamHandler
    formatter: console
    stream: ext://sys.stdout
  file:
    class: logging.handlers.RotatingFileHandler
    formatter: json
    filename: logs/hermes.log
    maxBytes: 10485760
    backupCount: 5
root:
  level: INFO
  handlers: [console, file]
loggers:
  hermes.dispatcher:
    level: DEBUG
  hermes.kanban:
    level: INFO
  hermes.worker:
    level: DEBUG
```

## Docker Compose Override

Create `docker-compose.override.yml` for local customization:

```yaml
version: '3.8'
services:
  api:
    environment:
      - LOG_LEVEL=DEBUG
    volumes:
      - ./config:/app/config:ro
      - ./data:/app/data
    ports:
      - "8000:8000"
  frontend:
    environment:
      - VITE_API_URL=http://localhost:8000
    ports:
      - "3000:3000"
  worker:
    deploy:
      replicas: 3
    environment:
      - WORKER_CONCURRENCY=2
```

## Secrets Management

Never commit secrets to git. Use:
1. **`.env` file** (gitignored) for local development
2. **Docker secrets** for production:
   ```yaml
   secrets:
     openrouter_api_key:
       file: ./secrets/openrouter_api_key.txt
   services:
     api:
       secrets:
         - openrouter_api_key
   ```
3. **External secret managers** (HashiCorp Vault, AWS Secrets Manager) via sidecar

## Validation

Validate your configuration:
```bash
# Check YAML syntax
python -c "import yaml; yaml.safe_load(open('config/profiles/sdlc-developer.yaml'))"

# Run config doctor
hermes-kanban doctor --config config/
```

## Migration Guide

### From v0.0.x to v0.1.0
- `dispatcher.poll_interval` → `dispatcher.poll_interval_seconds`
- `quality_gates.coverage` → `quality_gates.quality_gate.coverage_threshold`
- Profile `tools` list now uses toolset names, not individual tools

---

*See also: [Getting Started](getting-started.md) | [Architecture Overview](architecture-overview.md)*