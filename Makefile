.PHONY: setup setup-skills start restart restart-agent-worker dev dev-fast dev-fast-build run run-skill clean help docker-up docker-down docker-build check-env logs stop \
        autopilot-stable-up autopilot-stable-down autopilot-dev-up autopilot-status autopilot-logs \
        prod prod-up prod-down prod-down-safe prod-restart prod-logs prod-build prod-build-no-cache prod-status prod-dev prod-dev-build prod-env-bootstrap \
        backup backup-full backup-status restore-list restore restore-from-minio \
        archival archival-dry-run storage-health minio-console \
        workers-up workers-down workers-scale workers-status workers-logs workers-build \
        swarm-up swarm-down swarm-scale swarm-status \
        k8s-deploy k8s-delete k8s-status k8s-scale k8s-logs \
        db-migrate db-upgrade db-downgrade db-history alembic-upgrade alembic-history db-stamp db-demo-seed youtube-demo-seed \
        docker-prune volume-sizes db-vacuum health-check deploy-check company-rehearsal release-preflight server-upgrade release-to-server upgrade deps-lock \
        load-test agent-runtime-ready agent-temporal-smoke-up agent-temporal-smoke agent-temporal-smoke-logs \
        k6-workers-up k6-workers-down k6-workers-scale k6-workers-logs k6-workers-status dev-k6-workers-up dev-k6-workers-down dev-k6-workers-logs \
        zap-up zap-down zap-status zap-logs \
        lint format test autonomous-soak \
        docs-check docs-visual-check docs-visual-capture docs-serve docs-build docs-deploy \
        youtube-pack youtube-voice youtube-avatar youtube-assemble youtube-final \
        youtube-mcp-check youtube-upload-dry-run youtube-upload-confirm obs-recording-dry-run obs-recording-confirm

# Default target
help:
	@echo "Quorvex AI Commands:"
	@echo ""
	@echo "  Setup & Run:"
	@echo "    make setup          - Install dependencies and setup environment"
	@echo "    make setup-skills   - Install Playwright skill dependencies"
	@echo "    make dev            - Start full Docker dev stack with local code mounts"
	@echo "    make dev-fast       - Start Docker dev stack without rebuilding images"
	@echo "    make dev-fast-build - Build only images needed by make dev-fast"
	@echo "    make start          - Start company/server runtime for external-nginx deployment"
	@echo "    make stop           - Stop local dev and server-runtime Compose stacks"
	@echo "    make restart        - Restart the company/server runtime"
	@echo "    make restart-agent-worker - Restart backend uvicorn and queued agent workers only"
	@echo "    make logs           - Tail backend and frontend logs"
	@echo "    make deploy-check   - Verify local external-nginx runtime readiness"
	@echo "    make company-rehearsal - Simulate company nginx and run browser proxy smoke"
	@echo "    make run SPEC=...   - Run a specific test spec"
	@echo "    make run-skill S=.. - Run a Playwright skill script"
	@echo ""
	@echo "  Docker (legacy/local-only):"
	@echo "    make docker-up      - Unsupported legacy docker-compose.yml path"
	@echo "    make docker-down    - Stop all Docker services"
	@echo "    make docker-build   - Rebuild Docker images"
	@echo ""
	@echo "  Docker (advanced/compatibility):"
	@echo "    make prod           - Legacy repo-managed nginx path (guarded)"
	@echo "    make prod-up        - Legacy repo-managed nginx path (guarded)"
	@echo "    make prod-dev       - Compatibility alias for make dev"
	@echo "    make prod-down      - Stop production services"
	@echo "    make prod-down-safe - Stop with backup first (recommended)"
	@echo "    make prod-restart   - Restart app services (picks up mounted code changes)"
	@echo "    make prod-logs      - Tail production logs"
	@echo "    make prod-build     - Rebuild production images (with cache)"
	@echo "    make prod-build-no-cache - Rebuild without cache (force fresh)"
	@echo "    make prod-status    - Show status of all services"
	@echo ""
	@echo "  Auto Pilot local runtime (experimental):"
	@echo "    make autopilot-stable-up   - Unsupported pending Compose rebuild"
	@echo "    make autopilot-stable-down - Stop stable local Auto Pilot stack"
	@echo "    make autopilot-dev-up      - Start Auto Pilot dev stack with hot reload"
	@echo "    make autopilot-status      - Show Auto Pilot stack status and memory"
	@echo "    make autopilot-logs        - Tail Auto Pilot backend/frontend logs"
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
	@echo "  Docker Swarm (unsupported):"
	@echo "    make swarm-up       - Unsupported experimental path"
	@echo "    make swarm-down     - Stop Swarm stack"
	@echo "    make swarm-scale N=8 - Scale Swarm workers"
	@echo "    make swarm-status   - Check Swarm status"
	@echo ""
	@echo "  Kubernetes (unsupported):"
	@echo "    make k8s-deploy     - Unsupported experimental path"
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
	@echo "    make alembic-upgrade  - Alias for db-upgrade"
	@echo "    make alembic-history  - Alias for db-history"
	@echo "    make db-stamp R=...   - Stamp DB at revision (for existing DBs)"
	@echo "    make db-demo-seed     - Seed Database Testing demo content"
	@echo "    make youtube-demo-seed - Seed Quorvex Demo Shop YouTube walkthrough data"
	@echo ""
	@echo "  Maintenance:"
	@echo "    make release-preflight VERSION=v1.2.3 - Verify tagged images and deploy dry-run"
	@echo "    make server-upgrade VERSION=v1.2.3    - Run preflight, deploy, and post-check on server"
	@echo "    make release-to-server VERSION=v1.2.3 - Push release tag and run server upgrade over SSH"
	@echo "    make upgrade          - Unsupported legacy upgrade path; use release/server-upgrade"
	@echo "    make health-check     - Hit all health endpoints and report status"
	@echo "    make docker-prune     - Remove dangling images, stopped containers, build cache"
	@echo "    make volume-sizes     - Show sizes of all Docker volumes"
	@echo "    make db-vacuum        - Run VACUUM ANALYZE on PostgreSQL"
	@echo "    make deps-lock        - Regenerate requirements.lock from current venv"
	@echo ""
	@echo "  Load Testing:"
	@echo "    make load-test SPEC=... - Generate and run K6 load test from spec"
	@echo "    make autonomous-soak    - Run bounded autonomous product-UI soak"
	@echo "    make agent-runtime-ready - Verify API and Temporal agent workers are ready"
	@echo "    make agent-temporal-smoke-up - Start Docker services for agent Temporal smoke"
	@echo "    make agent-temporal-smoke    - Run deterministic Temporal-backed agent smoke"
	@echo ""
	@echo "  Documentation:"
	@echo "    make docs-check     - Run docs drift checks and strict MkDocs build"
	@echo "    make docs-visual-check - Verify local UI screenshots/GIFs are present"
	@echo "    make docs-visual-capture - Capture dashboard UI screenshots for docs"
	@echo "    make docs-serve     - Start MkDocs development server"
	@echo "    make docs-build     - Build MkDocs documentation in strict mode"
	@echo "    make docs-deploy    - Deploy docs to GitHub Pages"
	@echo ""
	@echo "  YouTube Production:"
	@echo "    make youtube-pack EP=001  - Generate episode script, captions, metadata, and checklist"
	@echo "    make youtube-voice EP=001 VOICE=DODLEQrClDo8wCz460ld - Generate ElevenLabs voiceover for an episode pack"
	@echo "    make youtube-avatar EP=001 - Generate HeyGen avatar payloads for presenter clips"
	@echo "    make youtube-assemble EP=001 RECORDING=path.mp4 - Export a 1080p YouTube MP4"
	@echo "    make youtube-final EP=001 RECORDING=path.mp4 - Seed, narrate with DODLEQrClDo8wCz460ld, and export final MP4"
	@echo "    make youtube-mcp-check EP=001 - Compile and check local YouTube/OBS MCP wrappers"
	@echo "    make youtube-upload-dry-run EP=001 - Write a YouTube upload dry-run manifest"
	@echo "    make youtube-upload-confirm EP=001 VIDEO=path.mp4 - Confirm a guarded YouTube upload"
	@echo "    make obs-recording-dry-run EP=001 - Write an OBS recording dry-run plan"
	@echo "    make obs-recording-confirm EP=001 - Confirm guarded OBS recording start"
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

