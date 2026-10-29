# Docker Compose Reference

Complete reference for all Docker Compose configurations and service definitions.

## File Structure

```
.
├── docker-compose.yml              # Base configuration
├── docker-compose.override.yml     # Local overrides (gitignored)
├── docker-compose.prod.yml         # Production overrides
├── docker-compose.test.yml         # Test/CI overrides
└── .env                            # Environment variables (gitignored)
```

## Base Configuration (`docker-compose.yml`)

```yaml
version: '3.8'

services:
  # ─────────────────────────────────────────────────────────
  # API Gateway - FastAPI application
  # ─────────────────────────────────────────────────────────
  api:
    build:
      context: .
      dockerfile: Dockerfile.api
    image: ${IMAGE_REGISTRY:-ghcr.io/your-org}/multi-agent-workflow-api:${TAG:-latest}
    container_name: maw-api
    restart: unless-stopped
    environment:
      - DATABASE_URL=${DATABASE_URL:-sqlite:///data/kanban.db}
      - REDIS_URL=${REDIS_URL:-redis://redis:6379}
      - JWT_SECRET=${JWT_SECRET}
      - API_KEY_SALT=${API_KEY_SALT}
      - LOG_LEVEL=${LOG_LEVEL:-INFO}
      - HOST=0.0.0.0
      - PORT=8000
    volumes:
      - ./config:/app/config:ro
      - data:/app/data
      - ./logs:/app/logs
    ports:
      - "${API_PORT:-8000}:8000"
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8000/health"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 10s
    depends_on:
      redis:
        condition: service_healthy
    networks:
      - maw-network

  # ─────────────────────────────────────────────────────────
  # Frontend - React + Vite + TypeScript
  # ─────────────────────────────────────────────────────────
  frontend:
    build:
      context: ./frontend
      dockerfile: Dockerfile
      args:
        - VITE_API_URL=${VITE_API_URL:-http://localhost:8000}
    image: ${IMAGE_REGISTRY:-ghcr.io/your-org}/multi-agent-workflow-frontend:${TAG:-latest}
    container_name: maw-frontend
    restart: unless-stopped
    environment:
      - VITE_API_URL=${VITE_API_URL:-http://localhost:8000}
    ports:
      - "${FRONTEND_PORT:-3000}:3000"
    healthcheck:
      test: ["CMD", "wget", "-q", "--spider", "http://localhost:3000"]
      interval: 30s
      timeout: 10s
      retries: 3
    networks:
      - maw-network

  # ─────────────────────────────────────────────────────────
  # Dispatcher - Task orchestration (single leader)
  # ─────────────────────────────────────────────────────────
  dispatcher:
    build:
      context: .
      dockerfile: Dockerfile.dispatcher
    image: ${IMAGE_REGISTRY:-ghcr.io/your-org}/multi-agent-workflow-dispatcher:${TAG:-latest}
    container_name: maw-dispatcher
    restart: unless-stopped
    environment:
      - DATABASE_URL=${DATABASE_URL:-sqlite:///data/kanban.db}
      - REDIS_URL=${REDIS_URL:-redis://redis:6379}
      - LOG_LEVEL=${LOG_LEVEL:-INFO}
      - DISPATCHER_POLL_INTERVAL=${DISPATCHER_POLL_INTERVAL:-5}
      - DISPATCHER_MAX_CONCURRENT=${DISPATCHER_MAX_CONCURRENT:-10}
      - DISPATCHER_HEARTBEAT_INTERVAL=${DISPATCHER_HEARTBEAT_INTERVAL:-60}
      - DISPATCHER_WORKER_TIMEOUT=${DISPATCHER_WORKER_TIMEOUT:-3600}
      - WORKSPACE_BASE_DIR=${WORKSPACE_BASE_DIR:-/tmp/hermes-workspaces}
    volumes:
      - ./config:/app/config:ro
      - data:/app/data
      - workspace:/workspace
      - /var/run/docker.sock:/var/run/docker.sock:ro  # For spawning workers
    networks:
      - maw-network
    deploy:
      replicas: 1  # Critical: only one dispatcher

  # ─────────────────────────────────────────────────────────
  # Worker Pool - Agent execution environments
  # ─────────────────────────────────────────────────────────
  worker:
    build:
      context: .
      dockerfile: Dockerfile.worker
    image: ${IMAGE_REGISTRY:-ghcr.io/your-org}/multi-agent-workflow-worker:${TAG:-latest}
    container_name: maw-worker
    restart: unless-stopped
    environment:
      - DATABASE_URL=${DATABASE_URL:-sqlite:///data/kanban.db}
      - REDIS_URL=${REDIS_URL:-redis://redis:6379}
      - LOG_LEVEL=${LOG_LEVEL:-INFO}
      - WORKER_CONCURRENCY=${WORKER_CONCURRENCY:-2}
      - WORKSPACE_BASE_DIR=${WORKSPACE_BASE_DIR:-/tmp/hermes-workspaces}
      - PYTHONPATH=/workspace
      - UV_CACHE_DIR=/tmp/uv-cache
    volumes:
      - ./config:/app/config:ro
      - data:/app/data
      - workspace:/workspace
    networks:
      - maw-network
    deploy:
      replicas: ${WORKER_REPLICAS:-3}
      resources:
        limits:
          cpus: '2'
          memory: 2G
        reservations:
          cpus: '1'
          memory: 1G

  # ─────────────────────────────────────────────────────────
  # Redis - Caching, pub/sub, distributed locking
  # ─────────────────────────────────────────────────────────
  redis:
    image: redis:7-alpine
    container_name: maw-redis
    restart: unless-stopped
    command: redis-server --appendonly yes --maxmemory 256mb --maxmemory-policy allkeys-lru
    volumes:
      - redis-data:/data
    ports:
      - "6379:6379"
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 10s
      timeout: 5s
      retries: 5
    networks:
      - maw-network

  # ─────────────────────────────────────────────────────────
  # PostgreSQL - Production database (optional, for prod)
  # ─────────────────────────────────────────────────────────
  postgres:
    image: postgres:16-alpine
    container_name: maw-postgres
    restart: unless-stopped
    environment:
      - POSTGRES_DB=kanban
      - POSTGRES_USER=${POSTGRES_USER:-kanban}
      - POSTGRES_PASSWORD_FILE=/run/secrets/postgres_password
    secrets:
      - postgres_password
    volumes:
      - postgres-data:/var/lib/postgresql/data
    ports:
      - "5432:5432"
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U ${POSTGRES_USER:-kanban} -d kanban"]
      interval: 10s
      timeout: 5s
      retries: 5
    networks:
      - maw-network
    profiles:
      - postgres  # Only start with: docker compose --profile postgres up

# ─────────────────────────────────────────────────────────
# Volumes
# ─────────────────────────────────────────────────────────
volumes:
  data:
    driver: local
  workspace:
    driver: local
  redis-data:
    driver: local
  postgres-data:
    driver: local

# ─────────────────────────────────────────────────────────
# Networks
# ─────────────────────────────────────────────────────────
networks:
  maw-network:
    driver: bridge
    name: maw-network

# ─────────────────────────────────────────────────────────
# Secrets
# ─────────────────────────────────────────────────────────
secrets:
  postgres_password:
    file: ./secrets/postgres_password.txt
```

