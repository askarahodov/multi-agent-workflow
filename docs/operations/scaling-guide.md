# Scaling Guide

Performance tuning and horizontal scaling for the Multi-Agent Workflow System.

## Scaling Dimensions

```
┌─────────────────────────────────────────────────────────────────┐
│                      Scaling Vectors                             │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  TASK THROUGHPUT                                                 │
│  ├── More Workers (Horizontal)          │  ├── Faster Models    │
│  ├── Higher Concurrency/Worker          │  ├── Better Prompts   │
│  └── Optimized Agent Loops              │  └── Caching          │
│                                         │                        │
│  DATA VOLUME                                                          │
│  ├── PostgreSQL (vs SQLite)             │  ├── Read Replicas    │
│  ├── Partitioning/Sharding              │  ├── Archival         │
│  └── Connection Pooling                 │  └── Caching          │
│                                         │                        │
│  LATENCY                                                              │
│  ├── Regional Deployment                │  ├── Edge Caching     │
│  ├── Async Processing                   │  ├── Model Warm-up    │
│  └── Connection Pooling                 │  └── Streaming        │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

---

## Worker Scaling

### Horizontal Scaling (More Workers)

```bash
# Docker Compose
docker compose up -d --scale worker=10

# Kubernetes (HPA)
kubectl autoscale deployment worker \
  --min=3 --max=50 --cpu-percent=60 \
  -n multi-agent-workflow
```

### Vertical Scaling (Worker Resources)

```yaml
# docker-compose.override.yml
services:
  worker:
    deploy:
      resources:
        limits:
          cpus: '4'      # Was 2
          memory: 4G     # Was 2G
        reservations:
          cpus: '2'
          memory: 2G
    environment:
      - WORKER_CONCURRENCY=4  # Match CPU cores
```

### Concurrency Tuning

| Workload Type | WORKER_CONCURRENCY | CPU per Worker | Memory per Worker |
|---------------|-------------------|----------------|-------------------|
| CPU-bound (compilation) | 1-2 | 2-4 cores | 2-4 GB |
| I/O-bound (API calls) | 4-8 | 1-2 cores | 1-2 GB |
| Mixed (default) | 2-4 | 2 cores | 2 GB |
| LLM-heavy | 1-2 | 2-4 cores | 4-8 GB |

**Formula:**
```
Optimal Concurrency = CPU Cores / (1 + Avg_Wait_Time / Avg_CPU_Time)
```

For LLM agents (high wait time): **Concurrency ≈ CPU Cores / 2**

### Worker Profiles

```yaml
# Different worker pools for different profiles
services:
  worker-developer:
    image: maw-worker:latest
    environment:
      - WORKER_PROFILES=sdlc-developer,sdlc-architect
      - WORKER_CONCURRENCY=2
    deploy:
      replicas: 5

  worker-reviewer:
    image: maw-worker:latest
    environment:
      - WORKER_PROFILES=sdlc-reviewer,sdlc-security
      - WORKER_CONCURRENCY=4  # Lighter workload
    deploy:
      replicas: 3

  worker-tester:
    image: maw-worker:latest
    environment:
      - WORKER_PROFILES=sdlc-tester
      - WORKER_CONCURRENCY=2
    deploy:
      replicas: 2
```

---

## Database Scaling

### SQLite → PostgreSQL Migration

```bash
# 1. Enable PostgreSQL profile
docker compose --profile postgres up -d postgres

# 2. Migrate data
./scripts/migrate-sqlite-to-postgres.sh

# 3. Update DATABASE_URL
echo "DATABASE_URL=postgresql://user:pass@postgres:5432/kanban" >> .env

# 4. Restart services
docker compose restart api dispatcher worker
```

### PostgreSQL Tuning

```sql
-- postgresql.conf optimizations
max_connections = 200
shared_buffers = 256MB          # 25% of RAM
effective_cache_size = 1GB      # 75% of RAM
work_mem = 16MB
maintenance_work_mem = 256MB
checkpoint_completion_target = 0.9
wal_buffers = 16MB
default_statistics_target = 100
random_page_cost = 1.1          # SSD
effective_io_concurrency = 200  # SSD
```

### Connection Pooling (PgBouncer)

```yaml
# deploy/compose/dev/docker-compose.yml addition
services:
  pgbouncer:
    image: edoburu/pgbouncer:latest
    environment:
      - DATABASES_HOST=postgres
      - DATABASES_PORT=5432
      - DATABASES_DBNAME=kanban
      - DATABASES_USER=kanban
      - DATABASES_PASSWORD_FILE=/run/secrets/postgres_password
      - POOL_MODE=transaction
      - MAX_CLIENT_CONN=500
      - DEFAULT_POOL_SIZE=25
      - MIN_POOL_SIZE=5
    secrets:
      - postgres_password
    ports:
      - "6432:6432"
    depends_on:
      - postgres
