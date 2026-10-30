# Deployment Guide

Complete guide for deploying the Multi-Agent Workflow System in various environments.

## Deployment Options

| Environment | Use Case | Complexity |
|-------------|----------|------------|
| **Docker Compose** | Development, testing, small production | Low |
| **Kubernetes** | Production, high availability, scale | High |
| **Single Binary** | Edge, air-gapped, simple deployments | Medium |

---

## Docker Compose Deployment (Recommended)

### Prerequisites

- Docker Engine 24.0+
- Docker Compose 2.20+ (plugin)
- 4GB+ RAM, 2+ CPU cores
- 10GB+ disk space

### Quick Start

```bash
# 1. Clone repository
git clone https://github.com/askarahodov/multi-agent-workflow.git
cd multi-agent-workflow

# 2. (Optional) configure local overrides
cp .env.example .env
cp docker-compose.override.yml.example docker-compose.override.yml

# 3. Build and start the stack
make up                 # == docker compose up -d --build

# 4. Verify (every host port is bound to 127.0.0.1)
curl http://localhost:18000/health   # orchestration-server
curl http://localhost:8001/health    # agent-management
curl http://localhost:8002/health    # runtime-hardening
curl http://localhost:8003/health    # quality-gates
open http://localhost:5173           # frontend (Vite dev server)
```

`make down`, `make logs` and `make ps` wrap the corresponding `docker compose`
commands.

### Services

The base stack (`docker-compose.yml`) defines five application services plus an
optional PostgreSQL instance. Each application service is built from its own
per-subsystem Dockerfile with the repository root as build context:

| Service | Dockerfile (context `.`) | Container port | Default host port |
|---------|--------------------------|----------------|-------------------|
| `orchestration-server` | `orchestration-server/Dockerfile` | 8000 | 18000 |
| `agent-management`     | `agent-management/Dockerfile`     | 8001 | 8001 |
| `runtime-hardening`    | `runtime-hardening/Dockerfile`    | 8002 | 8002 |
| `frontend`             | `frontend/Dockerfile`             | 5173 | 5173 |
| `quality-gates`        | `quality-gates/Dockerfile`        | 8003 | 8003 |
| `postgres`             | (image `postgres:16-alpine`)      | 5432 | 5432 |

Released images are named `ghcr.io/<repo>-<service>:<version>` (for example
`ghcr.io/<repo>-orchestration-server:v0.1.0-rc1`).

### How the images work (development mode)

The `<subsystem>/Dockerfile` images are **development images**: at build time they
install runtime dependencies only — into `/app/.venv` for the Python services and
`node_modules` for the frontend — and they do **not** COPY the application
source. The source tree is bind-mounted from the checkout
(`./<subsystem>:/app`) and the dependency volume is seeded from the image so the
bind mount never shadows it. Consequently a released image is **not
standalone-runnable**: it must run with the checkout bind-mount, exactly as the
Compose stack does (or via a Compose `image:` override onto the released tag).

### Configuration Files

#### `.env` (optional — `.env.example` documents the keys)

```bash
# Host-port overrides (container-internal ports are unchanged).
ORCH_HOST_PORT=18000
AGENT_MGMT_HOST_PORT=8001
RUNTIME_HOST_PORT=8002
QG_HOST_PORT=8003
FRONTEND_HOST_PORT=5173
POSTGRES_HOST_PORT=5432

# Optional: base64-encoded 32-byte key for provider-credential encryption.
AUTH_ENCRYPTION_KEY=
```

#### `docker-compose.override.yml` (optional — local customisation)

```yaml
services:
  # Point a service at PostgreSQL instead of SQLite
  orchestration-server:
    environment:
      - ORCH_DATABASE_URL=postgresql+asyncpg://workflow:workflow@postgres:5432/workflow
    depends_on:
      postgres:
        condition: service_healthy
```

### Deploy to another host

```bash
# 1. Check out the release tag
git checkout v0.1.0-rc1

# 2. Build and start the stack
make up

# 3. Verify
curl http://localhost:18000/health
```

---

## Kubernetes Deployment

> **Status:** target design. The Helm chart referenced below is not yet shipped in
> this repository; the Docker Compose stack described above is the supported
> deployment path today.

### Prerequisites