## Service Details

### API Service

**Dockerfile.api:**
```dockerfile
FROM python:3.11-slim

WORKDIR /app

# System dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Application code
COPY services/api/ ./services/api/
COPY config/ ./config/

# Non-root user
RUN useradd -m -u 1000 appuser && chown -R appuser:appuser /app
USER appuser

EXPOSE 8000

CMD ["uvicorn", "services.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

**Health Endpoint:** `GET /health`
```json
{
  "status": "healthy",
  "version": "0.1.0-rc1",
  "database": "connected",
  "dispatcher": "running",
  "workers": 3,
  "timestamp": "2025-10-16T14:30:00Z"
}
```

### Frontend Service

**Dockerfile (Development):**
```dockerfile
FROM node:20-alpine

WORKDIR /app

COPY frontend/package*.json ./
RUN npm ci

COPY frontend/ ./

EXPOSE 3000

CMD ["npm", "run", "dev", "--", "--host", "0.0.0.0"]
```

**Dockerfile.prod:**
```dockerfile
FROM node:20-alpine AS builder

WORKDIR /app
COPY frontend/package*.json ./
RUN npm ci

COPY frontend/ ./
RUN npm run build

FROM nginx:alpine
COPY --from=builder /app/dist /usr/share/nginx/html
COPY frontend/nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 3000
CMD ["nginx", "-g", "daemon off;"]
```

### Dispatcher Service

**Dockerfile.dispatcher:**
```dockerfile
FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    docker.io \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY services/dispatcher/ ./services/dispatcher/
COPY config/ ./config/
COPY agent-management/ ./agent-management/
COPY quality-gates/ ./quality-gates/

