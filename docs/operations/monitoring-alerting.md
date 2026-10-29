# Monitoring & Alerting

Comprehensive monitoring, observability, and alerting for the Multi-Agent Workflow System.

## Observability Stack

```
┌─────────────────────────────────────────────────────────────────┐
│                      Observability Stack                         │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐              │
│  │  Metrics    │  │   Logs      │  │  Traces     │              │
│  │ (Prometheus)│  │ (Loki)      │  │ (Tempo)     │              │
│  └──────┬──────┘  └──────┬──────┘  └──────┬──────┘              │
│         │                │                │                      │
│         └────────────────┼────────────────┘                      │
│                          ▼                                       │
│                 ┌─────────────────┐                              │
│                 │   Grafana       │                              │
│                 │   Dashboards    │                              │
│                 └────────┬────────┘                              │
│                          │                                       │
│                 ┌────────┴────────┐                              │
│                 ▼                 ▼                              │
│          ┌─────────────┐   ┌─────────────┐                       │
│          │ Alertmanager│   │  On-call    │                       │
│          │  (Alerts)   │   │  (PagerDuty)│                       │
│          └─────────────┘   └─────────────┘                       │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

## Metrics (Prometheus)

### Exposed Metrics

#### API Service (`:8000/metrics`)
```prometheus
# HTTP Metrics
http_requests_total{method,path,status}        # Request counter
http_request_duration_seconds{method,path}     # Latency histogram
http_requests_in_progress{method,path}         # In-flight requests

# Task Metrics
tasks_created_total{assignee,status}           # Task creation rate
tasks_completed_total{assignee}                # Completion rate
tasks_blocked_total{kind}                      # Block rate
task_duration_seconds{assignee}                # Task execution time

# Dispatcher Metrics
dispatcher_polls_total                         # Poll cycles
dispatcher_workers_active{profile}             # Active workers per profile
dispatcher_queue_depth{status}                 # Tasks per status
dispatcher_heartbeat_failures_total            # Missed heartbeats

# Worker Metrics
worker_agent_turns_total{profile,result}       # Agent loop turns
worker_tool_calls_total{tool,result}           # Tool usage
worker_token_usage_total{model,type}           # Token consumption
worker_errors_total{type}                      # Error breakdown
```

#### Dispatcher Service (`:8080/metrics`)
```prometheus
dispatcher_uptime_seconds                      # Process uptime
dispatcher_tasks_dispatched_total              # Total dispatched
dispatcher_tasks_failed_total{reason}          # Failure reasons
dispatcher_worker_spawn_duration_seconds       # Spawn latency
dispatcher_workspace_cleanup_duration_seconds  # Cleanup time
```

### Prometheus Configuration

```yaml
# prometheus.yml
global:
  scrape_interval: 15s
  evaluation_interval: 15s

scrape_configs:
  - job_name: 'maw-api'
    static_configs:
      - targets: ['api:8000']
    metrics_path: /metrics

  - job_name: 'maw-dispatcher'
    static_configs:
      - targets: ['dispatcher:8080']
    metrics_path: /metrics

  - job_name: 'maw-workers'
    kubernetes_sd_configs:
      - role: pod
        namespaces:
          names: ['multi-agent-workflow']
    relabel_configs:
      - source_labels: [__meta_kubernetes_pod_label_app]
        action: keep
        regex: worker
      - source_labels: [__meta_kubernetes_pod_name]
        action: replace
        target_label: pod

  - job_name: 'redis'
    static_configs:
      - targets: ['redis:9121']  # redis-exporter

  - job_name: 'postgres'
    static_configs:
      - targets: ['postgres:9187']  # postgres-exporter

  - job_name: 'node-exporter'
    static_configs:
      - targets: ['node-exporter:9100']
```

### Key Dashboards

#### 1. System Overview
- Request rate / latency / error rate (RED)
- Active tasks by status
- Worker pool utilization
- Database connections

#### 2. Task Pipeline
- Task throughput (created/completed/blocked per minute)
- Cycle time (creation → completion)
- Queue depth by status
- Retry rate

#### 3. Agent Performance
- Turns per task by profile
- Tool call success rate
- Token usage by model
- Cost per task

#### 4. Infrastructure
- CPU/Memory per service
- Database size / connections
- Redis memory / hit rate
- Disk usage

---

## Logging (Loki)

### Log Format (JSON)

```json
{
  "timestamp": "2025-10-16T14:30:00.123Z",
  "level": "INFO",
  "logger": "hermes.dispatcher",
  "message": "Task dispatched",
  "fields": {
    "task_id": "t_abc123",
    "assignee": "sdlc-developer",
    "worker_id": "worker-7",
    "run_id": 42
  }
}
```

### Log Labels

| Label | Values | Description |
|-------|--------|-------------|
| `service` | api, frontend, dispatcher, worker | Service name |
| `profile` | sdlc-developer, sdlc-architect, ... | Agent profile (worker only) |
| `task_id` | t_abc123 | Task identifier |
| `run_id` | 42 | Execution run number |
| `level` | DEBUG, INFO, WARNING, ERROR | Log level |

### Loki Configuration

```yaml
# loki-config.yml
auth_enabled: false

