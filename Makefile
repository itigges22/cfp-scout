# Scout — top-level Makefile.
# Auto-detects whether to drive docker compose or podman compose.

# ---------------------------------------------------------------------------
# Compose runtime detection
# ---------------------------------------------------------------------------
# Order of preference:
#   1. podman-compose binary (older Podman setups)
#   2. podman compose (newer Podman; uses the compose subcommand)
#   3. docker compose (Docker plugin)
# Override by setting COMPOSE_RUNTIME on the command line:
#   make up COMPOSE_RUNTIME="docker compose"
COMPOSE_RUNTIME ?= $(shell command -v podman-compose >/dev/null 2>&1 && echo podman-compose \
                          || (command -v podman >/dev/null 2>&1 && echo "podman compose") \
                          || echo "docker compose")

COMPOSE_FILE := infra/compose/compose.yaml
COMPOSE_OVERRIDE_DEV := infra/compose/compose.override.dev.yaml
COMPOSE_OVERRIDE_PODMAN := infra/compose/compose.override.podman.yaml

COMPOSE := $(COMPOSE_RUNTIME) -f $(COMPOSE_FILE)
ifneq (,$(findstring podman,$(COMPOSE_RUNTIME)))
  COMPOSE := $(COMPOSE) -f $(COMPOSE_OVERRIDE_PODMAN)
endif

.DEFAULT_GOAL := help

# ---------------------------------------------------------------------------
# Help
# ---------------------------------------------------------------------------
.PHONY: help
help:  ## Show this help
	@echo "Scout — available targets:"
	@echo ""
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
		| awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-22s\033[0m %s\n", $$1, $$2}'
	@echo ""
	@echo "Compose runtime in use: $(COMPOSE_RUNTIME)"
	@echo "(override with COMPOSE_RUNTIME=...)"

# ---------------------------------------------------------------------------
# Stack lifecycle
# ---------------------------------------------------------------------------
.PHONY: up
up:  ## Bring the stack up in detached mode
	@$(COMPOSE) up -d --build

.PHONY: up-dev
up-dev:  ## Bring the stack up with the dev override (live reload, host-bound Postgres)
	@$(COMPOSE) -f $(COMPOSE_OVERRIDE_DEV) up -d --build

.PHONY: down
down:  ## Stop the stack (containers + network)
	@$(COMPOSE) down

.PHONY: ps
ps:  ## Show service status
	@$(COMPOSE) ps

.PHONY: logs
logs:  ## Tail logs from a service: make logs SERVICE=api
	@if [ -z "$(SERVICE)" ]; then \
		$(COMPOSE) logs -f --tail=200; \
	else \
		$(COMPOSE) logs -f --tail=200 $(SERVICE); \
	fi

.PHONY: sh
sh:  ## Open a shell in a service: make sh SERVICE=api
	@if [ -z "$(SERVICE)" ]; then echo "usage: make sh SERVICE=api"; exit 2; fi
	@$(COMPOSE) exec $(SERVICE) /bin/bash

.PHONY: nuke
nuke:  ## Destroy stack + volumes (PROMPTS for confirmation)
	@printf "This will delete all named volumes (postgres data, uploads, raw_pages). Type 'nuke' to confirm: " \
	  && read -r ans && [ "$$ans" = "nuke" ] || (echo "Aborted."; exit 1)
	@$(COMPOSE) down -v

# ---------------------------------------------------------------------------
# Database — implemented in steps 03 / 06
# ---------------------------------------------------------------------------
.PHONY: migrate
migrate:  ## Run Alembic migrations (implemented in step 06)
	@echo "make migrate: implemented in step 06" && exit 1

.PHONY: migrate-create
migrate-create:  ## Create a new Alembic revision: make migrate-create MSG="..."
	@echo "make migrate-create: implemented in step 06" && exit 1

.PHONY: seed
seed:  ## Seed reference data (implemented in step 04 + 06)
	@echo "make seed: implemented in step 06" && exit 1

.PHONY: db-dump
db-dump:  ## Dump Postgres to ./backups/<timestamp>.sql.gz
	@mkdir -p backups
	@TS=$$(date +%Y-%m-%d-%H%M%S); \
	  FILE=backups/scout-$$TS.sql.gz; \
	  echo "Dumping to $$FILE..."; \
	  $(COMPOSE) exec -T postgres sh -c \
	    'pg_dump -U "$$POSTGRES_USER" -d "$$POSTGRES_DB" --no-owner --no-privileges --clean --if-exists' \
	    | gzip > $$FILE; \
	  if [ -s $$FILE ]; then \
	    echo "OK ($$FILE, $$(du -h $$FILE | cut -f1))"; \
	  else \
	    rm -f $$FILE; \
	    echo "FAILED — empty dump (is postgres up? \`make up\` first)"; exit 1; \
	  fi

.PHONY: db-restore
db-restore:  ## Restore from a backup: make db-restore FILE=backups/scout-...sql.gz
	@if [ -z "$(FILE)" ]; then echo "usage: make db-restore FILE=backups/scout-YYYY-MM-DD-HHMMSS.sql.gz"; exit 2; fi
	@if [ ! -f "$(FILE)" ]; then echo "no such file: $(FILE)"; exit 2; fi
	@echo "Restoring from $(FILE) (this will OVERWRITE current data)..."
	@printf "Type 'restore' to confirm: " && read -r ans && [ "$$ans" = "restore" ] || (echo "Aborted."; exit 1)
	@gunzip -c "$(FILE)" | $(COMPOSE) exec -T postgres sh -c \
	  'psql -U "$$POSTGRES_USER" -d "$$POSTGRES_DB" --quiet --set ON_ERROR_STOP=1'
	@echo "OK"

.PHONY: db-psql
db-psql:  ## Open a psql shell against the running postgres
	@$(COMPOSE) exec -it postgres sh -c 'psql -U "$$POSTGRES_USER" -d "$$POSTGRES_DB"'

# ---------------------------------------------------------------------------
# Frontend — implemented in step 08
# ---------------------------------------------------------------------------
.PHONY: build-spa
build-spa:  ## Build the Vite SPA into apps/api/static (step 08)
	@echo "make build-spa: implemented in step 08" && exit 1

# ---------------------------------------------------------------------------
# Tests — implemented in step 27
# ---------------------------------------------------------------------------
.PHONY: test
test:  ## Run unit + integration + frontend tests (step 27)
	@echo "make test: implemented in step 27" && exit 1

.PHONY: test-unit
test-unit:
	@echo "make test-unit: implemented in step 27" && exit 1

.PHONY: test-int
test-int:
	@echo "make test-int: implemented in step 27" && exit 1

.PHONY: test-web
test-web:
	@echo "make test-web: implemented in step 27" && exit 1

.PHONY: e2e
e2e:
	@echo "make e2e: implemented in step 27" && exit 1

.PHONY: eval
eval:
	@echo "make eval: implemented in step 27" && exit 1

# ---------------------------------------------------------------------------
# Lint / typecheck / security
# ---------------------------------------------------------------------------
.PHONY: lint
lint:  ## Run pre-commit on all files
	@pre-commit run --all-files

.PHONY: typecheck
typecheck:  ## Run mypy + tsc (implemented as services are added)
	@echo "make typecheck: wired up as services land" && exit 1

.PHONY: security
security:  ## Run gitleaks + trivy on local images (step 29)
	@echo "make security: implemented in step 29" && exit 1
