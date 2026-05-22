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
	@echo "FAST DEV LOOP (recommended):"
	@echo "  1. \033[36mmake dev\033[0m              — first-time bring-up (builds SPA + starts stack with bind mounts)"
	@echo "  2. edit Python in apps/api/app → \033[33msaves auto-reload in <1s\033[0m (uvicorn --reload)"
	@echo "  3. edit React  in apps/web/src → run \033[36mmake spa\033[0m (~30s) → container serves new JS immediately"
	@echo "  4. dep change (pyproject.toml / package.json / Containerfile) → \033[36mmake rebuild\033[0m"
	@echo ""
	@echo "Compose runtime in use: $(COMPOSE_RUNTIME)"
	@echo "(override with COMPOSE_RUNTIME=...)"

# ---------------------------------------------------------------------------
# Stack lifecycle
# ---------------------------------------------------------------------------
.PHONY: dev
dev:  ## RECOMMENDED dev workflow — builds SPA + brings up with bind mounts (uvicorn --reload)
	@if [ ! -f apps/api/static/index.html ]; then \
		echo "No SPA build found; running \`make spa\` first..."; \
		$(MAKE) spa; \
	fi
	@$(COMPOSE) -f $(COMPOSE_OVERRIDE_DEV) up -d --build
	@echo ""
	@echo "OK — stack up. Backend Python edits auto-reload via uvicorn."
	@echo "     For frontend changes: \`make spa\` (~30s) — container picks it up immediately."

.PHONY: up
up:  ## Bring the stack up (production-like; no bind mounts; uses image's baked SPA)
	@$(COMPOSE) up -d --build

.PHONY: up-dev
up-dev:  ## Bring the stack up with the dev override (bind mounts, uvicorn --reload)
	@$(COMPOSE) -f $(COMPOSE_OVERRIDE_DEV) up -d --build

.PHONY: api-restart
api-restart:  ## Restart only the api container (use when uvicorn --reload misses a change)
	@$(COMPOSE) -f $(COMPOSE_OVERRIDE_DEV) restart api

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

.PHONY: rebuild
rebuild:  ## Cache-aware rebuild of the api image (use after dep changes)
	@echo "Cache-aware rebuild of api image..."
	@$(CONTAINER_CLI) build -f apps/api/Containerfile -t scout/api:dev .
	@$(COMPOSE) -f $(COMPOSE_OVERRIDE_DEV) up -d
	@echo "OK — api image rebuilt (cache-aware) + stack up."
	@echo "    If something seems stale, try \`make rebuild-nocache\`."

.PHONY: rebuild-nocache
rebuild-nocache:  ## Nuclear option: full no-cache rebuild (~3 min)
	@echo "Force-rebuilding api image with --no-cache (slow)..."
	@$(COMPOSE) down 2>/dev/null || true
	@$(CONTAINER_CLI) rmi -f localhost/scout/api:dev scout/api:dev 2>/dev/null || true
	@$(CONTAINER_CLI) build --no-cache -f apps/api/Containerfile -t scout/api:dev .
	@$(COMPOSE) -f $(COMPOSE_OVERRIDE_DEV) up -d
	@echo "OK — stack up with a freshly-built api image"

.PHONY: nuke
nuke:  ## Destroy stack + volumes (PROMPTS for confirmation)
	@printf "This will delete all named volumes (postgres data, uploads, raw_pages). Type 'nuke' to confirm: " \
	  && read -r ans && [ "$$ans" = "nuke" ] || (echo "Aborted."; exit 1)
	@$(COMPOSE) down -v

# ---------------------------------------------------------------------------
# Database — implemented in steps 03 / 06
# ---------------------------------------------------------------------------
.PHONY: migrate
migrate:  ## Run Alembic migrations to head (inside the api container)
	@$(COMPOSE) exec -T api alembic upgrade head

