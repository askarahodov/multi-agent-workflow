# Troubleshooting Guide

Common issues and solutions for the Multi-Agent Workflow System.

## Quick Diagnosis

### Check Service Health
```bash
# All services
docker compose ps

# Individual service logs
docker compose logs api
docker compose logs frontend
docker compose logs dispatcher
docker compose logs worker

# API health endpoint
curl -s http://localhost:8000/health | jq .
```

### Check Dispatcher Status
```bash
# Via CLI
hermes-kanban dispatch status

# Or check logs
docker compose logs dispatcher --tail 100
```

### Check Database
```bash
# Inspect Kanban DB
sqlite3 data/kanban.db ".tables"
sqlite3 data/kanban.db "SELECT id, title, status, assignee FROM tasks LIMIT 10;"
sqlite3 data/kanban.db "SELECT * FROM events ORDER BY timestamp DESC LIMIT 20;"
```

---

## Common Issues

### 1. Services Won't Start

#### Port Already in Use
```bash
# Check what's using ports 3000/8000
lsof -i :3000 -i :8000

# Kill or change ports in docker-compose.yml
```

#### Docker Compose Version
```bash
# Requires Docker Compose v2 (plugin)
docker compose version
# Should show: Docker Compose version v2.20+

# If using standalone docker-compose (v1), migrate:
# https://docs.docker.com/compose/migrate/
```

#### Permission Denied on Volumes
```bash
# Fix data directory permissions
sudo chown -R $USER:$USER data/
sudo chmod -R 755 data/
```

### 2. Agent Fails to Spawn

#### OpenRouter Quota Exhausted
```bash
# Error: rc=75, rate_limited
# Solution: Wait for quota reset (daily at 00:00 UTC) or switch model

# Check current model in profile
cat config/profiles/sdlc-developer.yaml | grep -A2 model:

# Temporarily override
hermes-kanban create --title "Task" --assignee sdlc-developer \
  --model anthropic/claude-3.5-sonnet --provider anthropic
```

#### Model Not Found
```bash
# Verify model name on OpenRouter
curl -H "Authorization: Bearer $OPENROUTER_API_KEY" \
  https://openrouter.ai/api/v1/models | jq '.data[] | select(.id=="nvidia/nemotron-3-ultra-550b-a55b:free")'

# Use exact model ID from API response
```

#### Profile Not Found
```bash
# List available profiles
ls config/profiles/

# Check assignee matches profile name exactly
hermes-kanban create --title "Test" --assignee sdlc-developer
# Profile file must be: config/profiles/sdlc-developer.yaml
```

### 3. Task Stuck in `running`

#### Worker Crashed
```bash
# Check worker logs
docker compose logs worker --tail 200 | grep -i error

# Common causes:
# - OOM (memory limit): Increase worker memory in docker-compose.yml
# - Timeout: Increase DISPATCHER_WORKER_TIMEOUT
# - Tool error: Check task logs in Kanban UI
```

#### Heartbeat Timeout
```bash
# Worker not sending heartbeats
# Check dispatcher logs for "heartbeat timeout"
# Increase heartbeat timeout in dispatcher.yaml:
# heartbeat_timeout_seconds: 300
```

#### Infinite Loop / Iteration Budget Exhausted
```bash
# Error: "Iteration budget exhausted (60/60)"
# Solutions:
# 1. Increase goal_max_turns in task creation
hermes-kanban create ... --goal-mode --goal-max-turns 100

# 2. Fix underlying issue (lint errors, test failures)
# Check task logs for specific failures
```

### 4. Task Stuck in `ready` / Not Dispatched

#### No Matching Worker
```bash
# Check if worker with matching profile is running
docker compose ps | grep worker

# Start worker for specific profile
docker compose up -d --scale worker=3
# Workers auto-register for all profiles
```

#### Dependency Not Met
```bash
# Check parent tasks
hermes-kanban show --task-id TASK_ID | grep -A5 "parents"

# Parents must be in 'done' status
hermes-kanban list --status done
```

#### Concurrency Limit Reached
```bash
# Check DISPATCHER_MAX_CONCURRENT in .env
# Default: 10 concurrent tasks
# Increase if needed:
echo "DISPATCHER_MAX_CONCURRENT=20" >> .env
docker compose restart dispatcher
```

### 5. Kanban Database Issues

#### Database Locked
```bash
# Error: "database is locked"
# Cause: Multiple dispatcher processes
# Solution: Ensure only one dispatcher runs

# Check for multiple dispatchers
ps aux | grep dispatcher

# Kill extras, restart single dispatcher
docker compose restart dispatcher
```