# Docker compose command for dev. Override if needed, e.g. DOCKER_COMPOSE=docker-compose.
DOCKER_COMPOSE ?= docker compose
ALEMBIC_RUNNER ?= python -m orchestrator.scripts.alembic_runner
LOCAL_ALEMBIC = if [ -f venv/bin/activate ]; then source venv/bin/activate; fi; $(ALEMBIC_RUNNER)

# Common production docker-compose commands
PROD_COMPOSE = docker compose --env-file .env.prod -f docker-compose.prod.yml
APP_COMPOSE = $(PROD_COMPOSE) -f docker-compose.dev-override.yml
FAST_DEV_COMPOSE = $(APP_COMPOSE) -f docker-compose.dev-fast.yml
AUTOPILOT_STABLE_COMPOSE = $(PROD_COMPOSE) -f docker-compose.autopilot-stable.yml
BUILDX_CONFIG ?= /tmp/quorvex-buildx
RUNTIME_PROFILES = --profile standard
STOP_PROFILES = --profile standard --profile nginx --profile backup-scheduler --profile workers --profile k6-workers --profile security

start:
	@$(MAKE) prod-env-bootstrap
	@echo "Starting company/server runtime for external-nginx deployment..."
	@echo ""
	@echo "Company nginx should proxy the public subdomain to frontend :3000 and /websockify to backend :6080."
	@echo "This target does not start the repo-managed nginx or ZAP security scanner containers."
	@echo ""
	@COMPOSE_BAKE=false BUILDX_CONFIG=$(BUILDX_CONFIG) $(PROD_COMPOSE) $(RUNTIME_PROFILES) up -d --build db redis minio
	@python3 scripts/reconcile_prod_postgres.py
	@COMPOSE_BAKE=false BUILDX_CONFIG=$(BUILDX_CONFIG) $(PROD_COMPOSE) $(RUNTIME_PROFILES) up -d --build
	@$(MAKE) agent-runtime-ready
	@echo ""
	@echo "External-nginx runtime started:"
	@echo "  Dashboard:     http://localhost:3000 (proxy target)"
	@echo "  API:           http://localhost:8001 (private health/admin target)"
	@echo "  API Docs:      http://localhost:8001/docs"
	@echo "  VNC WebSocket: http://localhost:6080/websockify (proxy target)"
	@echo "  MinIO Console: http://localhost:9001"
	@echo ""
	@echo "Use the company URL for browser validation; direct localhost ports are server-local checks."
	@echo "View logs: make logs"

