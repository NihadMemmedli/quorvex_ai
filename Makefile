.PHONY: setup setup-skills dev run clean help docker-up docker-down docker-build check-env logs stop \
        prod-up prod-down prod-down-safe prod-restart prod-logs prod-build prod-build-no-cache prod-status prod-dev \
        backup backup-full backup-status restore-list restore restore-from-minio \
        archival archival-dry-run storage-health minio-console \
        workers-up workers-down workers-scale workers-status workers-logs workers-build \
        swarm-up swarm-down swarm-scale swarm-status \
        k8s-deploy k8s-delete k8s-status k8s-scale k8s-logs \
        db-migrate db-upgrade db-downgrade db-history db-stamp \
        docker-prune volume-sizes db-vacuum health-check upgrade deps-lock \
        load-test \
        k6-workers-up k6-workers-down k6-workers-scale k6-workers-logs k6-workers-status \
        zap-up zap-down zap-status zap-logs \
        lint format test \
        docs-serve docs-build docs-deploy

# Default target
help:
	@echo "Quorvex AI Commands:"
	@echo ""
	@echo "  Setup & Run:"
	@echo "    make setup          - Install dependencies and setup environment"
	@echo "    make setup-skills   - Install Playwright skill dependencies"
	@echo "    make dev            - Start the UI and Backend server (development)"
	@echo "    make run SPEC=...   - Run a specific test spec"
	@echo "    make run-skill S=.. - Run a Playwright skill script"
	@echo ""
	@echo "  Docker (dev):"
	@echo "    make docker-up      - Start all services via Docker Compose"
	@echo "    make docker-down    - Stop all Docker services"
	@echo "    make docker-build   - Rebuild Docker images"
	@echo ""
	@echo "  Docker (prod):"
	@echo "    make prod-up        - Start production services"
	@echo "    make prod-dev       - Start prod with local code (no rebuild needed!)"
	@echo "    make prod-down      - Stop production services"
	@echo "    make prod-down-safe - Stop with backup first (recommended)"
	@echo "    make prod-restart   - Restart backend (picks up code changes)"
	@echo "    make prod-logs      - Tail production logs"
	@echo "    make prod-build     - Rebuild production images (with cache)"
	@echo "    make prod-build-no-cache - Rebuild without cache (force fresh)"
	@echo "    make prod-status    - Show status of all services"
	@echo ""
	@echo "  Backup & Recovery:"
	@echo "    make backup         - Run database-only backup"
	@echo "    make backup-full    - Run full backup (DB + specs + tests + PRDs)"
	@echo "    make backup-status  - Show backup status and history"
	@echo "    make restore-list   - List available backups"
	@echo "    make restore TS=... - Restore from specific timestamp"
	@echo ""
	@echo "  Storage Management:"
	@echo "    make storage-health - Check storage health (DB, MinIO, local)"
	@echo "    make archival       - Run artifact archival (30-day retention)"
	@echo "    make archival-dry-run - Preview archival without changes"
	@echo "    make minio-console  - Open MinIO console in browser"
	@echo ""
	@echo "  Browser Workers (Phase 2 - Docker Isolation):"
	@echo "    make workers-up     - Start with isolated browser workers"
	@echo "    make workers-down   - Stop browser workers"
	@echo "    make workers-scale N=8 - Scale browser workers"
	@echo "    make workers-status - Check worker status"
	@echo "    make workers-logs   - View worker logs"
	@echo "    make workers-build  - Build worker images"
	@echo ""
	@echo "  K6 Load Test Workers (Distributed Execution):"
	@echo "    make k6-workers-up    - Start K6 worker containers (prod)"
	@echo "    make k6-workers-down  - Stop K6 workers"
	@echo "    make k6-workers-scale N=3 - Scale K6 workers"
	@echo "    make k6-workers-status - Check K6 worker status"
	@echo "    make k6-workers-logs  - View K6 worker logs"
	@echo "    make dev-k6-workers-up   - Start dev K6 workers (auto-mounted code)"
	@echo "    make dev-k6-workers-down - Stop dev K6 workers"
	@echo "    make dev-k6-workers-logs - View dev K6 worker logs"
	@echo ""
	@echo "  Security Testing (ZAP DAST):"
	@echo "    make zap-up             - Start ZAP security scanner daemon"
	@echo "    make zap-down           - Stop ZAP scanner"
	@echo "    make zap-status         - Check ZAP scanner status"
	@echo "    make zap-logs           - View ZAP logs"
	@echo ""
	@echo "  Docker Swarm (Enterprise):"
	@echo "    make swarm-up       - Deploy to Docker Swarm"
	@echo "    make swarm-down     - Stop Swarm stack"
	@echo "    make swarm-scale N=8 - Scale Swarm workers"
	@echo "    make swarm-status   - Check Swarm status"
	@echo ""
	@echo "  Kubernetes (Enterprise):"
	@echo "    make k8s-deploy     - Deploy to Kubernetes"
	@echo "    make k8s-delete     - Delete Kubernetes deployment"
	@echo "    make k8s-status     - Check Kubernetes status"
	@echo "    make k8s-scale N=8  - Scale Kubernetes workers"
	@echo "    make k8s-logs       - View Kubernetes logs"
	@echo ""
	@echo "  Database Migrations (PostgreSQL):"
	@echo "    make db-migrate M=..  - Generate new Alembic migration"
	@echo "    make db-upgrade       - Run pending migrations"
	@echo "    make db-downgrade     - Roll back one migration"
	@echo "    make db-history       - Show migration history"
	@echo "    make db-stamp R=...   - Stamp DB at revision (for existing DBs)"
	@echo ""
	@echo "  Maintenance:"
	@echo "    make upgrade          - Full upgrade procedure (backup, pull, migrate, restart)"
	@echo "    make health-check     - Hit all health endpoints and report status"
	@echo "    make docker-prune     - Remove dangling images, stopped containers, build cache"
	@echo "    make volume-sizes     - Show sizes of all Docker volumes"
	@echo "    make db-vacuum        - Run VACUUM ANALYZE on PostgreSQL"
	@echo "    make deps-lock        - Regenerate requirements.lock from current venv"
	@echo ""
	@echo "  Load Testing:"
	@echo "    make load-test SPEC=... - Generate and run K6 load test from spec"
	@echo ""
	@echo "  Utilities:"
	@echo "    make stop           - Stop all running services"
	@echo "    make check-env      - Validate environment configuration"
	@echo "    make logs           - Tail backend and frontend logs"
	@echo "    make clean          - Remove temporary run artifacts"
	@echo ""
	@echo "  Examples:"
	@echo "    make run SPEC=specs/examples/hello-world.md"
	@echo "    make backup-full"
	@echo "    make restore TS=20240115_143022"

