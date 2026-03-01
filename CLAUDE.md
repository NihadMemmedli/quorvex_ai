# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## System Overview

**Natural Language to Test Script Converter** - AI-powered pipeline with dual-interface architecture (CLI + Web Dashboard) that converts plain English test specifications into production-ready Playwright tests.

**Key capability**: Write tests in markdown → Get validated, passing Playwright code automatically.

**Architecture**: Python backend (`orchestrator/`) + Next.js frontend (`web/`) + PostgreSQL/SQLite database + Playwright test runner + Memory system (vector embeddings + graph store)

## Essential Commands

```bash
# One-time setup (Python venv, Node deps, Playwright browsers, Database)
make setup

# Start web dashboard (Backend API on :8001 + Frontend on :3000)
make dev

# Run a specific test spec via CLI (uses Native Pipeline by default)
make run SPEC=specs/your-test.md

# Direct CLI execution with options
python orchestrator/cli.py specs/your-test.md              # Native Pipeline (default, recommended)
python orchestrator/cli.py specs/your-test.md --hybrid     # Hybrid healing (Native + Ralph escalation)
python orchestrator/cli.py specs/your-test.md --standard-pipeline  # Legacy standard pipeline

# Process PDF PRD to tests
python orchestrator/cli.py your-prd.pdf --prd
python orchestrator/cli.py your-prd.pdf --prd --feature "User Login"

# AI-powered app exploration
python orchestrator/workflows/app_explorer.py --url https://example.com --max-interactions 50

# Run generated Playwright tests
npx playwright test                                    # All tests
npx playwright test tests/generated/your-test.spec.ts # Specific test

# Skill mode (network interception, multi-tab, etc.) - see .claude/skills/playwright/SKILL.md
make setup-skills
python orchestrator/cli.py --run-skill /tmp/script.js
python orchestrator/cli.py specs/test.md --skill-mode

# Load testing with K6
make k6-workers-up                    # Start distributed K6 worker containers
make k6-workers-scale N=3             # Scale K6 workers
make k6-workers-down                  # Stop K6 workers
make k6-workers-status                # Check worker health

# Backup & Storage (production)
make backup             # Database-only backup
make backup-full        # Full backup (DB + specs + tests + PRDs + ChromaDB)
make restore TS=...     # Restore from timestamp
make storage-health     # Check DB, MinIO, local storage health
make archival           # Run artifact archival (30-day retention)

# Database migrations (PostgreSQL only)
make db-migrate M="description"   # Generate new Alembic migration
make db-upgrade                   # Run pending migrations
make db-downgrade                 # Roll back one migration

# Production maintenance
make upgrade            # Full upgrade (backup, pull, migrate, restart)
make health-check       # Hit all health endpoints
make docker-prune       # Remove dangling images and build cache

# Linting & formatting (Python: ruff, config in orchestrator/pyproject.toml)
make lint       # Ruff check (Python) + next lint (frontend)
make format     # Ruff format (Python)
make test       # Run all Python tests (cd orchestrator && pytest tests/ -v)

# Production development (Docker: backend :8001 + frontend :3000 + PostgreSQL)
make prod-dev   # Start prod with local code mounted (no rebuild needed)
make prod-restart # Restart backend (picks up code changes)
make prod-logs  # Tail production logs
make prod-status # Show status of all services

# Utilities
make clean      # Remove run artifacts
make check-env  # Validate configuration
make logs       # Tail backend and frontend logs
make stop       # Stop all running services
```

## Code Style

**Python** (enforced by ruff, config in `orchestrator/pyproject.toml`): Line length 120, double quotes, isort for imports. `B008` ignored (FastAPI `Depends` in defaults is fine). Target: Python 3.10.

**Frontend**: Next.js default linting via `next lint`.

## Pipeline Architecture

### Execution Modes

**CLI Mode** (`orchestrator/cli.py`): Direct execution, no database required, artifacts stored in `runs/TIMESTAMP/`

**Web Dashboard Mode** (`orchestrator/api/` + `web/`): FastAPI backend (port 8001), Next.js frontend (port 3000), PostgreSQL/SQLite for persistence

### Pipeline Types

1. **Native Pipeline** (default): Browser exploration at every stage → Most reliable
   - `NativePlanner` → `NativeGenerator` → `NativeHealer`
   - Optional: `--hybrid` for Native + Ralph healing escalation (up to 20 iterations)
2. **Standard Pipeline** (`--standard-pipeline`): Legacy text-only planning
   - `planner.py` → `plan_executor.py` → `exporter.py` → `validator.py`

**PRD Pipeline** (`--prd`): PDF → Feature extraction → Native spec generation → Test generation

**AI Exploration Pipeline**: Autonomous web app discovery using Playwright MCP tools. Discovers pages, user flows, API endpoints, form behaviors, error states. Stores findings for requirements generation and RTM creation.