- Kubernetes 1.28+
- Helm 3.12+
- Ingress controller (nginx, traefik)
- Cert-manager for TLS
- PostgreSQL operator (CloudNativePG) or managed DB
- Redis operator or managed Redis

### Helm Chart Structure

```
helm/multi-agent-workflow/
├── Chart.yaml
├── values.yaml
├── values.prod.yaml
├── templates/
│   ├── deployment-api.yaml
│   ├── deployment-dispatcher.yaml
│   ├── deployment-worker.yaml
│   ├── deployment-frontend.yaml
│   ├── service.yaml
│   ├── ingress.yaml
│   ├── configmap.yaml
│   ├── secret.yaml
│   ├── pvc.yaml
│   └── hpa.yaml
└── charts/
    ├── postgresql/ (dependency)
    └── redis/ (dependency)
```

### Key Values (`values.prod.yaml`)

```yaml
global:
  domain: "your-domain.com"
  tls:
    enabled: true
    issuer: "letsencrypt-prod"

image:
  registry: ghcr.io
  repository: your-org/multi-agent-workflow
  tag: "v0.1.0-rc1"
  pullPolicy: IfNotPresent

api:
  replicas: 3
  resources:
    limits:
      cpu: 1000m
      memory: 1Gi
    requests:
      cpu: 500m
      memory: 512Mi
  autoscaling:
    enabled: true
    minReplicas: 3
    maxReplicas: 10
    targetCPUUtilization: 70

dispatcher:
  replicas: 1  # Leader election via lease
  resources:
    limits:
      cpu: 500m
      memory: 512Mi

worker:
  replicas: 5
  concurrency: 4
  resources:
    limits:
      cpu: 2000m
      memory: 2Gi
    requests:
      cpu: 1000m
      memory: 1Gi
  autoscaling:
    enabled: true
    minReplicas: 3
    maxReplicas: 20
    targetCPUUtilization: 60

frontend:
  replicas: 2
  resources:
    limits:
      cpu: 200m
      memory: 256Mi

postgresql:
  enabled: true
  primary:
    resources:
      limits:
        cpu: 1000m
        memory: 1Gi
  persistence:
    size: 20Gi

redis:
  enabled: true
  master:
    resources:
      limits:
        cpu: 500m
        memory: 512Mi
  persistence:
    size: 5Gi

config:
  dispatcher:
    poll_interval_seconds: 5
    max_concurrent_workers: 50
  quality_gates:
    coverage_threshold: 80
```

### Install with Helm

```bash
# Add repo
helm repo add maw https://your-org.github.io/multi-agent-workflow-helm
helm repo update

# Install
helm install maw maw/multi-agent-workflow \
  -n multi-agent-workflow \
  --create-namespace \
  -f values.prod.yaml \
  --wait --timeout 10m

# Upgrade
helm upgrade maw maw/multi-agent-workflow \
  -n multi-agent-workflow \
  -f values.prod.yaml \
  --wait --timeout 10m
```

### Verify Deployment

```bash
# Check pods
kubectl get pods -n multi-agent-workflow

# Check services
kubectl get svc -n multi-agent-workflow

# Check ingress
kubectl get ingress -n multi-agent-workflow

# Test API
kubectl port-forward -n multi-agent-workflow svc/api 8000:8000
curl http://localhost:8000/health
```

---

## Configuration Management

### Environment Variables Priority

1. **Docker/K8s secrets** (highest)
2. **`.env` file**
3. **`docker-compose.override.yml`**
4. **Default values in code** (lowest)

### Secrets Management

#### Docker Compose
```yaml
secrets:
  openrouter_api_key:
    file: ./secrets/openrouter_api_key.txt
  jwt_secret:
    file: ./secrets/jwt_secret.txt

services:
  api:
    secrets:
      - openrouter_api_key
      - jwt_secret
```

#### Kubernetes
```yaml
apiVersion: v1
kind: Secret
metadata:
  name: maw-secrets
  namespace: multi-agent-workflow
type: Opaque
stringData:
  OPENROUTER_API_KEY: "sk-or-v1-..."
  JWT_SECRET: "super-secret"
  DATABASE_URL: "postgresql://..."
---
apiVersion: v1
kind: ConfigMap
metadata:
  name: maw-config
  namespace: multi-agent-workflow
data:
  LOG_LEVEL: "INFO"
  DISPATCHER_MAX_CONCURRENT: "50"
```

