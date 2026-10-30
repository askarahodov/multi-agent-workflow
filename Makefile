# Multi-Agent Workflow Platform — single entry point for local development.
#
# Two concerns live here:
#
#   * `up` / `down` / `logs` / `ps` proxy to docker compose, so the whole
#     platform is started, stopped and inspected with one documented command.
#   * `check` is the local analog of the mandatory CI quality gate
#     (`.github/workflows/quality-gate.yml`): backend pytest, frontend
#     type-check/lint/tests/build and the quality-gates security scan. Every
#     step is a prerequisite, so the gate fails as soon as any check fails.

.PHONY: help up down logs ps check backend-test frontend-test frontend-check \
        typecheck lint test security test-gitflow gitflow-hooks gitflow-reap

COMPOSE  := docker compose

# Virtualenv used for the Python checks. The repo ships a uv-managed `.venv`
# (git-ignored); CI creates the same path, so `make check` behaves identically
# locally and in CI. Falls back to the ambient `python3` when no venv exists.
VENV    ?= .venv
PYTHON  := $(shell if [ -x "$(CURDIR)/$(VENV)/bin/python" ]; then \
                     echo "$(CURDIR)/$(VENV)/bin/python"; else echo python3; fi)

# Python subsystems that carry a pytest suite.
PY_SUBSYSTEMS := agent-management orchestration-server quality-gates runtime-hardening tools packages/agent-runtime

help: ## Show available targets
	@echo "Multi-Agent Workflow Platform — local development"
	@echo ""
	@echo "Usage:  make <target>"
	@echo ""
	@echo "Targets:"
	@echo "  up       Build images and start all services in the background"
	@echo "  down     Stop and remove all services, containers and networks"
	@echo "  logs     Tail live logs from all services"
	@echo "  ps       Show service status (Up / healthy)"
	@echo "  check    Run the full local quality gate (CI analog)"
	@echo "  test     Run all backend and frontend tests"
	@echo "  lint     Lint the frontend (eslint)"
	@echo "  typecheck Type-check the frontend (tsc --noEmit)"
	@echo "  gitflow-hooks Install/refresh the GitFlow git hooks (.githooks)"
	@echo "  gitflow-reap  List orphaned task worktrees/branches (never deletes)"

up: ## Build and start all services (docker compose up -d --build)
	$(COMPOSE) up -d --build

down: ## Stop and remove all services
	$(COMPOSE) down

logs: ## Tail logs from all services
	$(COMPOSE) logs -f --tail=100

ps: ## Show service status
	$(COMPOSE) ps

# ---------------------------------------------------------------------------
# Quality gate (local analog of .github/workflows/quality-gate.yml)
# ---------------------------------------------------------------------------

check: lint typecheck backend-test frontend-check security ## Run the full local quality gate (CI analog)
	@echo ""
	@echo "quality gate: ALL CHECKS PASSED"

typecheck: ## Type-check the frontend (tsc --noEmit)
	cd frontend && npm run typecheck

lint: ## Lint the frontend (eslint)
	cd frontend && npm run lint

backend-test: ## Run every backend pytest suite
	@set -e; \
	for svc in $(PY_SUBSYSTEMS); do \
		echo "==> pytest: $$svc"; \
		( cd "$$svc" && "$(PYTHON)" -m pytest tests -q ); \
	done

frontend-test: ## Run the frontend unit tests (vitest)
	cd frontend && npm run test:run

frontend-check: frontend-test ## Frontend unit tests, schema validation and production build
	cd frontend && npm run schema:validate
	cd frontend && npm run build

test: backend-test frontend-test ## Run all backend and frontend tests

test-gitflow: ## Run the GitFlow violation test suite
	@bash -c 'for s in tests/gitflow/test_*.sh; do echo "==> $$(basename $$s)"; bash "$$s" || exit 1; done'

security: ## Static security scan via the quality-gates SecurityGate
	"$(PYTHON)" scripts/security_scan.py

# ---------------------------------------------------------------------------
# GitFlow hooks / worktree hygiene
# ---------------------------------------------------------------------------

gitflow-hooks: ## Install/refresh the GitFlow git hooks (.githooks) for this repo
	bash scripts/install-gitflow-hooks.sh

gitflow-reap: ## List orphaned task worktrees/branches (report-only, never deletes)
	"$(PYTHON)" scripts/git/worktree-lifecycle.py reap