restart:
	@echo "Restarting company/server runtime..."
	@$(MAKE) stop
	@$(MAKE) start

restart-agent-worker:
	@echo "Restarting backend API and queued agent workers inside the existing backend container..."
	@$(APP_COMPOSE) $(RUNTIME_PROFILES) exec -T backend supervisorctl restart uvicorn agent_worker:* || \
		$(PROD_COMPOSE) $(RUNTIME_PROFILES) exec -T backend supervisorctl restart uvicorn agent_worker:*
	@echo "Backend API and agent workers restarted."

dev:
	@$(MAKE) prod-env-bootstrap
	@echo "Starting full Docker development stack with local code mounts..."
	@echo ""
	@echo "This target uses the production-shaped app stack plus docker-compose.dev-override.yml."
	@echo "Frontend hot reload is enabled. Backend source is mounted, but uvicorn reload is disabled in Docker."
	@echo "ZAP/security scanning is opt-in: run 'make zap-up' when needed."
	@echo ""
	@COMPOSE_BAKE=false BUILDX_CONFIG=$(BUILDX_CONFIG) $(APP_COMPOSE) $(RUNTIME_PROFILES) up -d --build db redis minio
	@python3 scripts/reconcile_prod_postgres.py
	@$(MAKE) prod-dev-build
	@COMPOSE_BAKE=false BUILDX_CONFIG=$(BUILDX_CONFIG) $(APP_COMPOSE) $(RUNTIME_PROFILES) up -d
	@$(MAKE) agent-runtime-ready
	@echo ""
	@echo "Docker dev stack started:"
	@echo "  Dashboard:     http://localhost:3000"
	@echo "  API:           http://localhost:8001"
	@echo "  API Docs:      http://localhost:8001/docs"
	@echo "  VNC WebSocket: http://localhost:6080/websockify"
	@echo "  MinIO Console: http://localhost:9001"
	@echo ""
	@echo "View logs: make logs"

dev-fast:
	@$(MAKE) prod-env-bootstrap
	@if ! docker image inspect "$${QUORVEX_FRONTEND_DEV_IMAGE:-quorvex-frontend:dev}" >/dev/null 2>&1; then \
		echo "Missing fast-dev frontend image: $${QUORVEX_FRONTEND_DEV_IMAGE:-quorvex-frontend:dev}"; \
		echo "Run 'make dev-fast-build' once, then rerun 'make dev-fast'."; \
		exit 2; \
	fi
	@echo "Starting fast Docker development stack without rebuilding images..."
	@echo ""
	@echo "This target is additive and leaves 'make dev' unchanged."
	@echo "It uses docker-compose.dev-fast.yml and refuses implicit image builds."
	@echo "Run 'make dev-fast-build' after dependency, lockfile, or Dockerfile changes."
	@echo ""
	@COMPOSE_BAKE=false BUILDX_CONFIG=$(BUILDX_CONFIG) $(FAST_DEV_COMPOSE) $(RUNTIME_PROFILES) up -d --no-build db redis minio
	@python3 scripts/reconcile_prod_postgres.py
	@COMPOSE_BAKE=false BUILDX_CONFIG=$(BUILDX_CONFIG) $(FAST_DEV_COMPOSE) $(RUNTIME_PROFILES) up -d --no-build
	@$(MAKE) agent-runtime-ready
	@echo ""
	@echo "Fast Docker dev stack started:"
	@echo "  Dashboard:     http://localhost:3000"
	@echo "  API:           http://localhost:8001"
	@echo "  API Docs:      http://localhost:8001/docs"
	@echo "  VNC WebSocket: http://localhost:6080/websockify"
	@echo "  MinIO Console: http://localhost:9001"
	@echo ""
	@echo "View logs: make logs"

dev-fast-build:
	@$(MAKE) prod-env-bootstrap
	@echo "Building fast-dev frontend image..."
	@COMPOSE_BAKE=false BUILDX_CONFIG=$(BUILDX_CONFIG) $(FAST_DEV_COMPOSE) --progress=plain $(RUNTIME_PROFILES) build frontend
	@if [ "$(BACKEND)" = "1" ]; then \
		echo "BACKEND=1 set; rebuilding backend images for fast dev..."; \
		COMPOSE_BAKE=false BUILDX_CONFIG=$(BUILDX_CONFIG) $(FAST_DEV_COMPOSE) --progress=plain $(RUNTIME_PROFILES) build backend autonomous-mission-worker custom-workflow-worker; \
	elif ! docker image inspect "$${QUORVEX_BACKEND_IMAGE:-quorvex-backend:prod}" >/dev/null 2>&1 || \
	     ! docker image inspect "$${QUORVEX_BACKEND_SLIM_IMAGE:-quorvex-backend-slim:prod}" >/dev/null 2>&1; then \
		echo "Backend image missing; building backend images once..."; \
		COMPOSE_BAKE=false BUILDX_CONFIG=$(BUILDX_CONFIG) $(FAST_DEV_COMPOSE) --progress=plain $(RUNTIME_PROFILES) build backend autonomous-mission-worker custom-workflow-worker; \
	else \
		echo "Backend images already exist; skipping heavy backend rebuild."; \
		echo "Use 'make dev-fast-build BACKEND=1' after Python, root package, or backend Dockerfile dependency changes."; \
	fi
	@echo "Fast-dev images are ready. Start with: make dev-fast"

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