server:
  http_listen_port: 3100
  grpc_listen_port: 9096

ingester:
  wal:
    enabled: true
    dir: /tmp/wal
  lifecycler:
    address: 127.0.0.1
    ring:
      kvstore:
        store: inmemory
      replication_factor: 1
  chunk_idle_period: 5m
  chunk_retain_period: 30s

schema_config:
  configs:
    - from: 2025-01-01
      store: boltdb-shipper
      object_store: filesystem
      schema: v11
      index:
        prefix: index_
        period: 24h

storage_config:
  boltdb_shipper:
    active_index_directory: /tmp/loki/boltdb-shipper-active
    cache_location: /tmp/loki/boltdb-shipper-cache
    cache_ttl: 24h
    shared_store: filesystem
  filesystem:
    directory: /tmp/loki/chunks

limits_config:
  reject_old_samples: true
  reject_old_samples_max_age: 168h
  ingestion_rate_mb: 10
  ingestion_burst_size_mb: 20
```

### Log Queries (LogQL)

```logql
# All errors in last hour
{service="api"} |= "ERROR" | json | level="ERROR"

# Task-specific logs
{service="worker", task_id="t_abc123"} | json

# Agent turns for profile
{service="worker", profile="sdlc-developer"} | json | logger="hermes.agent"

# Slow requests
{service="api"} | json | duration > 5
```

---

## Distributed Tracing (Tempo)

### Trace Context Propagation

```python
# Automatic via OpenTelemetry
from opentelemetry import trace

tracer = trace.get_tracer(__name__)

with tracer.start_as_current_span("dispatch_task") as span:
    span.set_attribute("task.id", task.id)
    span.set_attribute("task.assignee", task.assignee)
    
    # Child spans for tool calls
    with tracer.start_as_current_span("tool.write_file") as tool_span:
        tool_span.set_attribute("tool.name", "write_file")
        tool_span.set_attribute("file.path", path)
        await tool.execute(...)
```

### Trace Sampling

```yaml
# otel-collector-config.yml
receivers:
  otlp:
    protocols:
      grpc:
      http:

processors:
  batch:
  tail_sampling:
    decision_wait: 30s
    num_traces: 50000
    expected_new_traces_per_sec: 1000
    policies:
      - name: errors
        type: status_code
        status_code:
          status_codes: [ERROR]
      - name: slow
        type: latency
        latency:
          threshold_ms: 5000
      - name: normal
        type: probabilistic
        probabilistic:
          sampling_percentage: 10

exporters:
  otlp:
    endpoint: tempo:4317
    tls:
      insecure: true

service:
  pipelines:
    traces:
      receivers: [otlp]
      processors: [batch, tail_sampling]
      exporters: [otlp]
```

---

## Alerting Rules

### Critical Alerts (Page Immediately)

```yaml
# alerts/critical.yml
groups:
  - name: maw-critical
    interval: 30s
    rules:
      - alert: APIHighErrorRate
        expr: |
          sum(rate(http_requests_total{status=~"5.."}[5m])) 
          / sum(rate(http_requests_total[5m])) > 0.05
        for: 2m
        labels:
          severity: critical
        annotations:
          summary: "API error rate > 5%"
          description: "5xx error rate is {{ $value | humanizePercentage }}"

      - alert: DispatcherDown
        expr: up{job="maw-dispatcher"} == 0
        for: 1m
        labels:
          severity: critical
        annotations:
          summary: "Dispatcher is down"
          description: "No dispatcher heartbeat for 1 minute"

      - alert: NoWorkersAvailable
        expr: sum(dispatcher_workers_active) == 0
        for: 5m
        labels:
          severity: critical
        annotations:
          summary: "No workers available"
          description: "Worker pool empty for 5 minutes"

      - alert: DatabaseUnavailable
        expr: up{job="postgres"} == 0 or up{job="redis"} == 0
        for: 1m
        labels:
          severity: critical
        annotations:
          summary: "Database unavailable"
          description: "{{ $labels.job }} is down"

      - alert: DiskSpaceCritical
        expr: (node_filesystem_avail_bytes{mountpoint="/"} / node_filesystem_size_bytes{mountpoint="/"}) < 0.1
        for: 5m
        labels:
          severity: critical
        annotations:
          summary: "Disk space < 10%"
          description: "Only {{ $value | humanizePercentage }} disk space remaining"
