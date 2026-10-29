# Backup & Recovery

Disaster recovery procedures for the Multi-Agent Workflow System.

## Backup Strategy

### What to Backup

| Component | Method | Frequency | Retention |
|-----------|--------|-----------|-----------|
| Kanban Database (SQLite/PostgreSQL) | Dump/Snapshot | Daily + Before deployments | 30 days |
| File Storage (workspace, attachments) | Tar/Gzip | Daily | 14 days |
| Configuration | Git (config/) | On change | Forever |
| Docker Volumes | Volume snapshot | Daily | 7 days |
| Secrets | External secret manager | On change | Forever |

### Backup Schedule

```
Daily (02:00 UTC):
  ├─ Kanban DB dump (compressed)
  ├─ File storage archive
  └─ Volume snapshots

Weekly (Sunday 03:00 UTC):
  ├─ Full system state export
  └─ Configuration snapshot

Before Deployment:
  ├─ Pre-deployment DB snapshot
  └─ Current config backup

On Demand:
  ├─ Before major changes
  └─ Before migrations
```

---

## Database Backup

### SQLite (Development/Single-Node)

```bash
#!/bin/bash
# backup-sqlite.sh

set -euo pipefail

DB_PATH="${1:-data/kanban.db}"
BACKUP_DIR="${2:-backups}"
DATE=$(date +%Y%m%d-%H%M%S)
BACKUP_FILE="${BACKUP_DIR}/kanban-${DATE}.db.gz"

mkdir -p "${BACKUP_DIR}"

# Online backup (requires sqlite3)
sqlite3 "${DB_PATH}" ".backup '${BACKUP_DIR}/kanban-${DATE}.db'"
gzip "${BACKUP_DIR}/kanban-${DATE}.db"

# Verify
sqlite3 "${BACKUP_DIR}/kanban-${DATE}.db.gz" "PRAGMA integrity_check;"

echo "Backup created: ${BACKUP_FILE}"
```

### PostgreSQL (Production)

```bash
#!/bin/bash
# backup-postgres.sh

set -euo pipefail

DB_HOST="${POSTGRES_HOST:-localhost}"
DB_USER="${POSTGRES_USER:-kanban}"
DB_NAME="${POSTGRES_DB:-kanban}"
BACKUP_DIR="${1:-backups}"
DATE=$(date +%Y%m%d-%H%M%S)
BACKUP_FILE="${BACKUP_DIR}/kanban-${DATE}.sql.gz"

mkdir -p "${BACKUP_DIR}"

# Dump with compression
pg_dump -h "${DB_HOST}" -U "${DB_USER}" -d "${DB_NAME}" \
  --no-owner --no-privileges --clean --if-exists | gzip > "${BACKUP_FILE}"

# Verify
gunzip -c "${BACKUP_FILE}" | head -20

echo "Backup created: ${BACKUP_FILE}"
```

### Automated Backup (Cron)

```bash
# /etc/cron.d/maw-backup
# SQLite (dev)
0 2 * * * root /opt/maw/backup-sqlite.sh /opt/maw/data/kanban.db /opt/maw/backups >> /var/log/maw-backup.log 2>&1

# PostgreSQL (prod)
0 2 * * * root /opt/maw/backup-postgres.sh /opt/maw/backups >> /var/log/maw-backup.log 2>&1

# Cleanup old backups
0 3 * * * root find /opt/maw/backups -name "kanban-*.gz" -mtime +30 -delete
```

### Kubernetes CronJob