---

## Database Migration

### SQLite → PostgreSQL

```bash
# 1. Export SQLite data
sqlite3 data/kanban.db .dump > kanban_dump.sql

# 2. Adjust for PostgreSQL (remove sqlite-specific syntax)
# - Remove "AUTOINCREMENT" → "SERIAL"
# - Adjust datetime format
# - Fix boolean literals (0/1 → false/true)

# 3. Import to PostgreSQL
psql -h localhost -U user -d kanban < kanban_dump.sql

# 4. Update DATABASE_URL
echo "DATABASE_URL=postgresql://user:pass@localhost:5432/kanban" >> .env
```

### Schema Migrations

```bash
# Run migrations (if using Alembic)
alembic upgrade head

# Or manual
psql -h localhost -U user -d kanban -f migrations/001_add_indexes.sql
```

---

## Backup & Recovery

### Automated Backup (CronJob)

```yaml
# k8s/backup-cronjob.yaml
apiVersion: batch/v1
kind: CronJob
metadata:
  name: maw-backup
  namespace: multi-agent-workflow
spec:
  schedule: "0 2 * * *"  # Daily at 2 AM
  jobTemplate:
    spec:
      template:
        spec:
          containers:
          - name: backup
            image: postgres:16-alpine
            command:
            - /bin/sh
            - -c
            - |
              pg_dump -h postgresql -U user kanban | gzip > /backup/kanban-$(date +%F).sql.gz
              find /backup -name "*.sql.gz" -mtime +30 -delete
            volumeMounts:
            - name: backup-storage
              mountPath: /backup
          restartPolicy: OnFailure
          volumes:
          - name: backup-storage
            persistentVolumeClaim:
              claimName: backup-pvc
```

### Manual Backup

```bash
# SQLite
cp data/kanban.db backups/kanban-$(date +%F).db

# PostgreSQL
pg_dump -h localhost -U user kanban | gzip > backups/kanban-$(date +%F).sql.gz

# File storage
tar -czf backups/workspace-$(date +%F).tar.gz data/workspace/
```

### Recovery

```bash
# SQLite
cp backups/kanban-2025-10-15.db data/kanban.db
docker compose restart api dispatcher worker

# PostgreSQL
gunzip -c backups/kanban-2025-10-15.sql.gz | psql -h localhost -U user kanban
```

---

## Rolling Updates

### Zero-Downtime Deployment

```bash
# Docker Compose
docker compose pull
docker compose up -d --no-deps api frontend
# Workers: drain gracefully
docker compose up -d --no-deps --scale worker=0 worker
docker compose up -d --no-deps --scale worker=5 worker

# Kubernetes
kubectl rollout restart deployment/api -n multi-agent-workflow
kubectl rollout restart deployment/frontend -n multi-agent-workflow
# Workers handled by HPA
```

### Health Checks

```yaml
# Kubernetes liveness/readiness
livenessProbe:
  httpGet:
    path: /health
    port: 8000
  initialDelaySeconds: 30
  periodSeconds: 10

readinessProbe:
  httpGet:
    path: /ready
    port: 8000
  initialDelaySeconds: 10
  periodSeconds: 5
```

---

## Troubleshooting Deployment

### Common Issues

| Issue | Diagnosis | Fix |
|-------|-----------|-----|
| API returns 503 | Check dispatcher, DB | `docker compose logs api dispatcher db` |
| Workers not starting | Check dispatcher logs | `docker compose logs dispatcher` |
| Frontend blank | Check VITE_API_URL | Verify nginx proxy config |
| DB connection failed | Check DATABASE_URL, network | Verify DB host, credentials |
| OOM kills | Check memory limits | Increase container memory |

### Debug Commands

```bash
# View all logs
docker compose logs --tail=100 -f

# Exec into container
docker compose exec api bash
docker compose exec worker bash

# Check database
docker compose exec db psql -U user -d kanban -c "SELECT count(*) FROM tasks;"

# Check dispatcher status
curl http://localhost:8000/dispatcher/status
```

---

*See also: [Docker Compose Reference](docker-compose-reference.md) | [Monitoring & Alerting](monitoring-alerting.md) | [Backup & Recovery](backup-recovery.md) | [Scaling Guide](scaling-guide.md)*