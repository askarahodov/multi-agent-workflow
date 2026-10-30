# Release Notes v0.1.0-rc1

**Release Date:** 2026-10-30  
**Release Type:** Release Candidate  
**Git Tag:** `v0.1.0-rc1` (annotated, SSH-signed)  
**Commit:** `42b5354` (main @ `v0.1.0-rc1`)  
**Verified Candidate:** `a613a54` (tree-identical to the tagged commit)

---

## Overview

This is the first release candidate of the Multi-Agent Workflow System — a production-ready platform for orchestrating autonomous AI agents that collaborate to solve complex software engineering tasks.

The system implements a complete SDLC pipeline with specialized agents (Planner, Architect, Developer, Reviewer, Tester, Release, Security) coordinated through a Kanban-based task management system with automated quality gates.

---

## New Features

### Core Orchestration
- **Multi-Agent Orchestration Engine** (ADR-010): Dispatcher with leader election, worker pool management, and task lifecycle automation
- **Agent Runtime Loop** (ADR-011): Autonomous plan-act-observe cycle with tool calling, checkpointing, and structured handoffs
- **Tool Registry** (ADR-012): 20+ built-in tools (Kanban, Terminal, Files, Web, Code, Skills, Browser) with extensible architecture
- **Kanban Task Management**: SQLite/PostgreSQL backend with full CRUD, dependencies, events, attachments, and multi-tenant isolation

### Agent Profiles (7 Built-in)
| Profile | Role | Key Capabilities |
|---------|------|------------------|
| `sdlc-planner` | Task decomposition & planning | Epic breakdown, acceptance criteria, dependency mapping |
| `sdlc-architect` | Technical design & architecture | ADR creation, system design, API contracts |
| `sdlc-developer` | Implementation & testing | Code generation, TDD, debugging, refactoring |
| `sdlc-reviewer` | Code review & quality gates | Linting, type checking, diff review, security scan |
| `sdlc-tester` | Test execution & validation | Unit/integration tests, coverage ≥80%, mutation testing |
| `sdlc-release` | Release automation | Git tags, Docker images, GitHub Releases, artifacts |
| `sdlc-security` | Security scanning | SAST, dependency scan, secret detection, container scan |

### Quality Gates (4-Stage Pipeline)
1. **Security Gate**: Bandit SAST, Safety dependency check, Trivy container scan, TruffleHog secrets
2. **Review Gate**: Ruff linting, MyPy type checking, Ruff format, import sorting, diff review
3. **Quality Gate**: Pytest unit tests (≥80% line coverage), integration tests, benchmarks
4. **Release Gate**: Signed git tags, version consistency, artifact checksums, GitHub Release

### Security Hardening (P8.3)
- Scoped Filesystem Profiles (ADR-017): Workspace isolation with path traversal prevention
- Native Tool Boundaries: Fenced read-only tools with strict allowlists
- Shell Command Isolation: Command validation, output limits, UTF-8 enforcement
- HTTPS GET Boundary: TLS certificate pinning, hostname verification
- Process Operations: Restricted read-only process inspection
- Token Validation: Streaming usage validation at source and agent boundary
- Worker Output Validation: Byte limits, malformed UTF-8 rejection
- Recovery Ledger: SHA-256 redaction, corruption detection, reconciliation validation

### Developer Experience
- **CLI Tool** (`hermes-kanban`): Full task/board management from terminal with JSON output
- **Web UI**: React 18 + TypeScript + Vite Kanban board with real-time SSE updates
- **Skill System**: Reusable procedural knowledge packages with templates and scripts
- **Structured Logging**: JSON logging with correlation IDs
- **OpenTelemetry Tracing**: Distributed tracing with Tempo integration
- **Documentation Site**: VitePress with Mermaid diagrams, full-text search

### Infrastructure
- **Docker Compose**: Development and production stacks with nginx, PostgreSQL, Redis
- **Kubernetes Helm Chart**: Production deployment with HPA, leader election, PostgreSQL operator
- **Git Worktree Workspaces**: Per-task isolated workspaces with git integration
- **CI/CD Ready**: GitHub Actions workflows for quality gates and release automation

---

## Improvements

- **Agent Prompts**: Refined system prompts for all 7 profiles with explicit completion criteria
- **Quality Gate Config**: Stricter linting rules (ruff line-length 120, MyPy strict mode)
- **Dispatcher Performance**: Batch dispatch, priority queues, configurable poll intervals
- **Worker Concurrency**: Per-profile concurrency tuning (2-8 based on workload type)
- **Documentation**: Comprehensive user guide, developer guide, operations guide (15+ files)
- **ADR Coverage**: 8 Architecture Decision Records documenting all major decisions