agent-temporal-smoke-up:
	@echo "Starting services required for agent Temporal smoke..."
	@$(DOCKER_COMPOSE) up -d db temporal temporal-ui custom-workflow-worker
	@echo "Run smoke with: make agent-temporal-smoke"

agent-temporal-smoke:
	@echo "Running deterministic agent Temporal smoke..."
	@DATABASE_URL="$${DATABASE_URL:-postgresql://postgres:postgres@localhost:5434/playwright_agent}" \
	TEMPORAL_ADDRESS="$${TEMPORAL_ADDRESS:-localhost:7233}" \
	TEMPORAL_NAMESPACE="$${TEMPORAL_NAMESPACE:-default}" \
	TEMPORAL_WORKFLOW_TASK_QUEUE="$${TEMPORAL_WORKFLOW_TASK_QUEUE:-quorvex-custom-workflows}" \
	python scripts/agent_temporal_smoke.py --timeout "$${AGENT_TEMPORAL_SMOKE_TIMEOUT:-90}"

agent-temporal-smoke-logs:
	@$(DOCKER_COMPOSE) logs -f temporal custom-workflow-worker

agent-runtime-ready:
	@python scripts/check_agent_runtime_ready.py \
		--api-base "$${QUORVEX_PUBLIC_API_URL:-http://localhost:8001}" \
		--timeout "$${STARTUP_TIMEOUT_SECONDS:-180}"

deploy-check:
	@python3 scripts/deploy_check.py

company-rehearsal:
	@bash deploy/rehearse-company-external-nginx.sh

release-preflight:
	@if [ -z "$(VERSION)" ]; then \
		echo "Usage: make release-preflight VERSION=v1.2.3"; \
		exit 2; \
	fi
	@bash deploy/release-preflight.sh "$(VERSION)"

server-upgrade:
	@if [ -z "$(VERSION)" ]; then \
		echo "Usage: make server-upgrade VERSION=v1.2.3"; \
		exit 2; \
	fi
	@bash deploy/server-upgrade.sh "$(VERSION)"

release-to-server:
	@if [ -z "$(VERSION)" ]; then \
		echo "Usage: make release-to-server VERSION=v1.2.3 QUORVEX_SERVER_HOST=user@host"; \
		exit 2; \
	fi
	@VERSION="$(VERSION)" bash scripts/release_to_server.sh --deploy

# ==========================================
# DOCKER
# ==========================================

docker-up:
	@echo "docker-compose.yml is a legacy local-only path and is not supported for current app runtime work."
	@echo "Use 'make dev' for local full-stack Docker development or 'make start' for company/server external-nginx runtime."
	@exit 2

docker-down:
	@echo "Stopping all Docker services..."
	@$(DOCKER_COMPOSE) down
	@echo "Services stopped."

docker-build:
	@echo "Rebuilding Docker images..."
	@$(DOCKER_COMPOSE) build --no-cache
	@echo "Images rebuilt. Use 'make dev' or 'make start' for supported runtime paths."

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

prod-up:
	@if [ "$(QUORVEX_ENABLE_REPO_NGINX)" != "1" ]; then \
		echo "prod-up starts the legacy repo-managed nginx path and is not part of company/server deployment."; \
		echo "Use 'make start' for external-nginx runtime, or rerun with QUORVEX_ENABLE_REPO_NGINX=1 if you explicitly need repo nginx."; \
		exit 2; \
	fi
	@echo "Starting production services (standard mode with VNC + nginx)..."
	@$(PROD_COMPOSE) --profile standard --profile nginx --profile backup-scheduler up -d
	@echo ""
	@echo "Production services started:"
	@echo "  Dashboard:     http://localhost:3000 (direct) / http://localhost:80 (via nginx)"
	@echo "  API:           http://localhost:8001"
	@echo "  API Docs:      http://localhost:8001/docs"
	@echo "  VNC View:      http://localhost:6080"
	@echo "  MinIO Console: http://localhost:9001"
	@echo "  Backup Scheduler: enabled"
	@echo ""
	@echo "View logs: make prod-logs"

prod: prod-up

prod-dev:
	@echo "prod-dev is a compatibility alias. Use 'make dev' for the supported local Docker development workflow."
	@$(MAKE) dev

prod-dev-build:
	@echo "Rebuilding production development images..."
	@set -e; \
	for service in frontend backend autonomous-mission-worker custom-workflow-worker; do \
		echo "Building $$service..."; \
		COMPOSE_BAKE=false BUILDX_CONFIG=$(BUILDX_CONFIG) $(APP_COMPOSE) --progress=plain $(RUNTIME_PROFILES) build $$service; \
	done

prod-env-bootstrap:
	@echo "Bootstrapping production environment..."
	@python3 scripts/bootstrap_prod_env.py

prod-down:
	@echo "Stopping production services gracefully..."
	@-$(APP_COMPOSE) $(STOP_PROFILES) down --remove-orphans --timeout 30 2>/dev/null || true
	@-$(PROD_COMPOSE) $(STOP_PROFILES) down --remove-orphans --timeout 30 2>/dev/null || true
	@echo "Production services stopped."