**API Testing Pipeline**: OpenAPI spec import → API test generation → execution with self-healing. Supports both OpenAPI-driven and exploration-driven test creation. Uses `native_api_generator.py` and `native_api_healer.py` (no browser/Playwright MCP, pure HTTP testing).

**Exploration → Requirements → RTM Pipeline**: End-to-end flow from AI app exploration to requirements extraction to traceability matrix. Exploration sessions discover flows/endpoints → AI generates structured requirements → RTM maps requirements to test specs with coverage analysis.

**Skill Pipeline** (`--skill-mode` or `--run-skill`): Execute arbitrary Playwright scripts for complex scenarios (network interception, multi-tab, performance testing). See `.claude/skills/playwright/SKILL.md` for format and decision matrix.

### Smart Check (Stage 0)

Before running any pipeline, the system checks for existing generated code:
- **Reuse**: If valid code exists, run it immediately
- **Heal**: If existing code fails, attempt to fix it
- **Regenerate**: Full generation only if healing fails or no code exists

### Healing Modes

- **Native Healer** (default): 3 attempts using Playwright's `test_debug` MCP tool
- **Hybrid Mode** (`--hybrid`): Native (3 attempts) + Ralph escalation (up to 17 more)

## Critical Patterns

### Subprocess Execution
Each pipeline stage runs as a separate subprocess to avoid SDK cleanup issues. The main orchestrator (`cli.py`) spawns individual workflow scripts via `run_command()`.

### Agent Execution
Most workflows use `AgentRunner` (`orchestrator/utils/agent_runner.py`) for consistent agent execution with timeouts, logging, and SDK cleanup handling. The healer workflows use `query()` directly from `claude_agent_sdk` with manual message streaming. All pipeline stages set `allowed_tools=["*"]` to grant unrestricted MCP tool access.

### Logging
All backend code uses `logging.getLogger(__name__)`. Configuration in `orchestrator/logging_config.py` provides colored console output, rotating file handler (`logs/orchestrator.log`, 10MB, 5 backups), and optional JSON format for production. Workflow files call `setup_logging()` in their `__main__` blocks for standalone execution. The API layer configures logging at startup via `main.py`.

**Convention**: Use `logger.info()` for progress, `logger.warning()` for recoverable issues, `logger.error()` for failures. Never use bare `print()` in backend code — use logger instead.

### Credential Loading
**All AI credentials load from `.env` via `orchestrator/load_env.py`**. Every workflow file must call `setup_claude_env()` before using the Agent SDK.

### Environment Variables

**AI/LLM (required)**:
- `ANTHROPIC_AUTH_TOKEN` - API authentication token
- `ANTHROPIC_BASE_URL` - API endpoint (anthropic direct, openrouter, or custom proxy)
- `ANTHROPIC_DEFAULT_SONNET_MODEL` - Model ID (e.g., `claude-sonnet-4-20250514`)
- `OPENAI_API_KEY` - For memory system embeddings (optional)

**Authentication**:
- `JWT_SECRET_KEY` - Required for token signing
- `REQUIRE_AUTH` - Enable auth enforcement (default: `false`)
- `ALLOW_REGISTRATION` - Allow new user signups (default: `true`)
- `REDIS_URL` - For distributed rate limiting (optional)

**Database**: `DATABASE_URL` - SQLite (default: `sqlite:///./test.db`) or PostgreSQL

**Browser Pool**:
- `MAX_BROWSER_INSTANCES` - Hard limit on concurrent browsers (default: `5`)
- `BROWSER_SLOT_TIMEOUT` - Max wait for a slot in seconds (default: `3600`)

**Agent Timeouts**:
- `AGENT_TIMEOUT_SECONDS` - Default timeout for all agents (default: `1800`)
- `EXPLORATION_TIMEOUT_SECONDS`, `PLANNER_TIMEOUT_SECONDS`, `GENERATOR_TIMEOUT_SECONDS` - Per-agent overrides

**MinIO Storage** (production):
- `MINIO_ENDPOINT`, `MINIO_ROOT_USER`, `MINIO_ROOT_PASSWORD`
- `MINIO_BUCKET` (backups), `MINIO_BUCKET_ARTIFACTS` (archived artifacts)

**Backup/Archival**: `BACKUP_RETENTION` (default: 30 days), `ARCHIVE_HOT_DAYS` (default: 30), `ARCHIVE_TOTAL_DAYS` (default: 90)

**VNC** (admin-only): `VNC_ENABLED`, `DISPLAY=:99`

**Logging**: `LOG_LEVEL` (default: `INFO`)

**Load Testing**: `K6_MAX_VUS` (default: `1000`), `K6_MAX_DURATION` (default: `5m`), `K6_TIMEOUT_SECONDS` (default: `3600`)

**Security Testing**: `ZAP_HOST`, `ZAP_PORT`, `ZAP_API_KEY`, `ZAP_PROXY_ENABLED`, `NUCLEI_TIMEOUT_SECONDS`, `SECURITY_SCAN_TIMEOUT`