# ==========================================
# SETUP & DEVELOPMENT
# ==========================================

setup:
	@./setup.sh

setup-skills:
	@echo "Installing Playwright skill dependencies..."
	@if [ -d ".claude/skills/playwright" ]; then \
		cd .claude/skills/playwright && npm install && \
		echo "Installing Chromium for skill execution..." && \
		npx playwright install chromium && \
		echo "✅ Skill dependencies installed"; \
	else \
		echo "❌ Skill directory not found: .claude/skills/playwright"; \
		exit 1; \
	fi

run-skill:
	@if [ -z "$(S)" ]; then \
		echo "Error: S (script) argument is required."; \
		echo "Usage: make run-skill S=path/to/script.js"; \
		exit 1; \
	fi
	@source venv/bin/activate && python orchestrator/cli.py --run-skill "$(S)"

dev:
	@./start-ui.sh

run:
	@if [ -z "$(SPEC)" ]; then \
		echo "Error: SPEC argument is required."; \
		echo "Usage: make run SPEC=path/to/spec.md"; \
		exit 1; \
	fi
	@source venv/bin/activate && python orchestrator/cli.py "$(SPEC)"

load-test:
	@if [ -z "$(SPEC)" ]; then \
		echo "Error: SPEC argument is required."; \
		echo "Usage: make load-test SPEC=path/to/load-spec.md"; \
		exit 1; \
	fi
	@source venv/bin/activate && python orchestrator/workflows/load_test_runner.py --spec "$(SPEC)"

# Docker compose command for dev (docker-compose v1 for backwards compat)
DOCKER_COMPOSE ?= docker-compose

# ==========================================
# DOCKER
# ==========================================

docker-up:
	@echo "Starting all services via Docker Compose..."
	@$(DOCKER_COMPOSE) up -d
	@echo ""
	@echo "Services starting..."
	@echo "  Dashboard: http://localhost:3000"
	@echo "  API:       http://localhost:8001"
	@echo "  API Docs:  http://localhost:8001/docs"
	@echo ""
	@echo "View logs: $(DOCKER_COMPOSE) logs -f"

docker-down:
	@echo "Stopping all Docker services..."
	@$(DOCKER_COMPOSE) down
	@echo "Services stopped."

docker-build:
	@echo "Rebuilding Docker images..."
	@$(DOCKER_COMPOSE) build --no-cache
	@echo "Images rebuilt. Run 'make docker-up' to start."

# Dev K6 workers (uses docker-compose.yml with volume-mounted code)
dev-k6-workers-up:
	@echo "Starting dev K6 workers (code auto-mounted)..."
	@$(DOCKER_COMPOSE) --profile k6-workers up -d --build k6-workers
	@echo ""
	@echo "Dev K6 workers started. Code changes apply on container restart."
	@echo "Logs: make dev-k6-workers-logs"

dev-k6-workers-down:
	@echo "Stopping dev K6 workers..."
	@$(DOCKER_COMPOSE) --profile k6-workers stop k6-workers
	@echo "Dev K6 workers stopped."

dev-k6-workers-logs:
	@$(DOCKER_COMPOSE) --profile k6-workers logs -f k6-workers

# ==========================================
# DOCKER (PRODUCTION)
# ==========================================

# Common production docker-compose command
PROD_COMPOSE = docker compose --env-file .env.prod -f docker-compose.prod.yml

prod-up:
	@echo "Starting production services (standard mode with VNC + nginx)..."
	@$(PROD_COMPOSE) --profile standard --profile nginx up -d
	@echo ""
	@echo "Production services started:"
	@echo "  Dashboard:     http://localhost:3000 (direct) / http://localhost:80 (via nginx)"
	@echo "  API:           http://localhost:8001"
	@echo "  API Docs:      http://localhost:8001/docs"
	@echo "  VNC View:      http://localhost:6080"
	@echo "  MinIO Console: http://localhost:9001"
	@echo ""
	@echo "View logs: make prod-logs"

