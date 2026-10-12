# Multi-Agent Workflow Platform — single entry point for local development.
#
# All targets proxy to docker compose so the whole platform is started,
# stopped and inspected with one documented command.

.PHONY: help up down logs ps

COMPOSE  := docker compose

help: ## Show available targets
	@echo "Multi-Agent Workflow Platform — local development"
	@echo ""
	@echo "Usage:  make <target>"
	@echo ""
	@echo "Targets:"
	@echo "  up     Build images and start all services in the background"
	@echo "  down   Stop and remove all services, containers and networks"
	@echo "  logs   Tail live logs from all services"
	@echo "  ps     Show service status (Up / healthy)"

up: ## Build and start all services (docker compose up -d --build)
	$(COMPOSE) up -d --build

down: ## Stop and remove all services
	$(COMPOSE) down

logs: ## Tail logs from all services
	$(COMPOSE) logs -f --tail=100

ps: ## Show service status
	$(COMPOSE) ps