**Playwright**: `HEADLESS`, `BASE_URL`, `SKILL_DIR`, `SKILL_TIMEOUT`, `SLOW_MO`

### Credential Placeholders in Specs
1. Define secrets in `.env`: `LOGIN_PASSWORD=SecretValue`
2. Use in spec: `Enter password "{{LOGIN_PASSWORD}}"`
3. Generated code uses: `process.env.LOGIN_PASSWORD` (never hardcoded)

### JSON Output Format
Agents output JSON in markdown code blocks. Use `orchestrator/utils/json_utils.py:extract_json_from_markdown()` to parse.

### Selector Strategy (Playwright Best Practice)
- `getByRole('button', {name: 'Login'})` - Most resilient
- `getByLabel('Username')` - Best for form fields
- `getByText('Hello World')` - Good for text content
- Avoid CSS selectors like `locator('.btn-primary')` (brittle)

## TestRail Integration

Bidirectional sync between local specs and TestRail test cases. Configured per-project in Settings page.

### Capabilities
- **Push cases**: Sync local specs to TestRail as test cases with steps and expected results
- **Sync results**: Push regression batch results to TestRail as test runs
- **Mapping tracking**: Maintains local-to-TestRail ID mappings for incremental sync
- **Connection test**: Validate credentials before saving

### API Endpoints (`orchestrator/api/testrail.py`, prefix: `/testrail/{project_id}`)
- `GET/POST/DELETE /config` - Manage TestRail credentials (API key encrypted at rest)
- `POST /test-connection` - Validate credentials
- `GET /remote-projects` - List TestRail projects
- `GET /remote-suites/{tr_project_id}` - List suites in a project
- `POST /push-cases` - Push specs as test cases
- `GET /mappings` - View case mappings
- `GET /sync-preview/{batch_id}` - Preview batch result sync
- `POST /sync-results` - Push batch results to TestRail as a test run

### Configuration
Set in Settings UI or via API. Requires: TestRail base URL, email, API key, project ID, and suite ID. Credentials stored encrypted in `Project.settings["integrations"]["testrail"]`.

### Key Files
- `orchestrator/api/testrail.py` - API endpoints
- `orchestrator/services/testrail_client.py` - Async HTTP client with rate limiting
- `orchestrator/api/models_db.py` - `TestrailCaseMapping`, `TestrailRunMapping` models

## API Testing Framework

Separate pipeline for HTTP/REST API testing without browser automation.

### Flow
1. **Import**: OpenAPI/Swagger spec upload → parsed into API test specs stored in `specs/api/`
2. **Generate**: AI generates Playwright API test code from specs using `native_api_generator.py`
3. **Execute**: Tests run via Playwright (HTTP requests, not browser)
4. **Heal**: `native_api_healer.py` fixes failures without Playwright MCP tools (pure code analysis)

### Key Differences from UI Testing
- No Playwright MCP server needed (no browser)
- API specs stored separately in `specs/api/` subdirectories
- Uses in-memory job tracking (`_api_jobs` dict) with DB-backed run history (`TestRun` model)
- Run results stored in database, not just filesystem

### API Endpoints (`orchestrator/api/api_testing.py`, prefix: `/api-testing`)
- `POST /specs` - Create API test spec
- `POST /import-openapi` - Import OpenAPI/Swagger spec
- `POST /specs/{folder}/run` - Run API test with background job tracking
- `GET /runs` - List run history from database
- `GET /runs/{run_id}` - Get run details with logs

## Load Testing Framework

K6-based load testing with AI-generated scripts and distributed execution.

### Flow
1. **Spec**: Write load test spec in markdown (VU count, duration, endpoints, thresholds)
2. **Generate**: AI converts spec to K6 JavaScript via `load_test_generator.py`
3. **Execute**: K6 runs locally or distributed across worker containers
4. **Monitor**: Real-time metrics, timeseries data, HTTP status breakdown, run comparison

### Exclusive Lock System
Only one load test can run at a time. `load_test_lock.py` acquires an exclusive lock (Redis or in-memory) that also **pauses all browser operations** via the browser pool. Lock has 2-hour TTL as safety net.

### Distributed Execution
When Redis and K6 workers are available, tests automatically use distributed mode:
- `orchestrator/services/k6_queue.py` - Redis task queue for K6 workers
- `orchestrator/services/k6_worker.py` - Worker process consuming from queue
- Workers run in isolated containers (`docker-compose.prod.yml --profile k6-workers`)

### API Endpoints (`orchestrator/api/load_testing.py`, prefix: `/load-testing`)
- `POST /specs` - Create load test spec
- `POST /specs/{folder}/generate` - Generate K6 script from spec
- `POST /specs/{folder}/run` - Execute load test (background job)
- `GET /runs/{run_id}/status` - Real-time status with metrics
- `POST /runs/{run_id}/stop` - Cancel running test
- `GET /runs/compare` - Compare multiple runs with overlay charts
- `GET /system-limits` - Current resource caps and worker status

