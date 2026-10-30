# Docker Compose Reference

Reference for the local-development Docker Compose stack. The repository-root
`docker-compose.yml` is the single source of truth and is reproduced below; the
per-subsystem `Dockerfile` paths in this document mirror `docker compose config`
and the `dockerfile:` keys in that file. Specialised runtime/QA stacks live in
the `compose.*.yml` files (see [Specialised Stacks](#specialised-stacks)).

## File Structure

```
.
├── docker-compose.yml                    # Base stack (all services)
├── docker-compose.override.yml.example   # Copy to docker-compose.override.yml (git-ignored)
├── .env.example                          # Copy to .env for host-port/key overrides (git-ignored)
├── compose.*.yml                         # Specialised runtime/QA stacks (see below)
└── <subsystem>/Dockerfile                # One dev-mode Dockerfile per service
```

## Base Configuration (`docker-compose.yml`)

```yaml
# Multi-Agent Workflow Platform - Local Development Stack
# Single command: make up  (docker compose up -d --build)
#
# Python services install their runtime dependencies into /app/.venv at build
# time; docker compose seeds an anonymous /app/.venv volume from the image so
# the bind-mounted source tree (./<service>:/app) never shadows the venv.
# Each service exposes a container healthcheck so `docker compose ps` shows
# every container as (healthy).

services:
  # Shared PostgreSQL for services that need it (optional; services default to SQLite)
  postgres:
    image: postgres:16-alpine
    environment:
      POSTGRES_USER: workflow
      POSTGRES_PASSWORD: workflow
      POSTGRES_DB: workflow
    ports:
      - "127.0.0.1:${POSTGRES_HOST_PORT:-5432}:5432"
    volumes:
      - postgres_data:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U workflow"]
      interval: 5s
      timeout: 5s
      retries: 10

  # Orchestration Server - Port 8000
  orchestration-server:
    build:
      context: .
      dockerfile: orchestration-server/Dockerfile
    ports:
      - "127.0.0.1:${ORCH_HOST_PORT:-18000}:8000"
    environment:
      - ORCH_DATABASE_URL=sqlite+aiosqlite:///./orchestration.db
      - AUTH_ENABLED=false # LOCAL DEV ONLY; never expose this stack beyond loopback.
      - SHARED_SECRET=dev-secret-change-in-production
      - LOG_LEVEL=INFO
    depends_on:
      - postgres
    volumes:
      - ./orchestration-server:/app
      - /app/.venv
    command: uvicorn orchestration_server.main:app --host 0.0.0.0 --port 8000 --reload
    healthcheck:
      test: ["CMD", "python", "-c", "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health',timeout=3).status==200 else 1)"]
      interval: 10s
      timeout: 5s
      retries: 10
      start_period: 15s

  # Agent Management - Port 8001
  agent-management:
    build:
      context: .
      dockerfile: agent-management/Dockerfile
    ports:
      - "127.0.0.1:${AGENT_MGMT_HOST_PORT:-8001}:8001"
    environment:
      - AGENT_MGMT_DATABASE_URL=sqlite+aiosqlite:///./agent_management.db
      # Stable encryption key for provider credentials; set in git-ignored .env before entering real keys.
      - AUTH_ENCRYPTION_KEY=${AUTH_ENCRYPTION_KEY:-}
      - AUTH_ENABLED=false # LOCAL DEV ONLY; never expose this stack beyond loopback.
      - SHARED_SECRET=dev-secret-change-in-production
      - LOG_LEVEL=INFO
    depends_on:
      - postgres
    volumes:
      - ./agent-management:/app
      - /app/.venv
    command: uvicorn agent_management.main:app --host 0.0.0.0 --port 8001 --reload
    healthcheck:
      test: ["CMD", "python", "-c", "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8001/health',timeout=3).status==200 else 1)"]
      interval: 10s
      timeout: 5s
      retries: 10
      start_period: 15s

  # Runtime Hardening - Port 8002
  runtime-hardening:
    build:
      context: .
      dockerfile: runtime-hardening/Dockerfile
    ports:
      - "127.0.0.1:${RUNTIME_HOST_PORT:-8002}:8002"
    environment:
      - SHARED_SECRET=dev-secret-change-in-production
      - AUTH_ENABLED=false # LOCAL DEV ONLY; never expose this stack beyond loopback.
      - LOG_LEVEL=INFO
    # Required for container runtime operations
    privileged: true
    volumes:
      - ./runtime-hardening:/app
      - /app/.venv
      - /var/run/docker.sock:/var/run/docker.sock
      - /sys/fs/cgroup:/sys/fs/cgroup:ro
    command: uvicorn runtime.main:app --host 0.0.0.0 --port 8002 --reload
    healthcheck:
      test: ["CMD", "python", "-c", "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8002/health',timeout=3).status==200 else 1)"]
      interval: 10s
      timeout: 5s
      retries: 10
      start_period: 15s

  # Frontend - Port 5173 (Vite dev server)
  frontend:
    build:
      context: .
      dockerfile: frontend/Dockerfile
    ports:
      - "127.0.0.1:${FRONTEND_HOST_PORT:-5173}:5173"
    environment:
      - VITE_API_URL=http://localhost:${ORCH_HOST_PORT:-18000}
      - VITE_AGENT_MGMT_URL=http://localhost:${AGENT_MGMT_HOST_PORT:-8001}
      - VITE_RUNTIME_URL=http://localhost:${RUNTIME_HOST_PORT:-8002}
      # These addresses are resolved inside the Docker network, not on the host.
      - ORCH_UPSTREAM=http://orchestration-server:8000
      - AGENT_MGMT_UPSTREAM=http://agent-management:8001
    volumes:
      - ./frontend:/app
      - /app/node_modules
      - /app/dist
    command: npm run dev -- --host 0.0.0.0
    healthcheck:
      test: ["CMD", "node", "-e", "fetch('http://127.0.0.1:5173').then(r=>process.exit(r.ok?0:1)).catch(()=>process.exit(1))"]
      interval: 10s
      timeout: 5s
      retries: 10
      start_period: 15s

  # Quality Gates - Port 8003
  quality-gates:
    build:
      context: .
      dockerfile: quality-gates/Dockerfile
    ports:
      - "127.0.0.1:${QG_HOST_PORT:-8003}:8003"
    environment:
      - DATABASE_URL=sqlite+aiosqlite:///./quality_gates.db
      - SHARED_SECRET=dev-secret-change-in-production
      - AUTH_ENABLED=false # LOCAL DEV ONLY; never expose this stack beyond loopback.
      - LOG_LEVEL=INFO
    volumes:
      - ./quality-gates:/app
      - /app/.venv
    command: python -m quality_gates.main --host 0.0.0.0 --port 8003
    healthcheck:
      test: ["CMD", "python", "-c", "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8003/health',timeout=3).status==200 else 1)"]
      interval: 10s
      timeout: 5s
      retries: 10
      start_period: 15s

volumes:
  postgres_data:
```

## Service ↔ Build Mapping

| Compose service | Build context | Dockerfile | Container port | Default host port |
|-----------------|---------------|------------|----------------|-------------------|
| `orchestration-server` | `.` | `orchestration-server/Dockerfile` | 8000 | 18000 |
| `agent-management`     | `.` | `agent-management/Dockerfile`     | 8001 | 8001 |
| `runtime-hardening`    | `.` | `runtime-hardening/Dockerfile`    | 8002 | 8002 |
| `frontend`             | `.` | `frontend/Dockerfile`             | 5173 | 5173 |
| `quality-gates`        | `.` | `quality-gates/Dockerfile`        | 8003 | 8003 |
| `postgres`             | (image `postgres:16-alpine`) | — | 5432 | 5432 |

Each published release image is named `ghcr.io/<repo>-<compose-service>:<version>`
(e.g. `ghcr.io/<repo>-orchestration-server:v0.1.0-rc1`) and is built by
`.github/workflows/release.yml` from the **release** Dockerfile of each service
(`<subsystem>/Dockerfile.release`), with the repository root as context:

| Compose service | Release Dockerfile (context `.`) |
|-----------------|----------------------------------|
| `orchestration-server` | `orchestration-server/Dockerfile.release` |
| `agent-management`     | `agent-management/Dockerfile.release`     |
| `runtime-hardening`    | `runtime-hardening/Dockerfile.release`    |
| `frontend`             | `frontend/Dockerfile.release`             |
| `quality-gates`        | `quality-gates/Dockerfile.release`        |

> **The `<subsystem>/Dockerfile` files above are development images** — used only
> by `docker-compose.yml`. Each installs the runtime dependencies into
> `/app/.venv` (Python services) or `node_modules` (frontend) at build time but
> does **not** COPY the application source. The source tree is bind-mounted
> (`./<subsystem>:/app`) and the dependency volume is seeded from the image so the
> bind mount never shadows it.
>
> The **release images** (`<subsystem>/Dockerfile.release`) are source-baked: they
> COPY `shared/` and the subsystem source, install the packages, and run as a
> dedicated non-root user (uid/gid 10001–10005). They are **standalone-runnable** —
> `docker run` boots the service with no host bind mounts — and declare a
> `HEALTHCHECK`. `runtime-hardening` is privileged by design and needs the Docker
> socket plus cgroup mounts for its container/cgroup features; its API still boots
> and serves `/health` without them.

## Service Details

### `orchestration-server` — `orchestration-server/Dockerfile`

FastAPI app on port 8000 (`uvicorn orchestration_server.main:app`).

```dockerfile
# orchestration-server — local development image.
# Build context is the repository ROOT (docker compose sets context: ".").
# Runtime dependencies are installed into /app/.venv so that docker compose's
# anonymous /app/.venv volume is seeded; the worker source itself is
# bind-mounted from the host by docker-compose.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Local `shared` package (dependencies reference it by absolute path).
COPY shared /tmp/shared
RUN python -m venv /app/.venv \
    && /app/.venv/bin/pip install --upgrade pip \
    && /app/.venv/bin/pip install /tmp/shared \
    && rm -rf /tmp/shared

# Runtime dependencies declared in orchestration-server/pyproject.toml.
RUN /app/.venv/bin/pip install \
    "fastapi>=0.115" \
    "uvicorn[standard]>=0.30" \
    "sqlalchemy[asyncio]>=2.0" \
    "pydantic>=2.7" \
    "aiosqlite>=0.20" \
    "jsonschema>=4.20" \
    "httpx>=0.27"

ENV PATH="/app/.venv/bin:${PATH}"

EXPOSE 8000
CMD ["uvicorn", "orchestration_server.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]
```

Health endpoint: `GET /health`.

### `agent-management` — `agent-management/Dockerfile`

FastAPI app on port 8001 (`uvicorn agent_management.main:app`).

```dockerfile
# agent-management — local development image.
# Build context is the repository ROOT (docker compose sets context: ".").
# Runtime dependencies are installed into /app/.venv so that docker compose's
# anonymous /app/.venv volume is seeded; the worker source itself is
# bind-mounted from the host by docker-compose.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Local `shared` package (dependencies reference it by absolute path).
COPY shared /tmp/shared
RUN python -m venv /app/.venv \
    && /app/.venv/bin/pip install --upgrade pip \
    && /app/.venv/bin/pip install /tmp/shared \
    && rm -rf /tmp/shared

# Runtime dependencies declared in agent-management/pyproject.toml, plus
# `cryptography` which the code imports (agent_management/crypto.py) but which
# pyproject.toml does not list.
RUN /app/.venv/bin/pip install \
    "fastapi>=0.115" \
    "uvicorn[standard]>=0.30" \
    "sqlalchemy[asyncio]>=2.0" \
    "pydantic>=2.7" \
    "aiosqlite>=0.20" \
    "httpx>=0.27" \
    "cryptography>=42"

ENV PATH="/app/.venv/bin:${PATH}"

EXPOSE 8001
CMD ["uvicorn", "agent_management.main:app", "--host", "0.0.0.0", "--port", "8001", "--reload"]
```

Health endpoint: `GET /health`.

### `runtime-hardening` — `runtime-hardening/Dockerfile`

FastAPI app on port 8002 (`uvicorn runtime.main:app`). The service is
`privileged` and mounts `/var/run/docker.sock` plus a read-only cgroup mount
because it manages agent containers/cgroups.

```dockerfile
# runtime-hardening — local development image.
# Build context is the repository ROOT (docker compose sets context: ".").
# Runtime dependencies are installed into /app/.venv so that docker compose's
# anonymous /app/.venv volume is seeded; the worker source itself is
# bind-mounted from the host by docker-compose. The service mounts /var/run/
# docker.sock and is privileged because it manages agent containers/cgroups.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Local `shared` package (dependencies reference it by absolute path).
COPY shared /tmp/shared
RUN python -m venv /app/.venv \
    && /app/.venv/bin/pip install --upgrade pip \
    && /app/.venv/bin/pip install /tmp/shared \
    && rm -rf /tmp/shared

# Runtime dependencies declared in runtime-hardening/pyproject.toml.
RUN /app/.venv/bin/pip install \
    "pydantic>=2.7" \
    "pydantic-settings>=2.3" \
    "pyyaml>=6.0" \
    "fastapi>=0.111" \
    "uvicorn>=0.30" \
    "prometheus-client>=0.20"

ENV PATH="/app/.venv/bin:${PATH}"

EXPOSE 8002
CMD ["uvicorn", "runtime.main:app", "--host", "0.0.0.0", "--port", "8002", "--reload"]
```

Health endpoint: `GET /health`.

### `frontend` — `frontend/Dockerfile`

Vite dev server on port 5173 (`npm run dev -- --host 0.0.0.0`).

```dockerfile
# frontend — local development image (Vite dev server).
# Build context is the repository ROOT (docker compose sets context: ".").
# node_modules are installed at build time and docker compose's anonymous
# /app/node_modules volume is seeded from them; the source itself is
# bind-mounted from the host so the dev server hot-reloads.
FROM node:22-alpine

ENV NODE_ENV=development

WORKDIR /app

COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci

EXPOSE 5173
CMD ["npm", "run", "dev", "--", "--host", "0.0.0.0"]
```

### `quality-gates` — `quality-gates/Dockerfile`

API on port 8003 (`python -m quality_gates.main`).

```dockerfile
# quality-gates — local development image.
# Build context is the repository ROOT (docker compose sets context: ".").
# Runtime dependencies are installed into /app/.venv so that docker compose's
# anonymous /app/.venv volume is seeded; the worker source itself is
# bind-mounted from the host by docker-compose. The API imports shared auth and
# security middleware and therefore requires the first-party shared package.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

COPY shared /tmp/shared
RUN python -m venv /app/.venv \
    && /app/.venv/bin/pip install --upgrade pip \
    && /app/.venv/bin/pip install /tmp/shared \
    && rm -rf /tmp/shared

# Runtime dependencies declared in quality-gates/pyproject.toml.
RUN /app/.venv/bin/pip install \
    "fastapi>=0.115" \
    "uvicorn[standard]>=0.30" \
    "sqlalchemy[asyncio]>=2.0" \
    "pydantic>=2.7" \
    "aiosqlite>=0.20" \
    "httpx>=0.27"

ENV PATH="/app/.venv/bin:${PATH}"

EXPOSE 8003
CMD ["python", "-m", "quality_gates.main", "--host", "0.0.0.0", "--port", "8003"]
```

Health endpoint: `GET /health`.

## Environment Variables (`.env.example`)

| Variable | Default | Description |
|----------|---------|-------------|
| `AUTH_ENCRYPTION_KEY` | (empty) | Base64-encoded 32-byte key for provider-credential encryption; set in git-ignored `.env`. |
| `ORCH_HOST_PORT` | `18000` | Host port mapped to `orchestration-server:8000`. |
| `AGENT_MGMT_HOST_PORT` | `8001` | Host port mapped to `agent-management:8001`. |
| `RUNTIME_HOST_PORT` | `8002` | Host port mapped to `runtime-hardening:8002`. |
| `QG_HOST_PORT` | `8003` | Host port mapped to `quality-gates:8003`. |
| `FRONTEND_HOST_PORT` | `5173` | Host port mapped to `frontend:5173`. |
| `POSTGRES_HOST_PORT` | `5432` | Host port mapped to `postgres:5432`. |

All host port bindings are to `127.0.0.1` (loopback only). The dev stack runs
with `AUTH_ENABLED=false`; never expose it beyond loopback.

## Overrides (`docker-compose.override.yml.example`)

Copy the example to `docker-compose.override.yml` (git-ignored) to adjust a
local stack, e.g. point a service at PostgreSQL instead of SQLite:

```yaml
services:
  orchestration-server:
    environment:
      - ORCH_DATABASE_URL=postgresql+asyncpg://workflow:workflow@postgres:5432/workflow
    depends_on:
      postgres:
        condition: service_healthy
```

## Common Commands

```bash
# Start / stop the whole stack (also available via `make up` / `make down`)
docker compose up -d --build
docker compose down
docker compose down -v            # also remove volumes

# Status and logs
docker compose ps
docker compose logs -f --tail=100
docker compose logs -f orchestration-server

# Restart / rebuild a single service
docker compose restart quality-gates
docker compose up -d --build agent-management

# Exec into a container
docker compose exec orchestration-server bash
```

## Networking

All services share the default Compose network and reach each other by service
name (`orchestration-server:8000`, `agent-management:8001`, etc.).

| Service | Container port | Default host port (loopback) |
|---------|----------------|------------------------------|
| orchestration-server | 8000 | 18000 |
| agent-management     | 8001 | 8001 |
| runtime-hardening    | 8002 | 8002 |
| quality-gates        | 8003 | 8003 |
| frontend             | 5173 | 5173 |
| postgres             | 5432 | 5432 |

## Troubleshooting

```bash
# Container not healthy
docker compose ps
docker compose logs --tail=100 orchestration-server

# Verify a service answers on its container port
docker compose exec orchestration-server \
  python -c "import urllib.request;print(urllib.request.urlopen('http://127.0.0.1:8000/health').status)"

# PostgreSQL connectivity (profile-less dev stack defaults to SQLite)
docker compose exec postgres pg_isready -U workflow
```

## Specialised Stacks

Beyond the base stack, the repository ships purpose-built Compose files:

| File | Purpose |
|------|---------|
| `compose.native-worker-preflight.yml` / `compose.native-worker-runtime.yml` | Native worker preflight/runtime (builds `orchestration-server/Dockerfile.native-worker`). |
| `compose.native-qa-runtime.yml` | Native QA runtime (builds `quality-gates/Dockerfile.native-qa`). |
| `compose.trusted-gateway-preflight.yml` / `compose.trusted-gateway-runtime.yml` | Trusted gateway (builds `agent-management/Dockerfile.trusted-gateway`). |
| `compose.trusted-sqlite-control.yml` | Trusted SQLite control plane (`orchestration-server/Dockerfile.secure-sqlite` + `agent-management/Dockerfile.trusted-gateway`). |
| `compose.native-autonomous-dispatch.yml`, `compose.native-autonomous-qa-dispatch.yml`, `compose.native-openrouter-egress.yml`, `compose.native-trusted-git-runtime.yml`, `compose.trusted-git-artifacts.yml`, `compose.release-approval.yml` | Autonomous dispatch, egress and approval stacks. |

Each specialised stack builds from a `<subsystem>/Dockerfile.<variant>` file, not
a root-level `Dockerfile.<variant>`.

---

*See also: [Deployment Guide](deployment-guide.md) | [Architecture: trusted gateway image](../architecture/trusted-gateway-image.md)*