```

### Warning Alerts (Notify During Business Hours)

```yaml
# alerts/warning.yml
groups:
  - name: maw-warning
    interval: 60s
    rules:
      - alert: TaskQueueBacklog
        expr: dispatcher_queue_depth{status="ready"} > 50
        for: 10m
        labels:
          severity: warning
        annotations:
          summary: "Task queue backlog > 50"
          description: "{{ $value }} tasks waiting in ready queue"

      - alert: HighTaskBlockRate
        expr: |
          rate(tasks_blocked_total[15m]) / rate(tasks_created_total[15m]) > 0.2
        for: 10m
        labels:
          severity: warning
        annotations:
          summary: "High task block rate"
          description: "{{ $value | humanizePercentage }} of tasks blocked"

      - alert: WorkerHighMemoryUsage
        expr: (container_memory_usage_bytes{name=~"worker.*"} / container_spec_memory_limit_bytes{name=~"worker.*"}) > 0.85
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "Worker memory > 85%"
          description: "Worker {{ $labels.name }} at {{ $value | humanizePercentage }} memory"

      - alert: LowTokenQuota
        expr: |
          sum(rate(worker_token_usage_total{type="input"}[1h])) * 3600 * 24 > 0.8 * quota_limit
        for: 1h
        labels:
          severity: warning
        annotations:
          summary: "Daily token quota > 80%"
          description: "Projected daily usage exceeds 80% of quota"

      - alert: QualityGateFailures
        expr: increase(quality_gate_failures_total[1h]) > 5
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "Quality gate failures spike"
          description: "{{ $value }} quality gate failures in last hour"
```

### Info Alerts (Log Only)

```yaml
# alerts/info.yml
groups:
  - name: maw-info
    interval: 300s
    rules:
      - alert: NewDeployment
        expr: changes(deployment_version[5m]) > 0
        labels:
          severity: info
        annotations:
          summary: "New deployment detected"
          description: "Version {{ $labels.version }} deployed"

      - alert: HighTaskVolume
        expr: rate(tasks_created_total[1h]) > 100
        labels:
          severity: info
        annotations:
          summary: "High task creation rate"
          description: "{{ $value }} tasks/hour created"
```

---

## Alertmanager Configuration

```yaml
# alertmanager.yml
global:
  resolve_timeout: 5m
  smtp_smarthost: 'smtp.gmail.com:587'
  smtp_from: 'alerts@your-domain.com'
  smtp_auth_username: 'alerts@your-domain.com'
  smtp_auth_password: '${SMTP_PASSWORD}'

route:
  group_by: ['alertname', 'severity']
  group_wait: 30s
  group_interval: 5m
  repeat_interval: 4h
  receiver: 'default'
  routes:
    - match:
        severity: critical
      receiver: 'pagerduty'
      continue: true
    - match:
        severity: warning
      receiver: 'slack-warning'
    - match:
        severity: info
      receiver: 'slack-info'

receivers:
  - name: 'default'
    email_configs:
      - to: 'team@your-domain.com'
        send_resolved: true

  - name: 'pagerduty'
    pagerduty_configs:
      - service_key: '${PAGERDUTY_KEY}'
        severity: critical
        details:
          runbook: 'https://wiki.your-domain.com/runbooks/{{ .GroupLabels.alertname }}'

  - name: 'slack-warning'
    slack_configs:
      - api_url: '${SLACK_WEBHOOK_WARNING}'
        channel: '#alerts-warning'
        title: '⚠️ {{ .GroupLabels.alertname }}'
        text: '{{ range .Alerts }}{{ .Annotations.description }}\n{{ end }}'
        send_resolved: true

  - name: 'slack-info'
    slack_configs:
      - api_url: '${SLACK_WEBHOOK_INFO}'
        channel: '#alerts-info'
        title: 'ℹ️ {{ .GroupLabels.alertname }}'
        text: '{{ range .Alerts }}{{ .Annotations.description }}\n{{ end }}'