### Configuration
- `K6_MAX_VUS` - Safety limit on virtual users (default: `1000`)
- `K6_MAX_DURATION` - Max test duration (default: `5m`)
- `K6_TIMEOUT_SECONDS` - Process timeout (default: `3600`)

## Security Testing Framework

Multi-tier security scanning with AI-powered analysis.

### Scanner Tiers
1. **Quick Scan**: Python-native checks using `httpx` (headers, cookies, SSL, CORS, info disclosure) ~10-30s
2. **Nuclei Scan**: Template-based vulnerability scanning via `nuclei` binary ~1-5min
3. **ZAP DAST**: Full dynamic application security testing with spider + active scan ~5-30min
4. **AI Analysis**: Claude-powered finding analysis, prioritization, and remediation planning ~1-2min

### Flow
1. **Spec**: Write security test spec in markdown (target URL, scan type, specific checks)
2. **Scan**: Run quick/nuclei/zap/full scan as background job
3. **Findings**: View, filter, and manage findings with severity levels
4. **Triage**: Mark findings as open/false_positive/fixed/accepted_risk
5. **Analyze**: AI generates prioritized remediation plan from findings

### Passive Mode
When `ZAP_PROXY_ENABLED=true`, functional Playwright tests proxy through ZAP for automatic passive security analysis.

### API Endpoints (`orchestrator/api/security_testing.py`, prefix: `/security-testing`)
- `POST/GET /specs` - Security spec CRUD
- `POST /scan/quick` - Run quick scan (background)
- `POST /scan/nuclei` - Run Nuclei scan (background)
- `POST /scan/zap` - Run ZAP DAST scan (background)
- `POST /scan/full` - Run all tiers sequentially
- `GET /jobs/{job_id}` - Poll scan job status
- `GET /runs` - List scan history
- `GET /runs/{run_id}` - Scan details with findings
- `GET /runs/{run_id}/findings` - Findings with severity filter
- `PATCH /findings/{id}/status` - Update finding status
- `GET /findings/summary` - Aggregated severity counts
- `POST /analyze/{run_id}` - AI remediation analysis
- `POST /generate-spec` - AI generates spec from exploration

### Docker Setup
ZAP daemon runs under `security` profile: `docker compose --profile security up -d zap`

### Configuration
- `ZAP_HOST` - ZAP daemon host (default: `localhost`)
- `ZAP_PORT` - ZAP daemon port (default: `8090`)
- `ZAP_API_KEY` - ZAP API key (optional)
- `ZAP_PROXY_ENABLED` - Enable passive mode (default: `false`)
- `NUCLEI_TIMEOUT_SECONDS` - Nuclei scan timeout (default: `600`)
- `SECURITY_SCAN_TIMEOUT` - Overall scan timeout (default: `1800`)

### Key Files
| Path | Purpose |
|------|---------|
| `orchestrator/api/security_testing.py` | API router with all endpoints |
| `orchestrator/services/security/quick_scanner.py` | Python-native security checks |
| `orchestrator/services/security/nuclei_runner.py` | Nuclei subprocess execution |
| `orchestrator/services/security/zap_client.py` | ZAP API client wrapper |
| `orchestrator/services/security/finding_deduplicator.py` | Cross-scanner dedup |
| `orchestrator/workflows/security_analyzer.py` | AI analysis workflow |
| `.claude/agents/security-analyzer.md` | AI agent prompt |

## LLM Testing Framework

Full LLM evaluation platform for testing AI providers against structured test suites.

### Capabilities
- **Provider management**: Register LLM providers (any OpenAI-compatible API) with encrypted API keys and custom pricing
- **Test specs**: Markdown-based LLM test definitions with system prompts, test cases, and assertions
- **Datasets**: Reusable test case collections with versioning, CSV import/export, and golden dataset marking
- **Run & Compare**: Execute suites against providers, compare multiple models side-by-side with scoring matrices
- **Prompt iterations**: A/B test system prompt changes with automated scoring against baselines
- **AI suite generation**: Generate test suites from system prompt + app description using AI
- **Dataset augmentation**: AI-powered generation of edge cases, adversarial inputs, boundary tests, or rephrases via `dataset_augmentor.py`
- **Scheduling**: Cron-based scheduled runs with execution history tracking
- **Analytics**: Overview stats, trends, latency distribution, cost tracking, regression detection, golden dashboard

### API Endpoints (`orchestrator/api/llm_testing.py`, prefix: `/llm-testing`)
- `POST/GET/PUT/DELETE /providers` - Provider CRUD with health checks
- `POST/GET/PUT/DELETE /specs` - LLM test spec CRUD with versioning (`/specs/{name}/versions`)
- `POST /run` - Run suite against a provider (background job)
- `POST /compare` - Compare multiple providers against same suite
- `POST /bulk-run`, `POST /bulk-compare` - Batch dataset operations
- `POST /generate-suite` - AI-generated test suite from system prompt
- `POST/GET/PUT/DELETE /datasets` - Dataset CRUD with cases, import/export
- `POST /datasets/{id}/augment` - AI augmentation with accept/reject flow
- `POST/GET/PUT/DELETE /schedules` - Scheduled run management
- `GET /analytics/*` - Overview, trends, latency, cost, regressions, golden dashboard
- `POST /prompt-iterations` - A/B prompt testing
- `POST /specs/{name}/suggest-improvements` - AI-powered spec improvement suggestions