RUN useradd -m -u 1000 appuser && chown -R appuser:appuser /app
USER appuser

CMD ["python", "-m", "services.dispatcher.main"]
```

**Leader Election:** Uses Redis distributed lock (`SET NX EX`) to ensure single active dispatcher.

### Worker Service

**Dockerfile.worker:**
```dockerfile
FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY agent-management/ ./agent-management/
COPY config/ ./config/
COPY quality-gates/ ./quality-gates/
COPY skills/ ./skills/

RUN useradd -m -u 1000 appuser && chown -R appuser:appuser /app
USER appuser

CMD ["python", "-m", "agent_management.agent_loop"]
```

**Worker Concurrency:** Each worker container runs `WORKER_CONCURRENCY` agent processes concurrently.

---

## Environment Variables Reference

### Global (All Services)

| Variable | Default | Description |
|----------|---------|-------------|
| `DATABASE_URL` | `sqlite:///data/kanban.db` | Database connection string |
| `REDIS_URL` | `redis://redis:6379` | Redis connection |
| `LOG_LEVEL` | `INFO` | Log level (DEBUG, INFO, WARNING, ERROR) |
| `IMAGE_REGISTRY` | `ghcr.io/your-org` | Container registry |
| `TAG` | `latest` | Image tag |

### API Service

| Variable | Default | Description |
|----------|---------|-------------|
| `JWT_SECRET` | (required) | JWT signing secret |
| `API_KEY_SALT` | (required) | API key hashing salt |
| `HOST` | `0.0.0.0` | Bind address |
| `PORT` | `8000` | Port |
| `API_PORT` | `8000` | Host port mapping |

### Frontend Service

| Variable | Default | Description |
|----------|---------|-------------|
| `VITE_API_URL` | `http://localhost:8000` | API base URL |
| `FRONTEND_PORT` | `3000` | Host port mapping |

### Dispatcher Service

| Variable | Default | Description |
|----------|---------|-------------|
| `DISPATCHER_POLL_INTERVAL` | `5` | Poll interval (seconds) |
| `DISPATCHER_MAX_CONCURRENT` | `10` | Max concurrent tasks |
| `DISPATCHER_HEARTBEAT_INTERVAL` | `60` | Worker heartbeat interval |
| `DISPATCHER_WORKER_TIMEOUT` | `3600` | Worker timeout (seconds) |
| `WORKSPACE_BASE_DIR` | `/tmp/hermes-workspaces` | Workspace base directory |

### Worker Service

| Variable | Default | Description |
|----------|---------|-------------|
| `WORKER_CONCURRENCY` | `2` | Concurrent agents per worker |
| `WORKER_REPLICAS` | `3` | Number of worker containers |
| `PYTHONPATH` | `/workspace` | Python module path |
| `UV_CACHE_DIR` | `/tmp/uv-cache` | UV cache directory |

### PostgreSQL (Profile)

| Variable | Default | Description |
|----------|---------|-------------|
| `POSTGRES_USER` | `kanban` | Database user |
| `POSTGRES_PASSWORD_FILE` | (secret) | Password file path |

---

## Profiles

### Default Profile (Development)
```bash
docker compose up -d
# Starts: api, frontend, dispatcher, worker (3x), redis
```

### PostgreSQL Profile
```bash
docker compose --profile postgres up -d
# Adds: postgres service, uses PostgreSQL instead of SQLite
```