prod-down-safe:
	@echo "=== Safe Production Shutdown ==="
	@echo "Step 1: Running backup before shutdown..."
	@$(PROD_COMPOSE) --profile backup-full run --rm backup-full 2>/dev/null || echo "Backup skipped (service not available)"
	@echo "Step 2: Stopping services gracefully (30s timeout)..."
	@-$(APP_COMPOSE) $(STOP_PROFILES) down --remove-orphans --timeout 30 2>/dev/null || true
	@-$(PROD_COMPOSE) $(STOP_PROFILES) down --remove-orphans --timeout 30 2>/dev/null || true
	@echo "Step 3: Verifying shutdown..."
	@docker ps --filter "name=quorvex" --format "{{.Names}}" | grep -q . && echo "WARNING: Some containers still running!" || echo "All containers stopped."
	@echo "=== Safe shutdown complete ==="

prod-restart:
	@echo "Restarting app services (picking up mounted code changes)..."
	@$(APP_COMPOSE) $(RUNTIME_PROFILES) restart backend frontend || $(PROD_COMPOSE) $(RUNTIME_PROFILES) restart backend frontend
	@echo "App services restarted."

prod-logs:
	@$(PROD_COMPOSE) $(RUNTIME_PROFILES) logs -f backend frontend autonomous-mission-worker custom-workflow-worker

prod-build:
	@if [ ! -f ".env.prod" ]; then \
		echo "No .env.prod file found. Creating from .env.prod.example..."; \
		cp .env.prod.example .env.prod; \
		echo "Created .env.prod — edit it with your API credentials."; \
		echo ""; \
	fi
	@echo "Rebuilding production images (with cache)..."
	@$(PROD_COMPOSE) --profile standard --profile nginx --profile backup-scheduler --profile k6-workers build
	@echo "Images rebuilt. Run 'make prod-up' to start."

prod-build-no-cache:
	@echo "Rebuilding production images (no cache - fresh build)..."
	@$(PROD_COMPOSE) --profile standard --profile nginx --profile backup-scheduler --profile k6-workers build --no-cache
	@echo "Images rebuilt. Run 'make prod-up' to start."

prod-status:
	@echo "Production service status:"
	@echo ""
	@$(PROD_COMPOSE) --profile standard --profile nginx --profile backup-scheduler ps
	@echo ""
	@echo "Health checks:"
	@curl -s http://localhost:8001/health 2>/dev/null | python3 -m json.tool 2>/dev/null || echo "  Backend: Not responding"
	@echo ""

# ==========================================
# AUTO PILOT LOCAL RUNTIME
# ==========================================

autopilot-stable-up:
	@echo "autopilot-stable-up is currently unsupported: docker-compose.autopilot-stable.yml references browser-runtime without a valid base service."
	@echo "Use 'make dev' for local Auto Pilot development until this stack is rebuilt."
	@exit 2

autopilot-stable-down:
	@echo "Stopping stable local Auto Pilot stack..."
	@$(AUTOPILOT_STABLE_COMPOSE) --profile standard down --remove-orphans --timeout 30
	@echo "Stable Auto Pilot stack stopped."

autopilot-dev-up:
	@echo "Starting Auto Pilot dev stack with hot reload..."
	@$(MAKE) dev

autopilot-status:
	@echo "Auto Pilot service status:"
	@echo ""
	@$(AUTOPILOT_STABLE_COMPOSE) --profile standard ps
	@echo ""
	@echo "Container memory:"
	@docker stats --no-stream --format 'table {{.Name}}\t{{.MemUsage}}\t{{.MemPerc}}\t{{.CPUPerc}}' | grep -E 'NAME|quorvex_ai|quorvex-' || true
	@echo ""
	@echo "Health:"
	@curl -s http://localhost:8001/health 2>/dev/null | python3 -m json.tool 2>/dev/null || echo "  Backend: Not responding"

autopilot-logs:
	@$(AUTOPILOT_STABLE_COMPOSE) logs -f backend frontend

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
		elif [ -n "$$CLAUDE_CODE_OAUTH_TOKEN" ]; then \
			echo "  + CLAUDE_CODE_OAUTH_TOKEN is configured"; \
		else \
			echo "  ! Claude auth not configured"; \
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
		if [ -n "$$POSTGRES_PASSWORD" ] && ! printf "%s" "$$POSTGRES_PASSWORD" | grep -q "^replace-with-"; then \
			echo "  + POSTGRES_PASSWORD is configured"; \
		else \
			echo "  ! POSTGRES_PASSWORD not configured"; \
		fi; \
		if [ -n "$$MINIO_ROOT_PASSWORD" ] && ! printf "%s" "$$MINIO_ROOT_PASSWORD" | grep -q "^replace-with-"; then \
			echo "  + MINIO_ROOT_PASSWORD is configured"; \
		else \
			echo "  ! MINIO_ROOT_PASSWORD not configured"; \
		fi; \
		if [ -n "$$JWT_SECRET_KEY" ] && [ "$$JWT_SECRET_KEY" != "dev-secret-key-change-in-production" ] && ! printf "%s" "$$JWT_SECRET_KEY" | grep -q "^replace-with-"; then \
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
		echo "    Docker images skip Nuclei by default; rebuild with INSTALL_NUCLEI=true to include it."; \
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
	@$(APP_COMPOSE) $(RUNTIME_PROFILES) logs -f backend frontend 2>/dev/null || \
		$(PROD_COMPOSE) $(RUNTIME_PROFILES) logs -f backend frontend 2>/dev/null || \
		tail -f api.log web.log 2>/dev/null || \
		echo "No logs found. Start services with 'make dev' or 'make start' first."