prod-dev:
	@if [ ! -f ".env.prod" ]; then \
		echo "No .env.prod file found. Creating from .env.prod.example..."; \
		cp .env.prod.example .env.prod; \
		echo "Created .env.prod — edit it with your API credentials."; \
		echo "Default admin: admin@test.com / Admin123!@#"; \
		echo ""; \
	fi
	@echo "Starting production services with LOCAL CODE MOUNTING (no rebuild needed)..."
	@echo ""
	@echo "This mounts your local ./orchestrator and ./web/src directories."
	@echo "Code changes will be reflected automatically (uvicorn --reload)."
	@echo ""
	@$(PROD_COMPOSE) -f docker-compose.dev-override.yml --profile standard up -d
	@echo ""
	@echo "Development mode started:"
	@echo "  Dashboard:     http://localhost:3000"
	@echo "  API:           http://localhost:8001 (auto-reload enabled)"
	@echo "  API Docs:      http://localhost:8001/docs"
	@echo "  VNC View:      http://localhost:6080"
	@echo "  MinIO Console: http://localhost:9001"
	@echo ""
	@echo "Code changes in ./orchestrator will auto-reload the backend."
	@echo "View logs: make prod-logs"

prod-down:
	@echo "Stopping production services gracefully..."
	@$(PROD_COMPOSE) --profile standard --profile nginx --profile workers --profile k6-workers down --remove-orphans --timeout 30
	@echo "Production services stopped."

prod-down-safe:
	@echo "=== Safe Production Shutdown ==="
	@echo "Step 1: Running backup before shutdown..."
	@$(PROD_COMPOSE) --profile backup-full run --rm backup-full 2>/dev/null || echo "Backup skipped (service not available)"
	@echo "Step 2: Stopping services gracefully (30s timeout)..."
	@$(PROD_COMPOSE) --profile standard --profile nginx --profile workers --profile k6-workers down --remove-orphans --timeout 30
	@echo "Step 3: Verifying shutdown..."
	@docker ps --filter "name=quorvex" --format "{{.Names}}" | grep -q . && echo "WARNING: Some containers still running!" || echo "All containers stopped."
	@echo "=== Safe shutdown complete ==="

prod-restart:
	@echo "Restarting backend (picking up code changes)..."
	@$(PROD_COMPOSE) --profile standard restart backend || $(PROD_COMPOSE) --profile workers restart backend-slim
	@echo "Backend restarted."

prod-logs:
	@$(PROD_COMPOSE) logs -f backend frontend

prod-build:
	@if [ ! -f ".env.prod" ]; then \
		echo "No .env.prod file found. Creating from .env.prod.example..."; \
		cp .env.prod.example .env.prod; \
		echo "Created .env.prod — edit it with your API credentials."; \
		echo ""; \
	fi
	@echo "Rebuilding production images (with cache)..."
	@$(PROD_COMPOSE) --profile standard --profile nginx --profile k6-workers build
	@echo "Images rebuilt. Run 'make prod-up' to start."

prod-build-no-cache:
	@echo "Rebuilding production images (no cache - fresh build)..."
	@$(PROD_COMPOSE) --profile standard --profile nginx --profile k6-workers build --no-cache
	@echo "Images rebuilt. Run 'make prod-up' to start."

prod-status:
	@echo "Production service status:"
	@echo ""
	@$(PROD_COMPOSE) ps
	@echo ""
	@echo "Health checks:"
	@curl -s http://localhost:8001/health 2>/dev/null | python3 -m json.tool 2>/dev/null || echo "  Backend: Not responding"
	@echo ""

# ==========================================
# BACKUP & RECOVERY
# ==========================================

backup:
	@echo "Running database-only backup..."
	@$(PROD_COMPOSE) --profile backup run --rm backup
	@echo ""
	@echo "Backup complete. View backups: make backup-status"

backup-full:
	@echo "Running full backup (DB + specs + tests + PRDs + ChromaDB)..."
	@$(PROD_COMPOSE) --profile backup-full run --rm backup-full
	@echo ""
	@echo "Full backup complete. View backups: make backup-status"

backup-status:
	@echo "=== Backup Status ==="
	@echo ""
	@$(PROD_COMPOSE) --profile backup-full run --rm backup-full sh -c "\
		apk add --no-cache -q bash coreutils curl jq gzip >/dev/null 2>&1 && \
		bash /scripts/full_backup.sh --status" 2>/dev/null || \
		echo "Run 'make prod-up' first to start services."

restore-list:
	@echo "=== Available Backups ==="
	@echo ""
	@$(PROD_COMPOSE) --profile restore run --rm restore sh -c "\
		apk add --no-cache -q postgresql15-client bash coreutils jq gzip tar curl >/dev/null 2>&1 && \
		bash /scripts/restore.sh --list" 2>/dev/null || \
		echo "Run 'make prod-up' first to start services."