inhibit_rules:
  - source_match:
      severity: 'critical'
    target_match:
      severity: 'warning'
    equal: ['alertname', 'instance']
```

---

## Grafana Dashboards

### Dashboard Provisioning

```yaml
# grafana/dashboards.yml
apiVersion: 1

providers:
  - name: 'MAW Dashboards'
    orgId: 1
    folder: 'Multi-Agent Workflow'
    type: file
    disableDeletion: false
    updateIntervalSeconds: 10
    allowUiUpdates: true
    options:
      path: /etc/grafana/provisioning/dashboards
```

### Key Panels

#### Task Pipeline Dashboard
```json
{
  "title": "Task Pipeline",
  "panels": [
    {
      "title": "Tasks per Status",
      "type": "stat",
      "targets": [
        {"expr": "sum by (status) (tasks_total)", "legendFormat": "{{status}}"}
      ]
    },
    {
      "title": "Task Throughput",
      "type": "graph",
      "targets": [
        {"expr": "rate(tasks_created_total[5m])", "legendFormat": "Created"},
        {"expr": "rate(tasks_completed_total[5m])", "legendFormat": "Completed"},
        {"expr": "rate(tasks_blocked_total[5m])", "legendFormat": "Blocked"}
      ]
    },
    {
      "title": "Cycle Time (p50, p95, p99)",
      "type": "graph",
      "targets": [
        {"expr": "histogram_quantile(0.50, rate(task_duration_seconds_bucket[5m]))", "legendFormat": "p50"},
        {"expr": "histogram_quantile(0.95, rate(task_duration_seconds_bucket[5m]))", "legendFormat": "p95"},
        {"expr": "histogram_quantile(0.99, rate(task_duration_seconds_bucket[5m]))", "legendFormat": "p99"}
      ]
    }
  ]
}
```

#### Agent Performance Dashboard
```json
{
  "title": "Agent Performance",
  "panels": [
    {
      "title": "Turns per Task by Profile",
      "type": "heatmap",
      "targets": [
        {"expr": "sum by (profile, le) (rate(worker_agent_turns_bucket[5m]))", "format": "heatmap"}
      ]
    },
    {
      "title": "Tool Call Success Rate",
      "type": "graph",
      "targets": [
        {"expr": "sum by (tool) (rate(worker_tool_calls_total{result=\"success\"}[5m])) / sum by (tool) (rate(worker_tool_calls_total[5m]))", "legendFormat": "{{tool}}"}
      ]
    },
    {
      "title": "Token Usage by Model",
      "type": "graph",
      "targets": [
        {"expr": "sum by (model) (rate(worker_token_usage_total{type=\"input\"}[5m]))", "legendFormat": "{{model}} input"},
        {"expr": "sum by (model) (rate(worker_token_usage_total{type=\"output\"}[5m]))", "legendFormat": "{{model}} output"}
      ]
    }
  ]
}
```

---

## Cost Monitoring

### Token Cost Tracking

```prometheus
# Daily cost per model
sum by (model) (
  rate(worker_token_usage_total{type="input"}[24h]) * input_cost_per_1k
  + rate(worker_token_usage_total{type="output"}[24h]) * output_cost_per_1k
) / 1000 * 24
```

### Cost Dashboard
- Daily/Monthly spend by model
- Cost per task by profile
- Budget utilization (% of monthly limit)
- Projected monthly cost

---

## Runbooks

### Runbook: APIHighErrorRate
1. Check API logs: `docker compose logs api | grep ERROR`
2. Check dispatcher status: `curl /dispatcher/status`
3. Check database: `docker compose exec api python -c "from db import check; check()"`
4. If DB issue: restart DB, check connections
5. If dispatcher issue: restart dispatcher
6. If code issue: check recent deployments, rollback if needed

### Runbook: NoWorkersAvailable
1. Check worker pods: `kubectl get pods -l app=worker`
2. Check dispatcher logs for spawn errors
3. Check resource quotas: `kubectl describe quota`
4. Check image pull secrets
5. Scale up worker deployment

### Runbook: TaskQueueBacklog
1. Check worker count vs queue depth
2. Scale workers: `docker compose up -d --scale worker=10`
3. Check for stuck tasks: `hermes-kanban list --status running`
4. Block/investigate stuck tasks
5. Consider increasing `DISPATCHER_MAX_CONCURRENT`

---

*See also: [Deployment Guide](deployment-guide.md) | [Backup & Recovery](backup-recovery.md) | [Scaling Guide](scaling-guide.md)*