### Production Profile
```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d
# Uses: production configs, nginx, multiple replicas
```

### Test Profile
```bash
docker compose -f docker-compose.yml -f docker-compose.test.yml up -d
# Uses: test database, reduced resources, no frontend
```

---

## Common Commands

### Lifecycle
```bash
# Start all
docker compose up -d

# Start with profile
docker compose --profile postgres up -d

# Start with override
docker compose -f docker-compose.yml -f docker-compose.override.yml up -d

# Stop all
docker compose down

# Stop and remove volumes
docker compose down -v

# Restart specific service
docker compose restart api

# Rebuild and restart
docker compose up -d --build api
```

### Scaling
```bash
# Scale workers
docker compose up -d --scale worker=5

# Scale with profile
docker compose --profile postgres up -d --scale worker=10
```

### Logs
```bash
# All services
docker compose logs -f

# Specific service
docker compose logs -f api

# Last 100 lines
docker compose logs --tail=100 dispatcher

# With timestamps
docker compose logs -t worker
```

### Debugging
```bash
# Exec into container
docker compose exec api bash
docker compose exec worker python -c "import sys; print(sys.path)"

# View container resource usage
docker compose top

# Inspect container
docker compose exec api cat /app/config/profiles/sdlc-developer.yaml

# Run one-off command
docker compose run --rm worker pytest tests/
```

### Database Operations
```bash
# SQLite backup
docker compose exec api cp /app/data/kanban.db /app/data/kanban.backup.db

# PostgreSQL backup
docker compose exec postgres pg_dump -U kanban kanban > backup.sql

# Run migrations
docker compose exec api alembic upgrade head
```

---

## Networking

### Internal Network
All services communicate via `maw-network` bridge network:
- `api:8000` — API Gateway
- `frontend:3000` — Frontend
- `dispatcher:8080` — Dispatcher (internal)
- `redis:6379` — Redis
- `postgres:5432` — PostgreSQL

### Port Mapping

| Service | Container Port | Host Port (Default) |
|---------|----------------|---------------------|
| API | 8000 | 8000 |
| Frontend | 3000 | 3000 |
| Redis | 6379 | 6379 |
| PostgreSQL | 5432 | 5432 |

### Custom Ports
```bash
# Via .env
API_PORT=8080
FRONTEND_PORT=8081

# Or inline
docker compose up -d -p 8080:8000 -p 8081:3000
```

---

## Resource Limits

### Default Limits (Per Container)

| Service | CPU Limit | Memory Limit | CPU Reservation | Memory Reservation |
|---------|-----------|--------------|-----------------|-------------------|
| API | 1.0 | 1G | 0.5 | 512M |
| Frontend | 0.5 | 512M | 0.25 | 128M |
| Dispatcher | 0.5 | 512M | 0.25 | 256M |
| Worker | 2.0 | 2G | 1.0 | 1G |
| Redis | 0.5 | 256M | 0.25 | 128M |
| PostgreSQL | 1.0 | 1G | 0.5 | 512M |

### Override Limits
```yaml
# docker-compose.override.yml
services:
  worker:
    deploy:
      resources:
        limits:
          cpus: '4'
          memory: 4G
        reservations:
          cpus: '2'
          memory: 2G
```

---

## Troubleshooting

### Service Won't Start
```bash
# Check logs
docker compose logs api

# Check healthcheck
docker compose ps
docker inspect maw-api --format '{{json .State.Health}}' | jq .
```

### Database Issues
```bash
# SQLite: check file permissions
ls -la data/kanban.db

# PostgreSQL: check connection
docker compose exec postgres pg_isready -U kanban
```

### Worker Issues
```bash
# Check dispatcher logs for worker spawn errors
docker compose logs dispatcher | grep -i error

# Check worker resource usage
docker stats maw-worker-1 maw-worker-2 maw-worker-3
```

### Network Issues
```bash
# Test internal connectivity
docker compose exec api curl -f http://redis:6379
docker compose exec api curl -f http://postgres:5432
```

---

*See also: [Deployment Guide](deployment-guide.md) | [Monitoring & Alerting](monitoring-alerting.md) | [Scaling Guide](scaling-guide.md)*