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
git clone https://github.com/your-org/multi-agent-workflow.git
cd multi-agent-workflow

# 2. Configure environment
cp .env.example .env
# Edit .env with your settings (required: OPENROUTER_API_KEY, DEFAULT_MODEL)

# 3. Start services
docker compose up -d

# 4. Verify
curl http://localhost:8000/health
open http://localhost:3000
```

### Service Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                     docker-compose.yml                        │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  ┌─────────────┐    ┌─────────────┐    ┌─────────────┐     │
│  │   nginx     │    │   frontend  │    │     api     │     │
│  │  (proxy)    │◄───│  (React)    │◄───│  (FastAPI)  │     │
│  │  :80/:443   │    │   :3000     │    │   :8000     │     │
│  └─────────────┘    └─────────────┘    └──────┬──────┘     │
│                                                │            │
│                    ┌───────────────────────────┼───────┐    │
│                    ▼                           ▼       ▼    │
│             ┌─────────────┐             ┌──────────┐ ┌──────┐│
│             │ dispatcher  │             │  worker  │ │worker││
│             │  (single)   │             │  pool    │ │pool  ││
│             └──────┬──────┘             └──────────┘ └──────┘│
│                    │                                         │
│         ┌──────────┴──────────┐                               │
│         ▼                     ▼                               │
│  ┌─────────────┐        ┌─────────────┐                       │
│  │  SQLite     │        │  File       │                       │
│  │  (kanban)   │        │  Storage    │                       │
│  └─────────────┘        └─────────────┘                       │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

### Configuration Files

#### `.env` (Required)
```bash
# LLM Provider (required)
OPENROUTER_API_KEY=sk-or-v1-xxxxxxxxxxxxx
DEFAULT_MODEL=nvidia/nemotron-3-ultra-550b-a55b:free

# Database
DATABASE_URL=sqlite:///data/kanban.db

# Server
HOST=0.0.0.0
PORT=8000
FRONTEND_PORT=3000

# Logging
LOG_LEVEL=INFO

# Dispatcher
DISPATCHER_POLL_INTERVAL=5
DISPATCHER_MAX_CONCURRENT=10

# Security
JWT_SECRET=your-super-secret-jwt-key-change-in-production
API_KEY_SALT=your-api-key-salt
```

#### `docker-compose.override.yml` (Optional - Local Customization)
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

### Production Docker Compose

```yaml
# docker-compose.prod.yml
version: '3.8'

services:
  nginx:
    image: nginx:alpine
    ports:
      - "80:80"
      - "443:443"
    volumes:
      - ./nginx.prod.conf:/etc/nginx/nginx.conf:ro
      - ./certs:/etc/nginx/certs:ro
    depends_on:
      - api
      - frontend
    restart: unless-stopped

  api:
    build:
      context: .
      dockerfile: Dockerfile.api
    environment:
      - DATABASE_URL=postgresql://user:pass@db:5432/kanban
      - REDIS_URL=redis://redis:6379
      - LOG_LEVEL=INFO
    volumes:
      - ./config:/app/config:ro
      - data:/app/data
    deploy:
      replicas: 2
      resources:
        limits:
          cpus: '1'
          memory: 1G
    restart: unless-stopped

  frontend:
    build:
      context: ./frontend
      dockerfile: Dockerfile.prod
    environment:
      - VITE_API_URL=https://api.your-domain.com
    deploy:
      replicas: 2
    restart: unless-stopped

  dispatcher:
    build:
      context: .
      dockerfile: Dockerfile.dispatcher
    environment:
      - DATABASE_URL=postgresql://user:pass@db:5432/kanban
    volumes:
      - ./config:/app/config:ro
      - data:/app/data
    deploy:
      replicas: 1  # Single leader
    restart: unless-stopped

  worker:
    build:
      context: .
      dockerfile: Dockerfile.worker
    environment:
      - DATABASE_URL=postgresql://user:pass@db:5432/kanban
      - WORKER_CONCURRENCY=4
    volumes:
      - ./config:/app/config:ro
      - workspace:/workspace
    deploy:
      replicas: 5
    restart: unless-stopped

  db:
    image: postgres:16-alpine
    environment:
      - POSTGRES_DB=kanban
      - POSTGRES_USER=user
      - POSTGRES_PASSWORD_FILE=/run/secrets/db_password
    secrets:
      - db_password
    volumes:
      - pgdata:/var/lib/postgresql/data
    restart: unless-stopped

  redis:
    image: redis:7-alpine
    volumes:
      - redisdata:/data
    restart: unless-stopped

volumes:
  data:
  workspace:
  pgdata:
  redisdata:

secrets:
  db_password:
    file: ./secrets/db_password.txt
```

### SSL/TLS Configuration

```nginx
# nginx.prod.conf
events {
    worker_connections 1024;
}

http {
    upstream api {
        server api:8000;
    }
    
    upstream frontend {
        server frontend:3000;
    }
    
    server {
        listen 80;
        server_name your-domain.com;
        return 301 https://$server_name$request_uri;
    }
    
    server {
        listen 443 ssl http2;
        server_name your-domain.com;
        
        ssl_certificate /etc/nginx/certs/fullchain.pem;
        ssl_certificate_key /etc/nginx/certs/privkey.pem;
        ssl_protocols TLSv1.2 TLSv1.3;
        
        location /api/ {
            proxy_pass http://api/;
            proxy_set_header Host $host;
            proxy_set_header X-Real-IP $remote_addr;
            proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
            proxy_set_header X-Forwarded-Proto $scheme;
        }
        
        location /ws/ {
            proxy_pass http://api/;
            proxy_http_version 1.1;
            proxy_set_header Upgrade $http_upgrade;
            proxy_set_header Connection "upgrade";
        }
        
        location / {
            proxy_pass http://frontend/;
            proxy_set_header Host $host;
        }
    }
}
```

### Deploy to Production

```bash
# 1. Prepare secrets
mkdir -p secrets certs
echo "your-db-password" > secrets/db_password.txt
chmod 600 secrets/db_password.txt

# 2. Get SSL certs (Let's Encrypt)
# certbot certonly --standalone -d your-domain.com
# cp /etc/letsencrypt/live/your-domain.com/fullchain.pem certs/
# cp /etc/letsencrypt/live/your-domain.com/privkey.pem certs/

# 3. Deploy
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d

# 4. Verify
curl https://your-domain.com/health
```

---

## Kubernetes Deployment

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