### Key Files
| Path | Purpose |
|------|---------|
| `orchestrator/api/llm_testing.py` | All LLM testing endpoints (~3400 lines) |
| `orchestrator/workflows/dataset_augmentor.py` | AI dataset augmentation workflow |
| `orchestrator/api/models_db.py` | `LlmProvider`, `LlmTestRun`, `LlmTestResult`, `LlmDataset`, `LlmDatasetCase`, `LlmDatasetVersion`, `LlmComparisonRun`, `LlmSpecVersion`, `LlmPromptIteration`, `LlmSchedule`, `LlmScheduleExecution` |
| `web/src/app/(dashboard)/llm-testing/` | Frontend with tabs: Providers, Specs, Run, Compare, History, Datasets, Analytics, Prompts, Schedules |

## Database Testing Framework

PostgreSQL schema analysis and data quality testing with AI-powered suggestions.

### Flow
1. **Connect**: Register PostgreSQL connection profiles (credentials encrypted at rest)
2. **Analyze**: AI-powered schema analysis discovers tables, relationships, constraints
3. **Spec**: Write or AI-generate data quality check specs in markdown
4. **Execute**: Run checks (NULL rates, uniqueness, referential integrity, custom SQL)
5. **Suggest**: AI generates fix suggestions for failed checks
6. **Approve**: Review and apply approved suggestions

### API Endpoints (`orchestrator/api/database_testing.py`, prefix: `/database-testing`)
- `POST/GET/PUT/DELETE /connections` - Connection profile CRUD with test endpoint
- `POST /analyze/{conn_id}` - Schema analysis (background job)
- `POST /run/{conn_id}` - Run data quality checks
- `POST /run-full/{conn_id}` - Full pipeline (analyze + generate + run)
- `POST /suggest/{run_id}` - AI suggestions for failures
- `POST /runs/{run_id}/approve-suggestions` - Apply approved fixes
- `POST /generate-spec` - AI spec generation from schema
- `GET /runs`, `GET /summary` - Run history and project summary

### Key Files
- `orchestrator/api/database_testing.py` - All endpoints
- `orchestrator/api/models_db.py` - `DbConnection`, `DbTestRun`, `DbTestCheck`
- `web/src/app/(dashboard)/database-testing/page.tsx` - Frontend

## Regression Batches

Batch test execution with aggregated reporting and export.

### Capabilities
- Group multiple test runs into batches for regression testing
- Track pass/fail/error counts with auto-refresh
- HTML report generation with detailed results
- Export to HTML/JSON/CSV

### API Endpoints (`orchestrator/api/regression.py`, prefix: `/regression`)
- `GET /batches` - List batches with filtering (status, date range)
- `GET /batches/{batch_id}` - Batch detail with all run results
- `PATCH /batches/{batch_id}/refresh` - Recalculate batch stats
- `GET /batches/{batch_id}/export` - Export as HTML/JSON/CSV
- `DELETE /batches/{batch_id}` - Delete batch and associated runs

## Cron Scheduling

APScheduler-based job scheduling for automated regression and LLM test execution.

### Architecture
- `AsyncIOScheduler` with `SQLAlchemyJobStore` for persistence across restarts
- Jobs coalesced (missed runs merge into one) with max 1 instance per schedule
- 5-minute misfire grace time
- Two scheduling systems: general regression schedules (`orchestrator/api/scheduling.py`) and LLM-specific schedules (within `llm_testing.py`)

### API Endpoints (`orchestrator/api/scheduling.py`, prefix: `/scheduling`)
- `POST/GET/PUT/DELETE /{project_id}/schedules` - Schedule CRUD
- `POST /{project_id}/schedules/{id}/toggle` - Enable/disable
- `POST /{project_id}/schedules/{id}/run-now` - Immediate execution
- `GET /{project_id}/schedules/{id}/executions` - Execution history
- `GET /{project_id}/schedules/{id}/next-runs` - Preview upcoming runs
- `POST /validate-cron` - Validate cron expression

### Key Files
- `orchestrator/services/scheduler.py` - APScheduler singleton with SQLAlchemy job store
- `orchestrator/api/scheduling.py` - REST API for schedule management
- `orchestrator/api/models_db.py` - `CronSchedule`, `ScheduleExecution`

## CI/CD Integrations

GitHub and GitLab pipeline integration for running tests in CI environments.