```yaml
# k8s/backup-cronjob.yaml
apiVersion: batch/v1
kind: CronJob
metadata:
  name: maw-db-backup
  namespace: multi-agent-workflow
spec:
  schedule: "0 2 * * *"
  concurrencyPolicy: Forbid
  successfulJobsHistoryLimit: 3
  failedJobsHistoryLimit: 1
  jobTemplate:
    spec:
      template:
        spec:
          serviceAccountName: backup-sa
          containers:
          - name: backup
            image: postgres:16-alpine
            env:
            - name: PGHOST
              value: postgresql
            - name: PGUSER
              valueFrom:
                secretKeyRef:
                  name: maw-secrets
                  key: POSTGRES_USER
            - name: PGPASSWORD
              valueFrom:
                secretKeyRef:
                  name: maw-secrets
                  key: POSTGRES_PASSWORD
            - name: PGDATABASE
              value: kanban
            command:
            - /bin/sh
            - -c
            - |
              set -euo pipefail
              DATE=$(date +%Y%m%d-%H%M%S)
              pg_dump --no-owner --no-privileges --clean --if-exists | gzip > /backup/kanban-${DATE}.sql.gz
              # Upload to S3/GCS
              aws s3 cp /backup/kanban-${DATE}.sql.gz s3://maw-backups/db/
              # Cleanup local
              find /backup -name "kanban-*.sql.gz" -mtime +7 -delete
            volumeMounts:
            - name: backup-storage
              mountPath: /backup
          restartPolicy: OnFailure
          volumes:
          - name: backup-storage
            emptyDir: {}
```

---

## File Storage Backup

### Workspace & Attachments

```bash
#!/bin/bash
# backup-files.sh

set -euo pipefail

STORAGE_PATH="${1:-data}"
BACKUP_DIR="${2:-backups}"
DATE=$(date +%Y%m%d-%H%M%S)

mkdir -p "${BACKUP_DIR}"

# Workspace (exclude temp/cache)
tar -czf "${BACKUP_DIR}/workspace-${DATE}.tar.gz" \
  --exclude="*/.cache/*" \
  --exclude="*/__pycache__/*" \
  --exclude="*/.pytest_cache/*" \
  --exclude="*/node_modules/*" \
  -C "${STORAGE_PATH}" workspace

# Attachments
tar -czf "${BACKUP_DIR}/attachments-${DATE}.tar.gz" \
  -C "${STORAGE_PATH}" attachments

# Config (version controlled, but backup for quick restore)
tar -czf "${BACKUP_DIR}/config-${DATE}.tar.gz" \
  -C "${STORAGE_PATH}" ../config

echo "File backups created in ${BACKUP_DIR}"
```

### Docker Volume Backup

```bash
#!/bin/bash
# backup-volumes.sh

set -euo pipefail

BACKUP_DIR="${1:-backups}"
DATE=$(date +%Y%m%d-%H%M%S)

mkdir -p "${BACKUP_DIR}"

# Backup each named volume
for volume in maw_data maw_workspace maw_redis-data maw_postgres-data; do
  docker run --rm \
    -v "${volume}:/source:ro" \
    -v "${BACKUP_DIR}:/backup" \
    alpine tar -czf "/backup/${volume}-${DATE}.tar.gz" -C /source .
done

echo "Volume backups created in ${BACKUP_DIR}"
```

---

## Recovery Procedures

### Scenario 1: Database Corruption (SQLite)

```bash
# 1. Stop services
docker compose down

# 2. Restore latest good backup
LATEST=$(ls -t backups/kanban-*.db.gz | head -1)
gunzip -c "${LATEST}" > data/kanban.db

# 3. Verify integrity
sqlite3 data/kanban.db "PRAGMA integrity_check;"

# 4. Restart services
docker compose up -d

# 5. Verify
curl http://localhost:8000/health
hermes-kanban list --limit 5
```

### Scenario 2: Database Corruption (PostgreSQL)

```bash
# 1. Stop application (keep DB running)
kubectl scale deployment api dispatcher worker --replicas=0 -n multi-agent-workflow

# 2. Restore from backup
LATEST=$(aws s3 ls s3://maw-backups/db/ | sort | tail -1 | awk '{print $4}')
aws s3 cp "s3://maw-backups/db/${LATEST}" - | gunzip | psql -h postgresql -U kanban -d kanban

# 3. Verify
psql -h postgresql -U kanban -d kanban -c "SELECT count(*) FROM tasks;"

# 4. Restart application
kubectl scale deployment api dispatcher worker --replicas=3 -n multi-agent-workflow
```

### Scenario 3: Complete Site Recovery