```

### Read Replicas

```yaml
# For read-heavy workloads (dashboards, analytics)
services:
  postgres-replica:
    image: postgres:16-alpine
    command: postgres -c hot_standby=on
    environment:
      - POSTGRES_DB=kanban
    volumes:
      - postgres-replica-data:/var/lib/postgresql/data
    deploy:
      replicas: 2
```

---

## API Scaling

### Horizontal Scaling

```yaml
# Kubernetes HPA
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: api-hpa
  namespace: multi-agent-workflow
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: api
  minReplicas: 3
  maxReplicas: 20
  metrics:
    - type: Resource
      resource:
        name: cpu
        target:
          type: Utilization
          averageUtilization: 70
    - type: Pods
      pods:
        metric:
          name: http_requests_in_progress
        target:
          type: AverageValue
          averageValue: "100"
  behavior:
    scaleDown:
      stabilizationWindowSeconds: 300
      policies:
        - type: Percent
          value: 10
          periodSeconds: 60
    scaleUp:
      stabilizationWindowSeconds: 0
      policies:
        - type: Percent
          value: 100
          periodSeconds: 15
        - type: Pods
          value: 4
          periodSeconds: 15
      selectPolicy: Max
```

### Caching Layer

```python
# services/api/cache.py
import redis.asyncio as redis
from functools import wraps

redis_client = redis.from_url("redis://redis:6379", decode_responses=True)

async def cached(ttl: int = 300):
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            key = f"cache:{func.__name__}:{hash(str(args) + str(kwargs))}"
            cached = await redis_client.get(key)
            if cached:
                return json.loads(cached)
            result = await func(*args, **kwargs)
            await redis_client.setex(key, ttl, json.dumps(result))
            return result
        return wrapper
    return decorator

# Usage
@cached(ttl=60)
async def get_board_stats(board: str):
    return await db.query("SELECT * FROM board_stats WHERE board = ?", board)
```

### Response Compression

```python
# FastAPI middleware
from fastapi.middleware.gzip import GZipMiddleware

app.add_middleware(GZipMiddleware, minimum_size=1000)
```

---

## Frontend Scaling

### CDN + Static Hosting

```yaml
# For production: serve frontend via CDN
# CloudFront, Cloudflare, or nginx + object storage

# Build
npm run build  # Outputs to dist/

# Upload to S3/GCS
aws s3 sync dist/ s3://your-bucket --delete --cache-control "max-age=31536000"

# Invalidate CloudFront
aws cloudfront create-invalidation --distribution-id XXX --paths "/*"
```

### Nginx Caching

```nginx
# Cache static assets
location /assets/ {
    expires 1y;
    add_header Cache-Control "public, immutable";
    proxy_pass http://frontend/;
}

# Cache HTML for short time
location / {
    proxy_cache_valid 200 30s;
    proxy_cache_use_stale error timeout updating http_500 http_502 http_503 http_504;
    proxy_pass http://frontend/;
}
```

---

## Dispatcher Scaling

### Single Leader Constraint

The dispatcher **must run as a single instance** for correctness (leader election via Redis).

```yaml
# Kubernetes: Use leader election
dispatcher:
  replicas: 1  # Only one active
  # Leader election via lease:
  # kubectl get lease maw-dispatcher -n multi-agent-workflow
```

### High Availability

```yaml
# Run 2 dispatchers, only one active
dispatcher:
  replicas: 2
  # Uses Redis SET NX for leader election
  # Standby takes over within heartbeat_timeout (default 300s)
```

### Dispatcher Performance

```python
# Tune poll interval based on load
# High throughput: lower interval
DISPATCHER_POLL_INTERVAL=2  # seconds

# Low throughput: higher interval (less DB load)
DISPATCHER_POLL_INTERVAL=10

# Batch dispatch (dispatch multiple tasks per poll)
DISPATCHER_BATCH_SIZE=5
```

---

## Queue Management

### Priority Queues

```python
# Priority-based dispatch
# High priority tasks dispatched first
DISPATCHER_PRIORITY_BOOST=10  # Ready tasks get +10 priority

# Separate queues per profile (if needed)
# Configure in dispatcher.yaml
queues:
  sdlc-developer:
    max_concurrent: 20
  sdlc-reviewer:
    max_concurrent: 10
```

### Backpressure

```yaml
# Reject new tasks when queue full
dispatcher:
  max_queue_depth: 1000
  reject_on_full: true
  backpressure_threshold: 800