### API Endpoints
- `orchestrator/api/github_ci.py` (prefix: `/github`) - GitHub Actions workflow generation and webhook handling
- `orchestrator/api/gitlab_ci.py` (prefix: `/gitlab`) - GitLab CI pipeline configuration
- `web/src/app/(dashboard)/ci-cd/page.tsx` - Unified CI/CD configuration page

## Jira Integration

Issue tracking integration for linking test results to Jira tickets.

- `orchestrator/api/jira.py` (prefix: `/jira`) - Jira API endpoints
- Configured per-project in Settings page alongside TestRail

## Exploration → Requirements → RTM

End-to-end pipeline from application discovery to test coverage analysis.

### Exploration (`orchestrator/api/exploration.py`, prefix: `/exploration`)
- Manages AI exploration sessions with browser pool integration
- Per-user concurrency limit (`MAX_EXPLORATIONS_PER_USER`, default: 2)
- Circuit breaker prevents wasting slots on unreachable targets
- Stores `ExplorationSession`, `DiscoveredFlow`, `DiscoveredApiEndpoint` in database

### Requirements (`orchestrator/api/requirements.py`, prefix: `/requirements`)
- CRUD for structured requirements (title, category, priority, acceptance criteria)
- AI generation from exploration data via `requirements_generator.py`
- Auto-generates requirement codes (e.g., `REQ-001`)

### RTM (`orchestrator/api/rtm.py`, prefix: `/rtm`)
- Maps requirements to test specs with confidence scores
- Coverage analysis: covered, partial, uncovered, suggested
- AI-powered gap analysis identifies untested requirements
- Export to CSV/JSON

## Agent Queue System

Redis-based queue for agent execution tasks, solving subprocess I/O issues when spawning Claude CLI from within uvicorn workers.

**Architecture**: API (uvicorn) → Redis Queue → Agent Worker (supervisord). The worker runs as a separate supervisord program with a clean process environment.

### Key Components
- `orchestrator/services/agent_queue.py` - Queue interface (`AgentTask` with status tracking: queued → running → completed/failed)
- `orchestrator/services/agent_worker.py` - Worker process consuming tasks from Redis
- `orchestrator/services/job_queue.py` - Redis-based job queue for distributed test execution across browser worker containers

### API Endpoint
- `GET /api/agents/queue-status` - Current agent queue status and browser slot usage

### Configuration
Requires `REDIS_URL` env var. Falls back gracefully when Redis is unavailable.

## Storage & Archival

Tiered storage system for test run artifacts with configurable retention policies.

### Retention Tiers
- **Hot** (0-30 days): All artifacts kept locally in `runs/<run_id>/`
- **Warm** (30-90 days): Core artifacts (plan.json, validation.json, report.html) moved to MinIO; screenshots and traces deleted
- **Cold** (90+ days): All artifacts deleted, only metadata in database

### Key Components
- `orchestrator/services/storage.py` - Unified local/MinIO storage abstraction (`StorageService`)
- `orchestrator/services/archival.py` - Retention policy engine (`python -m orchestrator.services.archival --dry-run`)
- `orchestrator/api/health.py` - Health endpoints: `GET /health/storage`, `GET /health/backup`, `GET /health/alerts`
- `orchestrator/api/models_db.py` - `RunArtifact` (artifact tracking), `ArchiveJob` (audit log)

### MinIO Setup
S3-compatible object storage for archived artifacts and backups. Buckets: `playwright-backups` (DB backups) and `playwright-artifacts` (archived run artifacts). Console available at port 9001.

## Memory System Architecture

The memory system (`orchestrator/memory/`) provides persistent storage for exploration data and selector patterns:

- **Vector Store** (`vector_store.py`): Semantic similarity search using OpenAI embeddings
- **Graph Store** (`graph_store.py`): Stores relationships between pages, elements, and actions
- **Exploration Store** (`exploration_store.py`): Persists AI exploration discoveries
- **Manager** (`manager.py`): Unified API for all memory operations

Memory is used for:
1. Passing proven selectors to generators (reduces flaky tests)
2. Storing exploration discoveries for requirements generation
3. Building RTM (Requirements Traceability Matrix)

## Test Specification Format

### Standard Spec
```markdown
# Test: Test Name

## Description
What the test does.

## Steps
1. Navigate to https://example.com
2. Click the "Submit" button
3. Enter "value" into the field
4. Verify the success message appears

## Expected Outcome
- Expected results
```

### Template Include System
```markdown
## Steps
1. @include "templates/login.md"
2. Navigate to dashboard
```
Templates in `specs/templates/` can be reused. Selectors from previously automated templates are passed as hints.

### Visual Regression Testing
Add visual verification steps to specs. Generated tests use `expect(page).toHaveScreenshot()`. First run captures baseline; subsequent runs compare.

## Key Files