stop:
	@echo "Stopping services gracefully..."
	@# Stop Docker stacks first so Docker-owned port forwarders are not killed directly.
	@-$(APP_COMPOSE) $(STOP_PROFILES) down --remove-orphans --timeout 30 2>/dev/null || true
	@-$(PROD_COMPOSE) $(STOP_PROFILES) down --remove-orphans --timeout 30 2>/dev/null || true
	@-$(DOCKER_COMPOSE) --profile redis --profile k6-workers down --remove-orphans --timeout 30 2>/dev/null || true
	@# Then stop any remaining local processes started by start-ui.sh.
	@-lsof -ti :8001 | xargs kill -15 2>/dev/null || true
	@-lsof -ti :3000 | xargs kill -15 2>/dev/null || true
	@echo "  Waiting for graceful shutdown..."
	@sleep 3
	@# Force kill only if still running (SIGKILL)
	@-lsof -ti :8001 | xargs kill -9 2>/dev/null || true
	@-lsof -ti :3000 | xargs kill -9 2>/dev/null || true
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
	@$(PROD_COMPOSE) --profile workers build browser-workers agent-worker custom-workflow-worker backend-slim
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
	@echo "Temporal worker: custom-workflow-worker (custom workflows + agent runs)"
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
	@$(PROD_COMPOSE) --profile workers logs -f browser-workers agent-worker custom-workflow-worker backend-slim

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
	@echo "Docker Swarm deployment is currently unsupported and not company-deployment safe."
	@echo "Use 'make start' for server runtime or 'make dev' for local Docker development."
	@exit 2

swarm-down:
	@echo "Removing Swarm stack..."
	@docker stack rm quorvex
	@echo ""
	@echo "Swarm stack removed."
	@echo "Note: Swarm mode is still active. Run 'docker swarm leave --force' to disable."

swarm-scale:
	@echo "Docker Swarm scaling is currently unsupported."
	@exit 2

swarm-status:
	@echo "Docker Swarm runtime is currently unsupported."
	@docker stack services quorvex 2>/dev/null || true

# ==========================================
# KUBERNETES (Enterprise - Auto-scaling)
# ==========================================

# Kubernetes namespace
K8S_NAMESPACE ?= quorvex

k8s-deploy:
	@echo "Kubernetes deployment is currently unsupported and not company-deployment safe."
	@echo "Use 'make start' for server runtime or 'make dev' for local Docker development."
	@exit 2

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
	@echo "Kubernetes scaling is currently unsupported."
	@exit 2

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
	@$(PROD_COMPOSE) exec backend $(ALEMBIC_RUNNER) revision --autogenerate -m "$(M)" 2>/dev/null || \
		($(LOCAL_ALEMBIC) revision --autogenerate -m "$(M)")
	@echo ""
	@echo "Migration generated. Review it in orchestrator/migrations/versions/"
	@echo "Then run: make db-upgrade"

db-upgrade:
	@echo "Running pending Alembic migrations..."
	@$(PROD_COMPOSE) exec backend $(ALEMBIC_RUNNER) upgrade head 2>/dev/null || \
		($(LOCAL_ALEMBIC) upgrade head)
	@echo "Migrations complete."

db-downgrade:
	@echo "Rolling back one Alembic migration..."
	@$(PROD_COMPOSE) exec backend $(ALEMBIC_RUNNER) downgrade -1 2>/dev/null || \
		($(LOCAL_ALEMBIC) downgrade -1)
	@echo "Rollback complete. Run 'make db-history' to verify."

db-history:
	@echo "=== Alembic Migration History ==="
	@$(PROD_COMPOSE) exec backend $(ALEMBIC_RUNNER) history --verbose 2>/dev/null || \
		($(LOCAL_ALEMBIC) history --verbose)

alembic-upgrade: db-upgrade

alembic-history: db-history

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
	@$(PROD_COMPOSE) exec backend $(ALEMBIC_RUNNER) stamp $(R) 2>/dev/null || \
		($(LOCAL_ALEMBIC) stamp $(R))
	@echo "Database stamped at revision $(R)."

db-demo-seed:
	@echo "Seeding Database Testing demo content..."
	@PROJECT_ID="$(or $(PROJECT),default)"; \
	if [ -n "$(CONNECTION_HOST)" ]; then HOST_ARG="--connection-host $(CONNECTION_HOST)"; else HOST_ARG=""; fi; \
	if [ -n "$(CONNECTION_PORT)" ]; then PORT_ARG="--connection-port $(CONNECTION_PORT)"; else PORT_ARG=""; fi; \
	if [ -n "$(SCHEMA)" ]; then SCHEMA_ARG="--schema $(SCHEMA)"; else SCHEMA_ARG=""; fi; \
	(source venv/bin/activate 2>/dev/null || true; \
		DATABASE_URL="$${DATABASE_URL:-postgresql://postgres:postgres@localhost:5434/playwright_agent}" \
		python orchestrator/scripts/seed_database_testing_demo.py --project-id "$$PROJECT_ID" $$HOST_ARG $$PORT_ARG $$SCHEMA_ARG)