.PHONY: migrate-create
migrate-create:  ## Create a new Alembic revision: make migrate-create MSG="describe change"
	@if [ -z "$(MSG)" ]; then echo 'usage: make migrate-create MSG="describe change"'; exit 2; fi
	@$(COMPOSE) exec -T api alembic revision --autogenerate -m "$(MSG)"

.PHONY: migrate-history
migrate-history:  ## Show Alembic revision history
	@$(COMPOSE) exec -T api alembic history --verbose

.PHONY: migrate-current
migrate-current:  ## Show currently-applied revision
	@$(COMPOSE) exec -T api alembic current

.PHONY: seed
seed:  ## Re-apply seed data — informational; seeds are baked into Alembic migrations
	@echo "Reference-data seeds (embedding_models row) are baked into Alembic migrations."
	@echo "Run \`make migrate\` to apply them. Team-curated data (pillars, audiences,"
	@echo "SMEs, etc.) is entered via the XLSX workbook (plan 31)."

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
# Detect docker vs podman for one-off `run` calls (build-spa, etc.).
# COMPOSE_RUNTIME is what compose-aware targets use; CONTAINER_CLI is for plain `run`.
CONTAINER_CLI ?= $(shell command -v podman 2>/dev/null || echo docker)

.PHONY: spa
spa: build-spa  ## Alias: build the SPA into apps/api/static (~30s)

.PHONY: build-spa
build-spa:  ## Build the Vite SPA (throwaway node container; deposits in apps/api/static)
	@echo "Building SPA via UBI node-22 container ($(CONTAINER_CLI))..."
	@mkdir -p apps/api/static
	@$(CONTAINER_CLI) run --rm \
	  -v $(PWD)/apps/web:/build/web \
	  -v $(PWD)/apps/api/static:/build/static \
	  -w /build/web \
	  registry.access.redhat.com/ubi9/nodejs-22 \
	  bash -c 'npm install -g pnpm@9.12.0 && pnpm install && pnpm build && rm -rf /build/static/* && cp -R dist/. /build/static/'
	@echo "OK — SPA built into apps/api/static/"

# ---------------------------------------------------------------------------
# Tests — implemented in step 27
# ---------------------------------------------------------------------------
.PHONY: test
test: test-unit  ## Run all tests (today == test-unit; integration + e2e are plan 27 pass 2)

.PHONY: test-unit
test-unit:  ## Run the api unit suite inside the running api container
	@if ! $(CONTAINER_CLI) ps --filter name=scout-api --format '{{.Names}}' 2>/dev/null | grep -q scout-api; then \
	  echo "scout-api container not running — try \`make dev\` first."; exit 2; \
	fi
	@echo "Bootstrapping pip + dev test deps into the live venv (idempotent)..."
	@$(CONTAINER_CLI) exec scout-api python -c 'import pip' 2>/dev/null \
	  || $(CONTAINER_CLI) exec scout-api python -m ensurepip >/dev/null
	@$(CONTAINER_CLI) exec scout-api python -m pip install --quiet pytest pytest-asyncio
	@echo "Running unit tests..."
	@$(CONTAINER_CLI) exec -e PYTHONPATH=/app scout-api python -m pytest /app/tests/unit -q

.PHONY: test-int
test-int:  ## Integration tests against real Postgres (plan 27 pass 2)
	@echo "make test-int: plan 27 pass 2 will wire testcontainers" && exit 1

.PHONY: test-web
test-web:  ## Frontend Vitest suite (plan 27 pass 2)
	@echo "make test-web: plan 27 pass 2 will wire Vitest" && exit 1

.PHONY: e2e
e2e:  ## Playwright end-to-end (plan 27 pass 2)
	@echo "make e2e: plan 27 pass 2 will wire Playwright" && exit 1

.PHONY: eval
eval:  ## LLM evals (plan 27 pass 2)
	@echo "make eval: plan 27 pass 2 will wire evals" && exit 1

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