| Path | Purpose |
|------|---------|
| `orchestrator/cli.py` | CLI entry point |
| `orchestrator/workflows/full_native_pipeline.py` | Main native pipeline orchestrator |
| `orchestrator/workflows/native_*.py` | Native pipeline stages (planner, generator, healer) |
| `orchestrator/workflows/native_api_generator.py` | API test generation (no browser) |
| `orchestrator/workflows/native_api_healer.py` | API test healing (no browser) |
| `orchestrator/workflows/openapi_processor.py` | OpenAPI spec import and parsing |
| `orchestrator/workflows/requirements_generator.py` | AI requirements extraction from exploration data |
| `orchestrator/workflows/rtm_generator.py` | Requirements traceability matrix generation |
| `orchestrator/workflows/app_explorer.py` | AI-powered app exploration |
| `orchestrator/workflows/load_test_generator.py` | K6 script generation from specs |
| `orchestrator/workflows/load_test_runner.py` | K6 execution and metrics parsing |
| `orchestrator/workflows/security_analyzer.py` | AI security analysis |
| `orchestrator/api/main.py` | FastAPI backend entry with all routers |
| `orchestrator/api/api_testing.py` | API testing endpoints (specs, runs, OpenAPI import) |
| `orchestrator/api/load_testing.py` | Load testing endpoints (specs, runs, distributed execution) |
| `orchestrator/api/security_testing.py` | Security testing endpoints |
| `orchestrator/api/llm_testing.py` | LLM evaluation platform (providers, datasets, compare, analytics) |
| `orchestrator/api/database_testing.py` | Database testing (connections, schema analysis, quality checks) |
| `orchestrator/api/regression.py` | Regression batch management and export |
| `orchestrator/api/scheduling.py` | Cron schedule CRUD for automated runs |
| `orchestrator/api/github_ci.py` | GitHub Actions integration |
| `orchestrator/api/gitlab_ci.py` | GitLab CI integration |
| `orchestrator/api/jira.py` | Jira issue tracking integration |
| `orchestrator/api/analytics.py` | Cross-feature analytics endpoints |
| `orchestrator/api/dashboard.py` | Dashboard overview aggregation |
| `orchestrator/api/chat.py` | AI assistant chat endpoints |
| `orchestrator/api/prd.py` | PRD upload and processing endpoints |
| `orchestrator/services/scheduler.py` | APScheduler singleton with SQLAlchemy persistence |
| `orchestrator/workflows/dataset_augmentor.py` | AI dataset augmentation for LLM testing |
| `orchestrator/api/exploration.py` | Exploration session management |
| `orchestrator/api/requirements.py` | Requirements CRUD + AI generation |
| `orchestrator/api/rtm.py` | RTM generation, querying, export |
| `orchestrator/api/auth.py` | Authentication endpoints |
| `orchestrator/api/credentials.py` | Encrypted test credentials storage (Fernet) |
| `orchestrator/api/testrail.py` | TestRail integration API |
| `orchestrator/api/models_db.py` | All database models (SQLModel) |
| `orchestrator/logging_config.py` | Centralized logging with rotation and colored output |
| `orchestrator/utils/agent_runner.py` | Unified agent execution with timeouts and logging |
| `orchestrator/services/browser_pool.py` | Unified browser resource pool |
| `orchestrator/services/load_test_lock.py` | Exclusive load test lock (pauses browser pool) |
| `orchestrator/services/k6_queue.py` | Redis queue for distributed K6 execution |
| `orchestrator/services/agent_queue.py` | Redis agent task queue |
| `orchestrator/services/storage.py` | MinIO/local storage abstraction |
| `orchestrator/services/archival.py` | Artifact retention management |
| `orchestrator/services/security/quick_scanner.py` | Python-native security checks |
| `orchestrator/load_env.py` | Credential loading |
| `orchestrator/utils/json_utils.py` | Robust JSON extraction from AI output |
| `.claude/agents/*.md` | Agent tool permissions and prompts |
| `web/src/app/(dashboard)/` | All frontend pages (Next.js App Router) |

## Project Management

Multi-tenant project isolation for specs, runs, and batches.

- `GET/POST /projects`, `GET/PUT/DELETE /projects/{id}` - CRUD endpoints
- Each project has isolated specs, runs, and batches
- Default project auto-created on startup; legacy data belongs to default project
- Frontend stores current project in localStorage

## Authentication System

Multi-user authentication with role-based access control.

### Auth Endpoints (`orchestrator/api/auth.py`)
- `POST /auth/register` - User registration (rate limited, can be disabled via `ALLOW_REGISTRATION=false`)
- `POST /auth/login` - Login with email/password (rate limited, account lockout after failed attempts)
- `POST /auth/refresh` - Refresh access token (token rotation enabled)
- `POST /auth/logout` - Revoke refresh token
- `GET /auth/me` - Current user info

### Security Features
- **Password hashing**: bcrypt with secure defaults
- **JWT tokens**: Short-lived access tokens (15min) + long-lived refresh tokens (7 days)
- **Rate limiting**: Login/register endpoints protected against brute force
- **Account lockout**: Automatic lockout after 5 failed login attempts
- **Token rotation**: Refresh tokens are single-use and rotated on each refresh