```

---

## Model/Provider Scaling

### Model Routing

```yaml
# config/profiles/sdlc-developer.yaml
model:
  provider: openrouter
  name: openrouter/auto  # Auto-route to available model
  fallback_models:
    - anthropic/claude-3.5-sonnet
    - openai/gpt-4o
    - google/gemini-pro-1.5
```

### Rate Limit Handling

```python
# Automatic retry with exponential backoff
# Configured in dispatcher.yaml
retry_policy:
  max_attempts: 3
  base_delay_seconds: 60
  max_delay_seconds: 3600
  exponential_base: 2

# Per-model rate limits (OpenRouter)
# Monitor: rate_limited errors → switch model
```

### Cost Optimization

```bash
# Use cheaper models for simple tasks
hermes-kanban create --title "Simple refactor" \
  --assignee sdlc-developer \
  --model openai/gpt-4o-mini

# Reserve expensive models for complex tasks
hermes-kanban create --title "Architect system" \
  --assignee sdlc-architect \
  --model anthropic/claude-3.5-sonnet
```

---

## Performance Benchmarks

### Baseline Targets

| Metric | Target | Measurement |
|--------|--------|-------------|
| Task dispatch latency | < 5s | dispatcher logs |
| API p50 latency | < 100ms | Prometheus histogram |
| API p99 latency | < 500ms | Prometheus histogram |
| Worker startup time | < 10s | worker logs |
| Task throughput | 100+/min | tasks_completed_total rate |
| Concurrent tasks | 500+ | dispatcher_queue_depth |

### Load Testing

```bash
# Locust load test
# locustfile.py
from locust import HttpUser, task, between

class KanbanUser(HttpUser):
    wait_time = between(1, 5)
    
    def on_start(self):
        self.client.headers = {"Authorization": "Bearer test-token"}
    
    @task(3)
    def list_tasks(self):
        self.client.get("/boards/default/tasks")
    
    @task(1)
    def create_task(self):
        self.client.post("/boards/default/tasks", json={
            "title": f"Load test {random.randint(1,10000)}",
            "assignee": "sdlc-developer"
        })

# Run
locust -f locustfile.py --host=http://localhost:8000 --users=50 --spawn-rate=5 --run-time=5m
```

### Capacity Planning

```python
# Estimate required workers
# Tasks per hour = 600
# Avg task duration = 5 minutes = 1/12 hour
# Concurrent tasks = 600 * (1/12) = 50
# With 20% buffer = 60 concurrent
# Worker concurrency = 2
# Workers needed = 60 / 2 = 30

# Formula:
workers_needed = (tasks_per_hour * avg_task_duration_hours * 1.2) / worker_concurrency
```

---

## Cost Scaling

### Cost per Task

```python
# Track in metrics
worker_token_usage_total{model, type}

# Calculate
cost_per_task = (input_tokens * input_cost_per_1k + output_tokens * output_cost_per_1k) / 1000

# Example (GPT-4o-mini: $0.15/1M input, $0.60/1M output)
# 10k input + 5k output = $0.0015 + $0.003 = $0.0045 per task
```

### Budget Controls

```yaml
# In dispatcher.yaml
budget:
  daily_token_limit: 10000000  # 10M tokens/day
  daily_cost_limit_usd: 50.00
  alert_threshold: 0.8
  action_on_exceed: block_new_tasks  # or switch_to_cheaper_model
```

---

## Troubleshooting Scaling Issues

### Symptoms & Solutions

| Symptom | Cause | Solution |
|---------|-------|----------|
| Tasks stuck in `ready` | Not enough workers | Scale worker replicas |
| High API latency | DB connection pool exhausted | Increase pool size, add PgBouncer |
| Worker OOM kills | Concurrency too high | Reduce `WORKER_CONCURRENCY` |
| Dispatcher CPU high | Poll interval too low | Increase `DISPATCHER_POLL_INTERVAL` |
| Rate limit errors | Model quota exceeded | Add fallback models, reduce concurrency |
| Slow task completion | Model latency high | Use faster model, enable streaming |

### Debugging Commands

```bash
# Worker resource usage
docker stats --no-stream $(docker ps -f name=maw-worker -q)

# Queue depth
curl -s http://localhost:8000/dispatcher/status | jq .queue

# Task duration percentiles
curl -s http://localhost:8000/metrics | grep task_duration_seconds_bucket

# Model latency
curl -s http://localhost:8000/metrics | grep worker_tool_calls_duration
```

---

*See also: [Deployment Guide](deployment-guide.md) | [Monitoring & Alerting](monitoring-alerting.md) | [Backup & Recovery](backup-recovery.md)*