restore:
	@if [ -z "$(TS)" ]; then \
		echo "Error: TS (timestamp) argument is required."; \
		echo "Usage: make restore TS=20240115_143022"; \
		echo ""; \
		echo "List available backups: make restore-list"; \
		exit 1; \
	fi
	@echo "Restoring from backup: $(TS)"
	@echo ""
	@echo "WARNING: This will overwrite all existing data!"
	@echo "Make sure you have backed up .env.prod (contains JWT_SECRET_KEY)"
	@echo ""
	@read -p "Continue? (yes/no): " confirm && [ "$$confirm" = "yes" ] || exit 1
	@$(PROD_COMPOSE) --profile restore run --rm restore sh -c "\
		apk add --no-cache -q postgresql15-client bash coreutils jq gzip tar curl >/dev/null 2>&1 && \
		bash /scripts/restore.sh $(TS)"

restore-from-minio:
	@if [ -z "$(TS)" ]; then \
		echo "Error: TS (timestamp) argument is required."; \
		echo "Usage: make restore-from-minio TS=20240115_143022"; \
		exit 1; \
	fi
	@echo "Downloading and restoring from MinIO: $(TS)"
	@$(PROD_COMPOSE) --profile restore run --rm restore sh -c "\
		apk add --no-cache -q postgresql15-client bash coreutils jq gzip tar curl >/dev/null 2>&1 && \
		bash /scripts/restore.sh --from-minio $(TS)"

# ==========================================
# STORAGE MANAGEMENT
# ==========================================

storage-health:
	@echo "=== Storage Health Check ==="
	@echo ""
	@curl -s http://localhost:8001/health/storage 2>/dev/null | python3 -m json.tool 2>/dev/null || \
		echo "Backend not responding. Run 'make prod-up' first."

archival:
	@echo "Running artifact archival..."
	@echo "  Hot retention: 30 days (local)"
	@echo "  Total retention: 90 days (MinIO)"
	@echo ""
	@$(PROD_COMPOSE) --profile archival run --rm archival

archival-dry-run:
	@echo "Archival dry run (preview only)..."
	@echo ""
	@$(PROD_COMPOSE) --profile archival run --rm archival python -m orchestrator.services.archival --dry-run --verbose

minio-console:
	@echo "Opening MinIO Console..."
	@echo "  URL: http://localhost:9001"
	@echo "  Credentials: Check MINIO_ROOT_USER and MINIO_ROOT_PASSWORD in .env.prod"
	@echo ""
	@open http://localhost:9001 2>/dev/null || xdg-open http://localhost:9001 2>/dev/null || \
		echo "Open http://localhost:9001 in your browser"

# ==========================================
# UTILITIES
# ==========================================

check-env:
	@echo "Checking environment configuration..."
	@echo ""
	@if [ -f ".env" ]; then \
		echo "  + .env file exists"; \
		. .env 2>/dev/null; \
		if [ -n "$$ANTHROPIC_AUTH_TOKEN" ] && [ "$$ANTHROPIC_AUTH_TOKEN" != "your-token-here" ]; then \
			echo "  + ANTHROPIC_AUTH_TOKEN is configured"; \
		else \
			echo "  ! ANTHROPIC_AUTH_TOKEN not configured"; \
		fi; \
		if [ -n "$$ANTHROPIC_BASE_URL" ]; then \
			echo "  + ANTHROPIC_BASE_URL: $$ANTHROPIC_BASE_URL"; \
		else \
			echo "  ! ANTHROPIC_BASE_URL not set"; \
		fi; \
		if [ -n "$$ANTHROPIC_DEFAULT_SONNET_MODEL" ]; then \
			echo "  + Model: $$ANTHROPIC_DEFAULT_SONNET_MODEL"; \
		else \
			echo "  ! ANTHROPIC_DEFAULT_SONNET_MODEL not set"; \
		fi; \
		if [ -n "$$OPENAI_API_KEY" ]; then \
			echo "  + OPENAI_API_KEY is configured (memory system enabled)"; \
		else \
			echo "  - OPENAI_API_KEY not set (memory system limited)"; \
		fi; \
	else \
		echo "  x .env file not found - run 'make setup' first"; \
	fi
	@echo ""
	@if [ -f ".env.prod" ]; then \
		echo "  + .env.prod file exists (production config)"; \
		. .env.prod 2>/dev/null; \
		if [ -n "$$POSTGRES_PASSWORD" ]; then \
			echo "  + POSTGRES_PASSWORD is configured"; \
		else \
			echo "  ! POSTGRES_PASSWORD not configured"; \
		fi; \
		if [ -n "$$MINIO_ROOT_PASSWORD" ]; then \
			echo "  + MINIO_ROOT_PASSWORD is configured"; \
		else \
			echo "  ! MINIO_ROOT_PASSWORD not configured"; \
		fi; \
		if [ -n "$$JWT_SECRET_KEY" ] && [ "$$JWT_SECRET_KEY" != "dev-secret-key-change-in-production" ]; then \
			echo "  + JWT_SECRET_KEY is configured (secure)"; \
		else \
			echo "  ! JWT_SECRET_KEY using default (CHANGE FOR PRODUCTION!)"; \
		fi; \
	else \
		echo "  - .env.prod file not found (needed for production)"; \
	fi
	@echo ""
	@if [ -d "venv" ]; then \
		echo "  + Python virtual environment exists"; \
	else \
		echo "  x Python virtual environment not found"; \
	fi
	@if [ -d "web/node_modules" ]; then \
		echo "  + Frontend dependencies installed"; \
	else \
		echo "  x Frontend dependencies not installed"; \
	fi
	@echo ""
	@echo "K6 load testing:"
	@if command -v k6 >/dev/null 2>&1; then \
		echo "  + k6 installed: $$(k6 version 2>/dev/null | head -1)"; \
	else \
		echo "  - k6 not installed (needed for load testing)"; \
		echo "    Install: brew install k6  (macOS) or see https://k6.io/docs/get-started/installation/"; \
	fi
	@echo ""
	@echo "Security testing:"
	@if command -v nuclei >/dev/null 2>&1; then \
		echo "  + nuclei installed: $$(nuclei -version 2>&1 | head -1)"; \
	else \
		echo "  - nuclei not installed (optional, for template-based scanning)"; \
		echo "    Install: go install github.com/projectdiscovery/nuclei/v3/cmd/nuclei@latest"; \
	fi
	@echo "  Quick scan: Always available (uses httpx, no external deps)"
	@echo "  ZAP DAST:   make zap-up (Docker required)"
	@echo ""
	@echo "Parallelism settings:"
	@if [ -f ".env" ]; then \
		. .env 2>/dev/null; \
		echo "  PLAYWRIGHT_WORKERS: $${PLAYWRIGHT_WORKERS:-4} (default: 4)"; \
		echo "  DEFAULT_PARALLELISM: $${DEFAULT_PARALLELISM:-4} (default: 4)"; \
		echo "  BROWSER_WORKERS_ENABLED: $${BROWSER_WORKERS_ENABLED:-false}"; \
	fi