### User Roles
- **Regular user**: Access to assigned projects only
- **Superuser**: Full platform access, can manage users via `/admin/users`

Users are assigned to projects with roles (`owner`, `admin`, `member`, `viewer`) via `ProjectMember` model.

## Live Browser View (VNC - Admin-Only)

Real-time browser viewing during test execution via VNC streaming. Superuser-only. Uses Xvfb (virtual display) + x11vnc + websockify, managed by supervisord in Docker.

**Config**: `VNC_ENABLED=true`, `DISPLAY=:99`. When enabled, parallel execution is limited to 1 browser.

**Frontend**: `LiveBrowserView` component (noVNC) connects to `ws://{host}:6080/websockify` in view-only mode.

**Docker**: supervisord manages Xvfb (1920x1080x24), Fluxbox, x11vnc, websockify (port 6080), and uvicorn. Requires `shm_size: 2GB` minimum.

## Browser Parallelism & Scaling

### Unified Browser Pool

All browser operations (test runs, explorations, agents, PRD processing) are managed through `BrowserResourcePool` singleton with FIFO queuing and operation tracking.

**Config**: `MAX_BROWSER_INSTANCES=5` (hard limit), `BROWSER_SLOT_TIMEOUT=3600` (max wait)

**API Endpoints**: `GET /api/browser-pool/status`, `GET /api/browser-pool/recent`, `POST /api/browser-pool/cleanup`

### Scaling Options

1. **Native Parallelism** (default): Playwright built-in workers within the browser pool limit
2. **Docker Isolation** (production): Isolated browser worker containers via `docker-compose.prod.yml --profile workers`. See `docker/browser-worker/Dockerfile`.
3. **Kubernetes** (enterprise): Auto-scaling with HPA. See `k8s/README.md`.

Key files: `orchestrator/services/browser_pool.py`, `orchestrator/services/job_queue.py`

## Development Workflow

### Modifying Pipeline Behavior
1. Update workflow in `orchestrator/workflows/[stage].py`
2. Modify agent prompt in `.claude/agents/test-[stage].md`
3. Update schema in `schemas/[stage].schema.json` if JSON structure changes
4. Test: `python orchestrator/cli.py specs/test-example.md`

### Adding Web Dashboard Features
1. Backend: Add endpoint in `orchestrator/api/main.py` or sub-router
2. Frontend: Create page in `web/src/app/(dashboard)/[route]/page.tsx`
3. Test: `make dev` → http://localhost:3000

### Running Python Tests
```bash
cd orchestrator
python -m pytest test_e2e.py                          # End-to-end pipeline test
python -m pytest tests/test_09_memory_system.py -v    # Specific test suite
python -m pytest tests/ -v                            # All unit tests
```
Pytest config in `orchestrator/pytest.ini` with `asyncio_mode = auto`.

### Frontend Stack (`web/`)
Next.js 16 (App Router), React 19, Tailwind CSS v4, Radix UI primitives, Monaco Editor (code editing), Recharts (charts), noVNC (live browser view), react-syntax-highlighter (readonly code). All pages under `web/src/app/(dashboard)/`.

**Dashboard pages**: `dashboard`, `specs`, `runs`, `regression`, `exploration`, `requirements`, `rtm`, `coverage`, `api-testing`, `load-testing`, `security-testing`, `database-testing`, `llm-testing`, `prd`, `schedules`, `ci-cd`, `analytics`, `memory`, `agents`, `assistant`, `templates`, `projects`, `settings`.

## Common Issues

| Symptom | Solution |
|---------|----------|
| "ANTHROPIC_AUTH_TOKEN not set" | Check `.env` file, run `make check-env` |
| "Database connection refused" | `docker-compose up -d db` or use SQLite (default for dev) |
| SDK cleanup error | Already handled - stages run as subprocesses |
| Generated test selector fails | Native healer auto-fixes; use `--hybrid` for complex cases |
| "No target URL found in spec" | Spec must contain URL (e.g., "Navigate to https://...") |
| Test timeout on complex pages | Use `--hybrid` or increase exploration depth |
| Exploration stops early | Check `max_interactions` config (default: 50) |
| "Account locked" on login | Wait 15 minutes or clear lockout in database |
| "Invalid token" errors | Refresh token expired; re-login required |
| Registration disabled | Set `ALLOW_REGISTRATION=true` in `.env` |
| ZAP not reachable | Start with: `docker compose --profile security up -d zap` |
| Nuclei not found | Install nuclei binary or use Docker security profile |
| `make prod-dev` backend won't start | Check `docker logs` for migration errors; `_run_migrations()` in `db.py` uses PostgreSQL syntax — SQLite booleans (`DEFAULT 0`) fail in PostgreSQL (`DEFAULT FALSE`) |
| Backend crash loop on startup | Usually a migration issue — check `alembic_version` table and `db.py:_run_migrations()` legacy migrations |