youtube-demo-seed:
	@echo "Seeding Quorvex Demo Shop YouTube walkthrough data..."
	@PROJECT_ID="$(or $(PROJECT),quorvex-demo-shop)"; \
	if [ -n "$(CONNECTION_HOST)" ]; then HOST_ARG="--connection-host $(CONNECTION_HOST)"; else HOST_ARG=""; fi; \
	if [ -n "$(CONNECTION_PORT)" ]; then PORT_ARG="--connection-port $(CONNECTION_PORT)"; else PORT_ARG=""; fi; \
	if [ "$(SKIP_DATABASE)" = "1" ]; then DB_ARG="--skip-database"; else DB_ARG=""; fi; \
	if [ "$(NO_RESET_SCHEMA)" = "1" ]; then RESET_ARG="--no-reset-schema"; else RESET_ARG=""; fi; \
	if nc -z localhost 5434 >/dev/null 2>&1; then \
		(source venv/bin/activate 2>/dev/null || true; \
		DATABASE_URL="$${DATABASE_URL:-postgresql://postgres:postgres@localhost:5434/playwright_agent}" \
		JWT_SECRET_KEY="$${JWT_SECRET_KEY:-demo-seed-local-secret-key-change-me}" \
		REQUIRE_AUTH="$${REQUIRE_AUTH:-false}" \
		python orchestrator/scripts/seed_youtube_demo.py --project-id "$$PROJECT_ID" $$HOST_ARG $$PORT_ARG $$DB_ARG $$RESET_ARG); \
	elif $(DOCKER_COMPOSE) ps --services --filter status=running 2>/dev/null | grep -qx backend; then \
		$(DOCKER_COMPOSE) exec -T backend sh -lc 'DATABASE_URL="$${DATABASE_URL:-postgresql://playwright:postgres@db:5432/playwright_agent}" JWT_SECRET_KEY="$${JWT_SECRET_KEY:-demo-seed-local-secret-key-change-me}" REQUIRE_AUTH="$${REQUIRE_AUTH:-false}" python orchestrator/scripts/seed_youtube_demo.py --project-id "$$0" $$1 $$2 $$3 $$4' "$$PROJECT_ID" "$$HOST_ARG" "$$PORT_ARG" "$$DB_ARG" "$$RESET_ARG"; \
	else \
		(source venv/bin/activate 2>/dev/null || true; \
		DATABASE_URL="$${DATABASE_URL:-postgresql://postgres:postgres@localhost:5434/playwright_agent}" \
		JWT_SECRET_KEY="$${JWT_SECRET_KEY:-demo-seed-local-secret-key-change-me}" \
		REQUIRE_AUTH="$${REQUIRE_AUTH:-false}" \
		python orchestrator/scripts/seed_youtube_demo.py --project-id "$$PROJECT_ID" $$HOST_ARG $$PORT_ARG $$DB_ARG $$RESET_ARG); \
	fi

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
	python -m pytest orchestrator/tests -v
	@echo ""
	@echo "All tests passed!"

backend-unit:
	@python -m pytest orchestrator/tests -m "not integration"

backend-integration:
	@python -m pytest orchestrator/tests -m "integration"

frontend-static:
	@npm --prefix web run lint
	@npm --prefix web run typecheck
	@npm --prefix web run build

frontend-unit:
	@npm --prefix web run test

playwright-e2e:
	@npx playwright test tests/e2e --project=$${PLAYWRIGHT_PROJECT:-chromium}

playwright-generated:
	@npx playwright test tests/generated --project=$${PLAYWRIGHT_PROJECT:-chromium}

autonomous-soak:
	@echo "Running autonomous product-UI soak..."
	@python scripts/autonomous_soak.py \
		--api-base "$${SOAK_API_BASE:-http://127.0.0.1:8000}" \
		--project-id "$${SOAK_PROJECT_ID:-default}" \
		--target-url "$${SOAK_TARGET_URL:-http://127.0.0.1:3000}" \
		--iterations "$${SOAK_ITERATIONS:-10}" \
		--minutes "$${SOAK_MINUTES:-120}" \
		--poll-seconds "$${SOAK_POLL_SECONDS:-60}"

# ==========================================
# DOCUMENTATION
# ==========================================

docs-check:
	@python scripts/check_docs_drift.py
	@if [ -x "./venv/bin/mkdocs" ]; then \
		./venv/bin/mkdocs build --strict; \
	else \
		mkdocs build --strict; \
	fi

docs-visual-check:
	@python scripts/check_docs_drift.py --visual-only

