# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- Comprehensive user documentation (getting-started, CLI reference, configuration, architecture, troubleshooting)
- Developer documentation (API reference, agent development, Kanban integration, quality gates, ADR index)
- Operations documentation (deployment guide, Docker Compose reference, monitoring & alerting, backup & recovery, scaling guide)
- Documentation site with VitePress configuration

### Changed
- Updated agent system prompts for improved autonomy and safety
- Enhanced quality gate configuration with stricter linting rules

### Fixed
- Import sorting issues in test files (ruff I001)
- Line length violations in reviewer gate configuration

---

## [0.1.0-rc1] - 2025-10-16

### Added
- **Multi-Agent Orchestration** (ADR-010): Complete orchestration engine with dispatcher, worker pools, and Kanban coordination
- **Agent Runtime Loop** (ADR-011): Autonomous agent execution with plan-act-observe cycle, tool calling, and checkpointing
- **Tool Registry** (ADR-012): Extensible tool system with 20+ built-in tools (kanban, terminal, files, web, code, skills, browser)
- **MVP Core Subsystems** (ADR-013): API Gateway, Kanban Service, Dispatcher, Worker Runtime, Frontend, Quality Gates
- **Cross-Subsystem Integration** (ADR-014): Event-driven architecture with SQLite/PostgreSQL, Redis, WebSockets
- **Management API Authentication** (ADR-015): JWT + API key auth with RBAC scopes
- **SDLC Template Automation** (ADR-016): Automated task pipeline generation for feature development
- **Scoped Filesystem Profiles** (ADR-017): Workspace isolation with scoped filesystem boundaries
- **Hermes Independence** (ADR-001): Decoupled from Hermes desktop app, standalone deployment

### Security
- **Native Tool Boundaries**: Fenced native read-only tools with strict filesystem boundaries
- **Shell Command Isolation**: Secure shell execution with allowlist and output limits
- **HTTPS GET Boundary**: Trusted pinned HTTPS GET with TLS certificate pinning
- **Process Operations**: Restricted read-only process operations with validation
- **Token Validation**: Streaming token usage validation at source and agent boundary
- **Worker Output Validation**: Byte limits, UTF-8 validation, malformed output rejection
- **Scan/Batch Bounds**: Trusted scan and batch bounds enforcement
- **Supervisor Limits**: Strict supervisor limits for worker processes
- **Recovery Ledger**: SHA-256 redaction, malformed case handling, reconciliation validation
- **Tool Name Validation**: Recovery ledger tool name validation
- **Artifact Audit**: Agent artifact audit with batch verification

### Infrastructure
- **Docker Compose Stack**: Complete development and production deployment configurations
- **Kubernetes Helm Chart**: Production-ready K8s deployment with autoscaling
- **PostgreSQL Support**: Migration from SQLite to PostgreSQL with connection pooling (PgBouncer)
- **Redis Integration**: Caching, pub/sub, distributed locking for dispatcher HA
- **Nginx Reverse Proxy**: SSL termination, WebSocket support, static asset caching
- **Git Worktree Workspaces**: Isolated per-task workspaces with git integration

### Developer Experience
- **CLI Tool** (`hermes-kanban`): Full task/board management from terminal
- **Web UI**: React-based Kanban board with real-time updates (SSE)
- **Agent Profiles**: 7 built-in profiles (planner, architect, developer, reviewer, tester, release, security)
- **Skill System**: Reusable procedural knowledge packages with templates and scripts
- **Quality Gates**: 4-stage pipeline (Security → Review → Quality → Release)
- **Structured Logging**: JSON logging with correlation IDs
- **OpenTelemetry Tracing**: Distributed tracing with Tempo integration

### Testing
- **Unit Test Framework**: Pytest with 80% coverage threshold
- **Integration Tests**: Full pipeline E2E tests with Docker Compose
- **Security Scanning**: Bandit SAST, Safety dependency check, Trivy container scan, TruffleHog secrets
- **Linting**: Ruff (Python), MyPy (types), ESLint (TypeScript)
- **Mutation Testing**: Mutmut integration (optional)

### Documentation
- **Architecture Decision Records**: 9 ADRs documenting key architectural decisions
- **API Reference**: Complete REST API with examples
- **User Guide**: Getting started, CLI, configuration, architecture, troubleshooting
- **Developer Guide**: Agent development, Kanban integration, quality gates
- **Operations Guide**: Deployment, Docker Compose, monitoring, backup/recovery, scaling

---

## [0.0.1] - 2025-01-15

### Added
- Initial project structure
- Basic Kanban board implementation (SQLite)
- Simple dispatcher with single worker
- Minimal FastAPI service
- React frontend skeleton
- Basic agent loop prototype

---

## Release Notes Format

Each release includes:

1. **Overview** - High-level summary
2. **New Features** - User-facing additions
3. **Improvements** - Enhancements to existing features
4. **Bug Fixes** - Defect resolutions
5. **Breaking Changes** - Incompatible changes (with migration guide)
6. **Security Fixes** - Vulnerability patches
7. **Upgrade Guide** - Step-by-step migration instructions
8. **Contributors** - Acknowledgments

---

## Links

- [GitHub Releases](https://github.com/your-org/multi-agent-workflow/releases)
- [Documentation](https://docs.your-domain.com)
- [Issue Tracker](https://github.com/your-org/multi-agent-workflow/issues)