```bash
#!/bin/bash
# disaster-recovery.sh

set -euo pipefail

BACKUP_DATE="${1:-latest}"  # or YYYYMMDD-HHMMSS
RESTORE_DIR="/tmp/maw-restore"

echo "=== Multi-Agent Workflow Disaster Recovery ==="
echo "Restore date: ${BACKUP_DATE}"
echo "Restore dir: ${RESTORE_DIR}"
echo ""

# 1. Prepare restore directory
mkdir -p "${RESTORE_DIR}"
cd "${RESTORE_DIR}"

# 2. Download backups
if [ "${BACKUP_DATE}" = "latest" ]; then
  DB_BACKUP=$(aws s3 ls s3://maw-backups/db/ | sort | tail -1 | awk '{print $4}')
  FILES_BACKUP=$(aws s3 ls s3://maw-backups/files/ | sort | tail -1 | awk '{print $4}')
  VOLUMES_BACKUP=$(aws s3 ls s3://maw-backups/volumes/ | sort | tail -1 | awk '{print $4}')
else
  DB_BACKUP="kanban-${BACKUP_DATE}.sql.gz"
  FILES_BACKUP="workspace-${BACKUP_DATE}.tar.gz"
  VOLUMES_BACKUP="volumes-${BACKUP_DATE}.tar.gz"
fi

echo "Downloading backups..."
aws s3 cp "s3://maw-backups/db/${DB_BACKUP}" .
aws s3 cp "s3://maw-backups/files/${FILES_BACKUP}" .
aws s3 cp "s3://maw-backups/volumes/${VOLUMES_BACKUP}" .

# 3. Restore database
echo "Restoring database..."
gunzip -c "${DB_BACKUP}" | psql -h postgresql -U kanban -d kanban

# 4. Restore file storage
echo "Restoring file storage..."
tar -xzf "${FILES_BACKUP}" -C /opt/maw/data/

# 5. Restore volumes (if using named volumes)
echo "Restoring volumes..."
for vol in maw_data maw_workspace maw_redis-data; do
  docker volume create "${vol}" 2>/dev/null || true
  docker run --rm -v "${vol}:/target" -v "${RESTORE_DIR}:/backup" alpine \
    tar -xzf "/backup/${vol}-${BACKUP_DATE}.tar.gz" -C /target
done

# 6. Restart all services
echo "Restarting services..."
docker compose up -d
# OR: kubectl rollout restart deployment -n multi-agent-workflow

# 7. Verify
echo "Verifying..."
sleep 10
curl -f http://localhost:8000/health
hermes-kanban list --limit 5

echo "=== Recovery Complete ==="
```

### Scenario 4: Configuration Recovery

```bash
# Config is in Git - restore from repo
git clone https://github.com/your-org/multi-agent-workflow.git
cd multi-agent-workflow
git checkout main  # or specific tag

# Verify config
hermes-kanban doctor --config config/
```

### Scenario 5: Partial Data Loss (Single Task)

```bash
# Restore specific task from backup DB
sqlite3 backups/kanban-20251015-020000.db \
  "SELECT * FROM tasks WHERE id='t_abc123';" > /tmp/task_restore.sql

# Apply to production DB
sqlite3 data/kanban.db < /tmp/task_restore.sql

# Restore attachments if any
# (attachments stored in file system, restore from file backup)
```

---

## Recovery Testing

### Monthly DR Drill