docs-visual-capture:
	node scripts/docs-assets/capture-docs-assets.mjs --base-url $${BASE_URL:-http://127.0.0.1:3000} --update-docs-assets

docs-serve:
	pip install -r requirements-docs.txt && mkdocs serve

docs-build:
	pip install -r requirements-docs.txt && mkdocs build --strict

docs-deploy:
	pip install -r requirements-docs.txt && mkdocs gh-deploy --force

# ==========================================
# YOUTUBE PRODUCTION
# ==========================================

YOUTUBE_DEMO_VOICE_ID ?= DODLEQrClDo8wCz460ld

youtube-pack:
	@EPISODE="$(if $(EP),$(EP),001)"; \
	python scripts/youtube/generate-episode-pack.py --episode "$$EPISODE" --force

youtube-voice:
	@EPISODE="$(if $(EP),$(EP),001)"; \
	PYTHON_BIN="$$(if [ -x venv/bin/python ]; then echo venv/bin/python; else echo python; fi)"; \
	"$$PYTHON_BIN" scripts/demo-video/generate-voice.py \
		--lang en \
		--voice "$(if $(VOICE),$(VOICE),$(YOUTUBE_DEMO_VOICE_ID))" \
		--input "content/youtube/episodes/$$EPISODE/script.md" \
		--output-dir "content/youtube/episodes/$$EPISODE/build"

youtube-avatar:
	@EPISODE="$(if $(EP),$(EP),001)"; \
	python scripts/youtube/generate-avatar-payloads.py --episode "$$EPISODE" $(if $(SUBMIT),--submit,)

youtube-assemble:
	@if [ -z "$(RECORDING)" ]; then \
		echo "Error: RECORDING argument is required."; \
		echo "Usage: make youtube-assemble EP=001 RECORDING=path/to/recording.mp4"; \
		exit 1; \
	fi
	@EPISODE="$(if $(EP),$(EP),001)"; \
	bash scripts/youtube/assemble-episode.sh --episode "$$EPISODE" --recording "$(RECORDING)"

youtube-final:
	@if [ -z "$(RECORDING)" ]; then \
		echo "Error: RECORDING argument is required."; \
		echo "Usage: make youtube-final EP=001 RECORDING=path/to/recording.mp4"; \
		exit 1; \
	fi
	@if [ ! -f "$(RECORDING)" ]; then \
		echo "Error: recording not found: $(RECORDING)"; \
		exit 1; \
	fi
	@EPISODE="$(if $(EP),$(EP),001)"; \
	VOICE_NAME="$(if $(VOICE),$(VOICE),$(YOUTUBE_DEMO_VOICE_ID))"; \
	$(MAKE) youtube-demo-seed; \
	$(MAKE) youtube-voice EP="$$EPISODE" VOICE="$$VOICE_NAME"; \
	$(MAKE) youtube-assemble EP="$$EPISODE" RECORDING="$(RECORDING)"

youtube-mcp-check:
	@EPISODE="$(if $(EP),$(EP),001)"; \
	PYTHON_BIN="$$(if [ -x venv/bin/python ]; then echo venv/bin/python; else echo python; fi)"; \
	"$$PYTHON_BIN" -m py_compile tools/youtube_mcp/server.py tools/obs_mcp/server.py; \
	"$$PYTHON_BIN" tools/youtube_mcp/server.py check --episode "$$EPISODE"; \
	"$$PYTHON_BIN" tools/obs_mcp/server.py check --episode "$$EPISODE"

youtube-upload-dry-run:
	@EPISODE="$(if $(EP),$(EP),001)"; \
	PYTHON_BIN="$$(if [ -x venv/bin/python ]; then echo venv/bin/python; else echo python; fi)"; \
	if [ -n "$(VIDEO)" ]; then VIDEO_ARG="--video-path $(VIDEO)"; else VIDEO_ARG=""; fi; \
	if [ -n "$(THUMBNAIL)" ]; then THUMBNAIL_ARG="--thumbnail-path $(THUMBNAIL)"; else THUMBNAIL_ARG=""; fi; \
	YOUTUBE_DRY_RUN=1 "$$PYTHON_BIN" tools/youtube_mcp/server.py prepare-upload --episode "$$EPISODE" $$VIDEO_ARG $$THUMBNAIL_ARG

youtube-upload-confirm:
	@if [ -z "$(VIDEO)" ]; then \
		echo "Error: VIDEO argument is required."; \
		echo "Usage: make youtube-upload-confirm EP=001 VIDEO=content/youtube/episodes/001/build/youtube-001.mp4"; \
		exit 1; \
	fi
	@EPISODE="$(if $(EP),$(EP),001)"; \
	PYTHON_BIN="$$(if [ -x venv/bin/python ]; then echo venv/bin/python; else echo python; fi)"; \
	YOUTUBE_DRY_RUN=0 "$$PYTHON_BIN" tools/youtube_mcp/server.py upload-video --episode "$$EPISODE" --video-path "$(VIDEO)" --confirm

obs-recording-dry-run:
	@EPISODE="$(if $(EP),$(EP),001)"; \
	PYTHON_BIN="$$(if [ -x venv/bin/python ]; then echo venv/bin/python; else echo python; fi)"; \
	if [ -n "$(SCENES)" ]; then SCENE_ARG="--scene-sequence $(SCENES)"; else SCENE_ARG=""; fi; \
	OBS_DRY_RUN=1 "$$PYTHON_BIN" tools/obs_mcp/server.py prepare-recording --episode "$$EPISODE" $$SCENE_ARG

obs-recording-confirm:
	@EPISODE="$(if $(EP),$(EP),001)"; \
	PYTHON_BIN="$$(if [ -x venv/bin/python ]; then echo venv/bin/python; else echo python; fi)"; \
	OBS_DRY_RUN=0 "$$PYTHON_BIN" tools/obs_mcp/server.py start-recording --episode "$$EPISODE" --confirm

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
	@echo "make upgrade is a legacy in-place path and is currently unsupported."
	@echo "Use 'make server-upgrade VERSION=v1.2.3' for server updates or 'make release-to-server VERSION=v1.2.3' from local development."
	@exit 2