logs:
	@if [ -f "api.log" ] || [ -f "web.log" ]; then \
		tail -f api.log web.log 2>/dev/null || echo "No logs found. Start services with 'make dev' first."; \
	else \
		echo "No logs found. Start services with 'make dev' first."; \
	fi

stop:
	@echo "Stopping services gracefully..."
	@# First try graceful shutdown (SIGTERM) - allows cleanup
	@-lsof -ti :8001 | xargs kill -15 2>/dev/null || true
	@-lsof -ti :3000 | xargs kill -15 2>/dev/null || true
	@echo "  Waiting for graceful shutdown..."
	@sleep 3
	@# Force kill only if still running (SIGKILL)
	@-lsof -ti :8001 | xargs kill -9 2>/dev/null || true
	@-lsof -ti :3000 | xargs kill -9 2>/dev/null || true
	@# Stop any Docker containers gracefully
	@-$(DOCKER_COMPOSE) down 2>/dev/null || true
	@echo "Services stopped."

clean:
	@rm -rf runs/*
	@rm -f api.log web.log
	@echo "Cleaned up run artifacts and logs."

# ==========================================
# BROWSER WORKERS (Phase 2 - Docker Isolation)
# ==========================================

# Default number of workers
WORKERS ?= 4

workers-build:
	@echo "Building browser worker images..."
	@$(PROD_COMPOSE) --profile workers build browser-workers agent-worker backend-slim
	@echo ""
	@echo "Images built:"
	@docker images | grep -E "quorvex-(worker|backend-slim)" || echo "  (images not tagged yet)"

workers-up:
	@echo "Starting production services with isolated browser workers..."
	@echo "  Workers: $(WORKERS)"
	@echo ""
	@$(PROD_COMPOSE) --profile workers up -d --scale browser-workers=$(WORKERS)
	@echo ""
	@echo "Services started with browser worker isolation:"
	@echo "  Dashboard:     http://localhost:3000"
	@echo "  API:           http://localhost:8001"
	@echo "  MinIO Console: http://localhost:9001"
	@echo ""
	@echo "Browser workers: $(WORKERS) containers"
	@echo "Agent workers:   2 containers (default)"
	@echo ""
	@echo "View logs:   make workers-logs"
	@echo "Scale:       make workers-scale N=8"
	@echo "Status:      make workers-status"

workers-down:
	@echo "Stopping browser worker services..."
	@$(PROD_COMPOSE) --profile workers down --timeout 30
	@echo "Browser worker services stopped."

workers-scale:
	@if [ -z "$(N)" ]; then \
		echo "Error: N (number of workers) argument is required."; \
		echo "Usage: make workers-scale N=8"; \
		exit 1; \
	fi
	@echo "Scaling browser workers to $(N)..."
	@$(PROD_COMPOSE) --profile workers up -d --scale browser-workers=$(N) --no-recreate
	@echo ""
	@echo "Browser workers scaled to $(N)"
	@echo ""
	@make workers-status

workers-status:
	@echo "=== Browser Worker Status ==="
	@echo ""
	@$(PROD_COMPOSE) --profile workers ps
	@echo ""
	@echo "Browser Worker containers:"
	@docker ps --filter "name=browser-worker" --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}" 2>/dev/null || echo "  No browser workers running"
	@echo ""
	@echo "Agent Worker containers:"
	@docker ps --filter "name=agent-worker" --format "table {{.Names}}\t{{.Status}}" 2>/dev/null || echo "  No agent workers running"
	@echo ""
	@echo "Resource usage:"
	@docker stats --no-stream --format "table {{.Name}}\t{{.CPUPerc}}\t{{.MemUsage}}" $$(docker ps -q --filter "name=worker") 2>/dev/null || echo "  No workers running"

workers-logs:
	@echo "Tailing worker logs (Ctrl+C to stop)..."
	@$(PROD_COMPOSE) --profile workers logs -f browser-workers agent-worker backend-slim

# ==========================================
# K6 LOAD TEST WORKERS (Distributed Execution)
# ==========================================

# Default K6 workers
K6_WORKERS ?= 1

k6-workers-up:
	@echo "Starting K6 load test workers..."
	@echo "  Workers: $(K6_WORKERS)"
	@echo ""
	@$(PROD_COMPOSE) --profile k6-workers up -d --scale k6-workers=$(K6_WORKERS)
	@echo ""
	@echo "K6 workers started. Load tests will be distributed automatically."
	@echo ""
	@echo "Scale:   make k6-workers-scale N=3"
	@echo "Status:  make k6-workers-status"
	@echo "Logs:    make k6-workers-logs"

k6-workers-down:
	@echo "Stopping K6 workers..."
	@$(PROD_COMPOSE) --profile k6-workers stop k6-workers
	@echo "K6 workers stopped. Load tests will run locally in backend."

k6-workers-scale:
	@if [ -z "$(N)" ]; then \
		echo "Error: N (number of workers) argument is required."; \
		echo "Usage: make k6-workers-scale N=3"; \
		exit 1; \
	fi
	@echo "Scaling K6 workers to $(N)..."
	@$(PROD_COMPOSE) --profile k6-workers up -d --scale k6-workers=$(N) --no-recreate
	@echo ""
	@make k6-workers-status

k6-workers-status:
	@echo "=== K6 Worker Status ==="
	@echo ""
	@$(PROD_COMPOSE) --profile k6-workers ps k6-workers 2>/dev/null || echo "  No K6 workers running"
	@echo ""
	@echo "Resource usage:"
	@docker stats --no-stream --format "table {{.Name}}\t{{.CPUPerc}}\t{{.MemUsage}}" $$(docker ps -q --filter "name=k6-worker" 2>/dev/null) 2>/dev/null || echo "  No K6 workers running"

k6-workers-logs:
	@echo "Tailing K6 worker logs (Ctrl+C to stop)..."
	@$(PROD_COMPOSE) --profile k6-workers logs -f k6-workers

# ==========================================
# SECURITY TESTING (ZAP DAST Scanner)
# ==========================================

zap-up:
	@echo "Starting OWASP ZAP security scanner daemon..."
	@$(PROD_COMPOSE) --profile security up -d zap
	@echo ""
	@echo "ZAP scanner started."
	@echo "  API:    http://localhost:$${ZAP_PORT:-8090}"
	@echo "  Status: make zap-status"
	@echo "  Logs:   make zap-logs"
	@echo ""
	@echo "Quick scan works WITHOUT ZAP (uses httpx)."
	@echo "Nuclei and ZAP DAST scans require this service."

zap-down:
	@echo "Stopping ZAP scanner..."
	@$(PROD_COMPOSE) --profile security stop zap
	@echo "ZAP scanner stopped. Quick scans still work."

zap-status:
	@echo "=== ZAP Scanner Status ==="
	@echo ""
	@$(PROD_COMPOSE) --profile security ps zap 2>/dev/null || echo "  ZAP not running"
	@echo ""
	@echo "ZAP API health:"
	@curl -sf http://localhost:$${ZAP_PORT:-8090}/JSON/core/view/version/ 2>/dev/null | python3 -m json.tool 2>/dev/null || echo "  ZAP API not reachable (run: make zap-up)"

zap-logs:
	@echo "Tailing ZAP logs (Ctrl+C to stop)..."
	@$(PROD_COMPOSE) --profile security logs -f zap

# ==========================================
# DOCKER SWARM (Enterprise - Simpler Alternative)
# ==========================================

swarm-up:
	@echo "Deploying to Docker Swarm..."
	@if ! docker info 2>/dev/null | grep -q "Swarm: active"; then \
		echo "Initializing Docker Swarm..."; \
		docker swarm init 2>/dev/null || echo "Swarm already initialized or failed"; \
	fi
	@echo ""
	@docker stack deploy -c docker-compose.swarm.yml quorvex
	@echo ""
	@echo "Swarm deployment started."
	@echo ""
	@echo "View status:  make swarm-status"
	@echo "Scale:        make swarm-scale N=8"
	@echo "View logs:    docker service logs quorvex_backend -f"

swarm-down:
	@echo "Removing Swarm stack..."
	@docker stack rm quorvex
	@echo ""
	@echo "Swarm stack removed."
	@echo "Note: Swarm mode is still active. Run 'docker swarm leave --force' to disable."

swarm-scale:
	@if [ -z "$(N)" ]; then \
		echo "Error: N (number of workers) argument is required."; \
		echo "Usage: make swarm-scale N=8"; \
		exit 1; \
	fi
	@echo "Scaling Swarm browser workers to $(N)..."
	@docker service scale quorvex_browser-workers=$(N)
	@echo ""
	@make swarm-status

swarm-status:
	@echo "=== Docker Swarm Status ==="
	@echo ""
	@docker stack services quorvex 2>/dev/null || echo "Stack not deployed. Run 'make swarm-up' first."
	@echo ""
	@echo "Browser worker tasks:"
	@docker service ps quorvex_browser-workers --format "table {{.Name}}\t{{.CurrentState}}\t{{.Node}}" 2>/dev/null || echo "  No workers running"

# ==========================================
# KUBERNETES (Enterprise - Auto-scaling)
# ==========================================

# Kubernetes namespace
K8S_NAMESPACE ?= quorvex

k8s-deploy:
	@echo "Deploying to Kubernetes..."
	@echo ""
	@echo "Checking prerequisites..."
	@kubectl version --client > /dev/null 2>&1 || (echo "Error: kubectl not found" && exit 1)
	@echo "  + kubectl found"
	@echo ""
	@if [ ! -f "k8s/secrets.local.yaml" ]; then \
		echo "WARNING: k8s/secrets.local.yaml not found!"; \
		echo "Copy k8s/secrets.yaml to k8s/secrets.local.yaml and fill in values."; \
		echo ""; \
		read -p "Continue with template secrets? (yes/no): " confirm && [ "$$confirm" = "yes" ] || exit 1; \
	fi
	@echo "Applying Kubernetes manifests..."
	@kubectl apply -k k8s/
	@echo ""
	@echo "Deployment started. View status: make k8s-status"

k8s-delete:
	@echo "Deleting Kubernetes deployment..."
	@read -p "This will delete all resources in namespace '$(K8S_NAMESPACE)'. Continue? (yes/no): " confirm && [ "$$confirm" = "yes" ] || exit 1
	@kubectl delete -k k8s/ || kubectl delete namespace $(K8S_NAMESPACE)
	@echo ""
	@echo "Kubernetes deployment deleted."

k8s-status:
	@echo "=== Kubernetes Status ==="
	@echo ""
	@echo "Pods:"
	@kubectl get pods -n $(K8S_NAMESPACE) 2>/dev/null || echo "  Namespace not found. Run 'make k8s-deploy' first."
	@echo ""
	@echo "Services:"
	@kubectl get svc -n $(K8S_NAMESPACE) 2>/dev/null || true
	@echo ""
	@echo "HPA (Auto-scaling):"
	@kubectl get hpa -n $(K8S_NAMESPACE) 2>/dev/null || true
	@echo ""
	@echo "Ingress:"
	@kubectl get ingress -n $(K8S_NAMESPACE) 2>/dev/null || true

k8s-scale:
	@if [ -z "$(N)" ]; then \
		echo "Error: N (number of workers) argument is required."; \
		echo "Usage: make k8s-scale N=8"; \
		exit 1; \
	fi
	@echo "Scaling Kubernetes browser workers to $(N)..."
	@kubectl scale deployment browser-workers -n $(K8S_NAMESPACE) --replicas=$(N)
	@echo ""
	@echo "Note: HPA may override this if CPU/memory thresholds are breached."
	@echo ""
	@kubectl get pods -n $(K8S_NAMESPACE) -l app=browser-worker

k8s-logs:
	@echo "Tailing Kubernetes logs (Ctrl+C to stop)..."
	@echo ""
	@echo "Select service to tail:"
	@echo "  1) Backend"
	@echo "  2) Browser Workers"
	@echo "  3) Frontend"
	@echo ""
	@read -p "Choice [1]: " choice; \
	case "$$choice" in \
		2) kubectl logs -n $(K8S_NAMESPACE) -l app=browser-worker -f --max-log-requests=10 ;; \
		3) kubectl logs -n $(K8S_NAMESPACE) -l app=frontend -f ;; \
		*) kubectl logs -n $(K8S_NAMESPACE) -l app=backend -f ;; \
	esac

# ==========================================
# DATABASE MIGRATIONS (Alembic - PostgreSQL only)
# ==========================================

db-migrate:
	@if [ -z "$(M)" ]; then \
		echo "Error: M (message) argument is required."; \
		echo "Usage: make db-migrate M='add user preferences table'"; \
		exit 1; \
	fi
	@echo "Generating new Alembic migration..."
	@$(PROD_COMPOSE) exec backend alembic revision --autogenerate -m "$(M)" 2>/dev/null || \
		(source venv/bin/activate 2>/dev/null && alembic revision --autogenerate -m "$(M)")
	@echo ""
	@echo "Migration generated. Review it in orchestrator/migrations/versions/"
	@echo "Then run: make db-upgrade"

db-upgrade:
	@echo "Running pending Alembic migrations..."
	@$(PROD_COMPOSE) exec backend alembic upgrade head 2>/dev/null || \
		(source venv/bin/activate 2>/dev/null && alembic upgrade head)
	@echo "Migrations complete."

db-downgrade:
	@echo "Rolling back one Alembic migration..."
	@$(PROD_COMPOSE) exec backend alembic downgrade -1 2>/dev/null || \
		(source venv/bin/activate 2>/dev/null && alembic downgrade -1)
	@echo "Rollback complete. Run 'make db-history' to verify."

db-history:
	@echo "=== Alembic Migration History ==="
	@$(PROD_COMPOSE) exec backend alembic history --verbose 2>/dev/null || \
		(source venv/bin/activate 2>/dev/null && alembic history --verbose)

db-stamp:
	@if [ -z "$(R)" ]; then \
		echo "Error: R (revision) argument is required."; \
		echo "Usage: make db-stamp R=001"; \
		echo ""; \
		echo "Use this for existing databases to mark current schema version"; \
		echo "without running the migration."; \
		exit 1; \
	fi
	@echo "Stamping database at revision $(R)..."
	@$(PROD_COMPOSE) exec backend alembic stamp $(R) 2>/dev/null || \
		(source venv/bin/activate 2>/dev/null && alembic stamp $(R))
	@echo "Database stamped at revision $(R)."

# ============================================================
# Development Tools
# ============================================================

lint:
	@echo "Running Python linting..."
	cd orchestrator && ruff check .
	@echo ""
	@echo "Running frontend linting..."
	cd web && npm run lint
	@echo ""
	@echo "All linting passed!"

format:
	@echo "Formatting Python code..."
	cd orchestrator && ruff format .
	@echo ""
	@echo "Formatting complete!"

test:
	@echo "Running Python tests..."
	cd orchestrator && python -m pytest tests/ -v
	@echo ""
	@echo "All tests passed!"

# ==========================================
# DOCUMENTATION
# ==========================================

docs-serve:
	pip install -r requirements-docs.txt && mkdocs serve

docs-build:
	pip install -r requirements-docs.txt && mkdocs build --strict

docs-deploy:
	pip install -r requirements-docs.txt && mkdocs gh-deploy --force

# ==========================================
# MAINTENANCE & OPERATIONS
# ==========================================

docker-prune:
	@echo "=== Docker Cleanup ==="
	@echo ""
	@echo "Removing dangling images..."
	@docker image prune -f
	@echo ""
	@echo "Removing stopped containers..."
	@docker container prune -f
	@echo ""
	@echo "Removing build cache..."
	@docker builder prune -f
	@echo ""
	@echo "Cleanup complete."
	@echo ""
	@echo "Disk usage after cleanup:"
	@docker system df

volume-sizes:
	@echo "=== Docker Volume Sizes ==="
	@echo ""
	@docker system df -v 2>/dev/null | grep -A 100 "VOLUME NAME" || \
		echo "No volumes found."

db-vacuum:
	@echo "Running VACUUM ANALYZE on PostgreSQL..."
	@$(PROD_COMPOSE) exec db psql -U $${POSTGRES_USER:-playwright} -d $${POSTGRES_DB:-playwright_agent} \
		-c "VACUUM (VERBOSE, ANALYZE);" 2>/dev/null || \
		echo "Database not running. Start with 'make prod-up' first."

health-check:
	@echo "=== Health Check ==="
	@echo ""
	@echo "Backend API:"
	@curl -sf http://localhost:8001/health 2>/dev/null | python3 -m json.tool 2>/dev/null && echo "" || echo "  UNREACHABLE"
	@echo ""
	@echo "Frontend:"
	@curl -sf -o /dev/null -w "  Status: %{http_code}\n" http://localhost:3000 2>/dev/null || echo "  UNREACHABLE"
	@echo ""
	@echo "Storage health:"
	@curl -sf http://localhost:8001/health/storage 2>/dev/null | python3 -m json.tool 2>/dev/null || echo "  UNREACHABLE"
	@echo ""
	@echo "Backup health:"
	@curl -sf http://localhost:8001/health/backup 2>/dev/null | python3 -m json.tool 2>/dev/null || echo "  UNREACHABLE"
	@echo ""
	@echo "Alerts:"
	@curl -sf http://localhost:8001/health/alerts 2>/dev/null | python3 -m json.tool 2>/dev/null || echo "  UNREACHABLE"

deps-lock:
	@echo "Capturing current venv versions to requirements.freeze..."
	@echo "NOTE: This outputs to requirements.freeze (NOT requirements.lock)."
	@echo "      requirements.lock is a curated list - edit it manually."
	@echo ""
	@source venv/bin/activate && pip freeze | grep -v "^-e " | grep -v "git+" > requirements.freeze
	@echo "requirements.freeze written ($$(wc -l < requirements.freeze) lines)."
	@echo ""
	@echo "To update requirements.lock, compare versions:"
	@echo "  diff <(sort requirements.lock | grep '==') <(sort requirements.freeze)"

upgrade:
	@echo "=== Production Upgrade Procedure ==="
	@echo ""
	@echo "Step 1/6: Pre-flight checks..."
	@curl -sf http://localhost:8001/health >/dev/null 2>&1 || { echo "WARNING: Backend not running. Starting fresh deployment."; }
	@echo ""
	@echo "Step 2/6: Full backup before upgrade..."
	@$(PROD_COMPOSE) --profile backup-full run --rm backup-full 2>/dev/null || echo "  Backup skipped (services not running)"
	@echo ""
	@echo "Step 3/6: Pulling latest code..."
	@git pull
	@echo ""
	@echo "Step 4/6: Rebuilding images..."
	@$(PROD_COMPOSE) --profile standard --profile nginx build
	@echo ""
	@echo "Step 5/6: Running database migrations..."
	@$(PROD_COMPOSE) --profile standard --profile nginx run --rm backend sh -c "cd /app && python -c 'from orchestrator.api.db import init_db; init_db()'" 2>/dev/null || echo "  Migration will run on startup"
	@echo ""
	@echo "Step 6/6: Restarting services..."
	@$(PROD_COMPOSE) --profile standard --profile nginx up -d
	@echo ""
	@echo "Waiting for services to become healthy..."
	@sleep 10
	@make health-check
	@echo ""
	@echo "=== Upgrade complete ==="
	@echo ""
	@echo "If something went wrong:"
	@echo "  1. make db-downgrade     (roll back migration)"
	@echo "  2. git checkout <tag>    (revert code)"
	@echo "  3. make prod-build       (rebuild old images)"
	@echo "  4. make prod-up          (restart with old code)"