```bash
#!/bin/bash
# dr-drill.sh

set -euo pipefail

DRILL_DATE=$(date +%Y%m%d)
DRILL_DIR="/tmp/dr-drill-${DRILL_DATE}"

echo "=== Monthly DR Drill: ${DRILL_DATE} ==="

# 1. Create isolated test environment
mkdir -p "${DRILL_DIR}"
cd "${DRILL_DIR}"

# 2. Restore latest backup to test DB
LATEST=$(ls -t /opt/maw/backups/kanban-*.db.gz | head -1)
gunzip -c "${LATEST}" > test-kanban.db

# 3. Start test stack with restored data
cat > docker-compose.drill.yml << 'EOF'
version: '3.8'
services:
  api:
    image: ghcr.io/your-org/multi-agent-workflow-api:latest
    environment:
      - DATABASE_URL=sqlite:///data/test-kanban.db
    volumes:
      - ./test-kanban.db:/app/data/kanban.db:ro
      - ./config:/app/config:ro
    ports:
      - "18000:8000"
  dispatcher:
    image: ghcr.io/your-org/multi-agent-workflow-dispatcher:latest
    environment:
      - DATABASE_URL=sqlite:///data/test-kanban.db
    volumes:
      - ./test-kanban.db:/app/data/kanban.db:ro
      - ./config:/app/config:ro
EOF

docker compose -f docker-compose.drill.yml up -d

# 4. Run verification tests
sleep 10
curl -f http://localhost:18000/health

# Test task creation
TASK_ID=$(hermes-kanban --db-path ./test-kanban.db create \
  --title "DR Drill Test" \
  --assignee sdlc-developer \
  --output json | jq -r .id)

# Wait and verify
hermes-kanban --db-path ./test-kanban.db wait --task-id "${TASK_ID}" --timeout 60
RESULT=$(hermes-kanban --db-path ./test-kanban.db show --task-id "${TASK_ID}" --output json | jq -r .status)

if [ "${RESULT}" = "done" ]; then
  echo "✅ DR Drill PASSED"
else
  echo "❌ DR Drill FAILED: Task status = ${RESULT}"
  exit 1
fi

# 5. Cleanup
docker compose -f docker-compose.drill.yml down
rm -rf "${DRILL_DIR}"

echo "=== DR Drill Complete ==="
```

### Automated DR Validation (CI)

```yaml
# .github/workflows/dr-validation.yml
name: DR Validation

on:
  schedule:
    - cron: '0 4 * * 0'  # Weekly Sunday 4 AM
  workflow_dispatch:

jobs:
  dr-test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      
      - name: Download latest backup
        run: |
          aws s3 cp s3://maw-backups/db/latest.db.gz ./kanban.db.gz
          gunzip ./kanban.db.gz
      
      - name: Start test stack
        run: |
          docker compose -f docker-compose.test.yml up -d
      
      - name: Run verification
        run: |
          # Test API
          curl -f http://localhost:8000/health
          
          # Test task flow
          TASK_ID=$(hermes-kanban create --title "DR Test" --assignee sdlc-developer --output json | jq -r .id)
          hermes-kanban wait --task-id $TASK_ID --timeout 120
          STATUS=$(hermes-kanban show --task-id $TASK_ID --output json | jq -r .status)
          
          if [ "$STATUS" != "done" ]; then
            echo "DR validation failed: task status = $STATUS"
            exit 1
          fi
      
      - name: Cleanup
        if: always()
        run: docker compose -f docker-compose.test.yml down
```

---

## Backup Verification Checklist

### Weekly
- [ ] Latest backup exists and is non-zero size
- [ ] Backup integrity check passes (`PRAGMA integrity_check` / `pg_dump` test restore)
- [ ] Backup age < 24 hours
- [ ] Off-site copy exists (S3/GCS)

### Monthly
- [ ] Full restore test completes successfully
- [ ] All services start with restored data
- [ ] Task creation/completion works
- [ ] Attachments accessible
- [ ] Recovery time documented (RTO)
- [ ] Data loss measured (RPO)

### Quarterly
- [ ] Full disaster recovery drill
- [ ] Cross-region restore test
- [ ] Runbook accuracy verified
- [ ] Team notification procedures tested

---

## Key Metrics (RTO/RPO)

| Metric | Target | Measurement |
|--------|--------|-------------|
| **RPO** (Recovery Point Objective) | < 24 hours | Daily backup frequency |
| **RTO** (Recovery Time Objective) | < 2 hours | DR drill measurement |
| **Backup Success Rate** | 100% | Monitoring alert on failure |
| **Restore Test Pass Rate** | 100% | Monthly drill results |

---

*See also: [Deployment Guide](deployment-guide.md) | [Monitoring & Alerting](monitoring-alerting.md) | [Scaling Guide](scaling-guide.md)*