---

## Bug Fixes

- Fixed import sorting issues (ruff I001) in test files
- Resolved line length violations in reviewer gate configuration
- Fixed worker heartbeat timeout handling
- Corrected SQLite database locking with single dispatcher instance
- Fixed frontend API URL configuration for production deployment
- Resolved mermaid diagram rendering in documentation site
- Fixed VitePress build with proper ESM module handling

---

## Breaking Changes

### Database
- **SQLite → PostgreSQL**: Production deployments now require PostgreSQL (SQLite still supported for development)
- Migration script provided: `scripts/migrate-sqlite-to-postgres.sh`

### API
- **Task Completion Contract**: `completion_contract` field now required for worktree tasks (values: `local-only`, `OWNER/REPO`, `PR_URL`)
- **Webhook Signature**: `X-Hermes-Signature` header now uses SHA256 HMAC (was SHA1)

### Configuration
- **Dispatcher Config**: `poll_interval` renamed to `poll_interval_seconds`
- **Quality Gates**: `coverage` renamed to `coverage_threshold` with explicit `coverage_type` (line/branch)

### Migration Guide
```bash
# 1. Update config files
# dispatcher.yaml: poll_interval -> poll_interval_seconds
# quality-gates.yaml: coverage -> coverage_threshold, add coverage_type: line

# 2. Migrate database (production)
./scripts/migrate-sqlite-to-postgres.sh

# 3. Update webhook consumers to verify SHA256 signature
```

---

## Security Fixes

- **CVE-2024-xxxx**: Path traversal in workspace file operations (fixed via ADR-017 scoped filesystem)
- **CVE-2024-xxxx**: Command injection in shell tool (fixed via allowlist and validation)
- **CVE-2024-xxxx**: SSRF in web fetch tool (fixed via egress allowlist and timeout)
- **CVE-2024-xxxx**: Secret leakage in logs (fixed via structured redaction)

---

## Upgrade Guide

### From v0.0.x (Development)

1. **Backup Database**
   ```bash
   cp data/kanban.db data/kanban.db.backup
   ```

2. **Pull Latest Images**
   ```bash
   docker compose pull
   ```

3. **Update Configuration**
   ```bash
   # Compare .env with .env.example
   # Update dispatcher.yaml and quality-gates.yaml per breaking changes
   ```

4. **Migrate Database (if using PostgreSQL)**
   ```bash
   ./scripts/migrate-sqlite-to-postgres.sh
   ```

5. **Deploy**
   ```bash
   docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d
   ```

6. **Verify**
   ```bash
   curl https://your-domain.com/health
   hermes-kanban list --limit 5
   ```

### From Pre-RC (Internal)

No migration needed — this is the first tagged release.

---

## Contributors

- @orchestrator — Pipeline orchestration, task management, release automation
- @sdlc-architect — System architecture, ADRs, security design
- @sdlc-developer — Core implementation, agent loop, tool registry, quality gates
- @sdlc-planner — Task decomposition, sprint planning, epic management
- @sdlc-reviewer — Code review automation, quality gate implementation
- @sdlc-tester — Test infrastructure, coverage enforcement, integration tests
- @sdlc-release — Release automation, Docker images, GitHub Releases
- @sdlc-security — Security hardening, vulnerability scanning, compliance
- @sdlc-researcher — Technology evaluation, best practices, documentation

---

## Artifacts

| Artifact | SHA256 |
|----------|--------|
| `multi-agent-workflow-v0.1.0-rc1.tar.gz` | `pending` |
| `multi-agent-workflow-orchestration-server:v0.1.0-rc1` | `pending` |
| `multi-agent-workflow-agent-management:v0.1.0-rc1` | `pending` |
| `multi-agent-workflow-runtime-hardening:v0.1.0-rc1` | `pending` |
| `multi-agent-workflow-frontend:v0.1.0-rc1` | `pending` |
| `multi-agent-workflow-quality-gates:v0.1.0-rc1` | `pending` |

*Checksums will be published with the GitHub Release.*

---

## Links

- **GitHub Release:** https://github.com/your-org/multi-agent-workflow/releases/tag/v0.1.0-rc1
- **Documentation:** https://docs.your-domain.com
- **Docker Images:** https://github.com/your-org/multi-agent-workflow/pkgs/container/multi-agent-workflow
- **Issues:** https://github.com/your-org/multi-agent-workflow/issues
- **Discussions:** https://github.com/your-org/multi-agent-workflow/discussions

---

*This release candidate is intended for testing and validation. Report any issues via GitHub Issues. The stable v0.1.0 release will follow after RC validation.*