#### Corrupted Database
```bash
# Backup first!
cp data/kanban.db data/kanban.db.backup

# Check integrity
sqlite3 data/kanban.db "PRAGMA integrity_check;"

# If corrupted, restore from backup or rebuild:
# 1. Stop all services
# 2. Restore backup
# 3. Restart
```

### 6. Quality Gate Failures

#### Linting Errors (Ruff/MyPy)
```bash
# Run locally to see errors
cd .worktrees/<task-id>/workspace
ruff check .
mypy .

# Auto-fix ruff issues
ruff check --fix .

# Common fixes:
# - Import order (I001): ruff check --select I --fix
# - Unused imports (F401): ruff check --select F401 --fix
# - Line length (E501): Adjust MAX_LINE in quality-gates/config
```

#### Test Failures
```bash
# Run tests in workspace
cd .worktrees/<task-id>/workspace
pytest -v

# Check coverage
pytest --cov=src --cov-report=term-missing

# Coverage threshold: 80% line coverage
# Adjust in quality-gates.yaml if needed
```

#### Security Gate Failures
```bash
# Run security scans locally
bandit -r src/
safety check
trivy fs .

# Common issues:
# - Hardcoded secrets: Use environment variables
# - Vulnerable dependencies: Update requirements.txt
# - SQL injection: Use parameterized queries
```

### 7. Frontend Issues

#### Blank Page / White Screen
```bash
# Check browser console for errors
# Common: API URL mismatch

# Verify VITE_API_URL in frontend/.env
echo "VITE_API_URL=http://localhost:8000" > frontend/.env
docker compose restart frontend
```

#### WebSocket/SSE Connection Failed
```bash
# Check nginx/proxy config if using reverse proxy
# Ensure WebSocket upgrade headers passed:
# proxy_http_version 1.1;
# proxy_set_header Upgrade $http_upgrade;
# proxy_set_header Connection "upgrade";
```

#### Stale Data
```bash
# Hard refresh: Ctrl+Shift+R (Cmd+Shift+R on Mac)
# Or clear browser cache for localhost:3000
```

### 8. Git Worktree Issues

#### Worktree Creation Failed
```bash
# Error: "fatal: 'feature/xyz' is not a valid branch name"
# Check project slug + task ID format
# Branch name: <project-slug>-<task-id>

# Verify git repo is clean
git status

# Clean up stale worktrees
git worktree list
git worktree remove --force <path>
```

#### Merge Conflicts on Completion
```bash
# Release agent handles merge
# If manual: checkout main, merge feature branch
git checkout main
git merge feature/my-project-task-123
```

---

## Debugging Workflows

### Enable Debug Logging
```bash
# In .env
LOG_LEVEL=DEBUG

# Restart services
docker compose restart
```

### Inspect Worker Workspace
```bash
# Workspaces at .worktrees/<task-id>/
ls -la /mnt/data/multi-agent-workflow/.worktrees/

# Enter workspace
cd /mnt/data/multi-agent-workflow/.worktrees/<task-id>/workspace
# Run commands as the agent would
```

### Trace Task Execution
```bash
# Get full task event log
hermes-kanban show --task-id TASK_ID | jq '.events[] | {timestamp, type, message}'

# Or via API
curl -s http://localhost:8000/tasks/TASK_ID/events | jq .
```

### Profile Worker Performance
```bash
# Add profiling to worker startup
# In docker-compose.yml worker command:
# command: python -m cProfile -o profile.stats -m agent_loop

# Analyze
python -c "import pstats; p = pstats.Stats('profile.stats'); p.sort_stats('cumulative').print_stats(20)"
```

---

## Getting Help

### Log Collection for Support
```bash
# Collect all logs
mkdir -p debug-logs
docker compose logs --no-color > debug-logs/all.log 2>&1
cp data/kanban.db debug-logs/
tar -czf debug-logs.tar.gz debug-logs/
```

### Community Resources
- **GitHub Issues:** https://github.com/your-org/multi-agent-workflow/issues
- **Discussions:** https://github.com/your-org/multi-agent-workflow/discussions
- **Documentation:** https://docs.your-domain.com (when running)

### Reporting Bugs
Include:
1. System info: `docker compose version`, `python --version`, `node --version`
2. Error logs (sanitized)
3. Steps to reproduce
4. Task ID and board slug
5. Expected vs actual behavior

---

*Last updated: 2025-10-16 | Version: 0.1.0-rc1*