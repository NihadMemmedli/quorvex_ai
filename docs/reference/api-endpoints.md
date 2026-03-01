# API Endpoints

Complete endpoint catalog for the Quorvex AI REST API. For conventions (authentication, errors, pagination, rate limiting), see [API Overview](api-overview.md).

## Authentication

Prefix: `/auth` | Source: `orchestrator/api/auth.py`

| Method | Path | Description | Auth Required | Rate Limit |
|--------|------|-------------|---------------|------------|
| POST | `/auth/register` | Register a new user | No | 3/min |
| POST | `/auth/login` | Login with email and password | No | 10/min |
| POST | `/auth/refresh` | Refresh access token using refresh token | No | 30/min |
| POST | `/auth/logout` | Revoke a specific refresh token | Yes | -- |
| POST | `/auth/logout-all` | Revoke all refresh tokens for the user | Yes | -- |
| GET | `/auth/me` | Get current authenticated user info | Yes | -- |

## Users (Admin)

Prefix: `/users` | Source: `orchestrator/api/users.py`

All endpoints require superuser authentication.

| Method | Path | Description | Auth Required |
|--------|------|-------------|---------------|
| GET | `/users` | List all users (paginated) | Superuser |
| POST | `/users` | Create a user | Superuser |
| GET | `/users/{id}` | Get user by ID | Superuser |
| PUT | `/users/{id}` | Update user (name, active, superuser) | Superuser |
| DELETE | `/users/{id}` | Delete user and all memberships | Superuser |
| GET | `/users/{id}/projects` | List projects a user belongs to | Superuser |
| POST | `/users/{id}/projects/{project_id}` | Assign user to project with role | Superuser |
| DELETE | `/users/{id}/projects/{project_id}` | Remove user from project | Superuser |

## Projects

Prefix: `/projects` | Source: `orchestrator/api/projects.py`

| Method | Path | Description | Auth Required |
|--------|------|-------------|---------------|
| GET | `/projects` | List all projects | Optional |
| POST | `/projects` | Create a project | Optional |
| GET | `/projects/{id}` | Get project details with counts | Optional |
| PUT | `/projects/{id}` | Update project name, URL, or description | Optional |
| DELETE | `/projects/{id}` | Delete project (not default) | Optional |
| POST | `/projects/{id}/assign-spec` | Assign a spec to this project | Optional |
| POST | `/projects/{id}/bulk-assign-specs` | Assign multiple specs at once | Optional |
| GET | `/projects/{id}/members` | List project members | Optional |
| POST | `/projects/{id}/members` | Add a member with role | Optional |
| PUT | `/projects/{id}/members/{user_id}` | Update member role | Optional |
| DELETE | `/projects/{id}/members/{user_id}` | Remove member | Optional |
| GET | `/projects/{id}/my-role` | Get current user's role in project | Yes |
| GET | `/projects/{id}/credentials` | List credentials (masked values) | Optional |
| POST | `/projects/{id}/credentials` | Create or update a credential | Optional |
| DELETE | `/projects/{id}/credentials/{key}` | Delete a credential | Optional |

## Specs

Source: `orchestrator/api/main.py` (registered directly on app)

| Method | Path | Description | Auth Required |
|--------|------|-------------|---------------|
| GET | `/specs` | Paginated spec list (metadata only, no content) | Optional |
| GET | `/specs/list` | Lightweight spec list with automation status | Optional |
| GET | `/specs/folders` | Folder tree with automated spec counts | Optional |
| GET | `/specs/automated` | Paginated automated specs with last-run info | Optional |
| GET | `/specs/{name}` | Get spec content and metadata | Optional |
| POST | `/specs` | Create a new spec | Optional |
| PUT | `/specs/{name}` | Update spec content | Optional |
| DELETE | `/specs/{name}` | Delete spec and optionally generated test | Optional |
| DELETE | `/specs/folder/{path}` | Delete a folder and all specs inside | Optional |
| POST | `/specs/move` | Move a spec or folder to a new location | Optional |
| POST | `/specs/register-folder` | Register all specs in a folder to a project | Optional |
| GET | `/specs/{name}/generated-code` | Get the generated TypeScript test code | Optional |
| PUT | `/specs/{name}/generated-code` | Update generated test code | Optional |
| GET | `/specs/{name}/info` | Get spec type, test count, categories | Optional |
| POST | `/specs/split` | Split a multi-test PRD spec into individual specs | Optional |

## Spec Metadata

Source: `orchestrator/api/main.py`

| Method | Path | Description | Auth Required |
|--------|------|-------------|---------------|
| GET | `/spec-metadata` | Get all spec metadata (dict keyed by name) | Optional |
| GET | `/spec-metadata/{name}` | Get metadata for one spec | Optional |
| PUT | `/spec-metadata/{name}` | Update tags, description, author, project | Optional |

## Runs

Source: `orchestrator/api/main.py`

| Method | Path | Description | Auth Required |
|--------|------|-------------|---------------|
| GET | `/runs` | Paginated list of test runs | Optional |
| GET | `/runs/{id}` | Full run details with plan, validation, artifacts | Optional |
| POST | `/runs` | Create and start a single test run | Optional |
| POST | `/runs/{id}/stop` | Stop a running or queued test | Optional |
| POST | `/runs/{id}/progress` | Update run stage progress (called by CLI) | Optional |
| GET | `/runs/{id}/log/stream` | Stream execution log via SSE | Optional |
| POST | `/runs/bulk` | Create a regression batch of runs | Optional |

## Regression Batches

Prefix: `/regression` | Source: `orchestrator/api/regression.py`

| Method | Path | Description | Auth Required |
|--------|------|-------------|---------------|
| GET | `/regression/batches` | List batches (paginated) | Optional |
| GET | `/regression/batches/{id}` | Get batch detail with all runs | Optional |
| PATCH | `/regression/batches/{id}/refresh` | Recalculate batch statistics | Optional |
| GET | `/regression/batches/{id}/export` | Export batch as JSON or HTML report | Optional |
| DELETE | `/regression/batches/{id}` | Delete batch and all associated runs | Optional |
| GET | `/regression/debug/test-counts` | Debug: show test counts across all batches | Optional |
| GET | `/regression/debug/batch/{id}/test-counts` | Debug: show test counts for one batch | Optional |

## Exploration

Prefix: `/exploration` | Source: `orchestrator/api/exploration.py`

| Method | Path | Description | Auth Required | Rate Limit |
|--------|------|-------------|---------------|------------|
| GET | `/exploration/health` | Check exploration service health | Optional | -- |
| POST | `/exploration/start` | Start an AI exploration session | Optional | 5/min |
| GET | `/exploration` | List exploration sessions | Optional | -- |
| GET | `/exploration/{id}` | Get exploration session details | Optional | -- |
| GET | `/exploration/{id}/results` | Get exploration results (pages, flows, APIs) | Optional | -- |
| POST | `/exploration/{id}/stop` | Stop a running exploration | Optional | 10/min |
| GET | `/exploration/{id}/flows` | Get discovered user flows | Optional | -- |
| GET | `/exploration/{id}/apis` | Get discovered API endpoints | Optional | -- |
| GET | `/exploration/queue/status` | Get exploration queue status | Optional | -- |

## Requirements

Prefix: `/requirements` | Source: `orchestrator/api/requirements.py`

| Method | Path | Description | Auth Required |
|--------|------|-------------|---------------|
| GET | `/requirements` | List requirements (paginated, filterable) | Optional |
| POST | `/requirements` | Create a requirement manually | Optional |
| GET | `/requirements/{id}` | Get requirement detail | Optional |
| PUT | `/requirements/{id}` | Update a requirement | Optional |
| DELETE | `/requirements/{id}` | Delete a requirement | Optional |
| POST | `/requirements/generate` | Generate requirements from exploration session | Optional |
| GET | `/requirements/duplicates` | Find duplicate requirements | Optional |
| POST | `/requirements/check-duplicate` | Check if a requirement is a duplicate | Optional |
| POST | `/requirements/merge` | Merge duplicate requirements | Optional |
| GET | `/requirements/categories/list` | List distinct categories | Optional |
| GET | `/requirements/stats` | Requirement statistics | Optional |
| GET | `/requirements/health` | Requirements service health | Optional |
| GET | `/requirements/{id}/spec-status` | Check if spec exists for this requirement | Optional |
| POST | `/requirements/{id}/generate-spec` | Generate a test spec from a requirement | Optional |

## RTM (Requirements Traceability Matrix)

Prefix: `/rtm` | Source: `orchestrator/api/rtm.py`

| Method | Path | Description | Auth Required |
|--------|------|-------------|---------------|
| GET | `/rtm` | Get full RTM (requirements mapped to tests) | Optional |
| POST | `/rtm/generate` | Generate/rebuild the RTM | Optional |
| GET | `/rtm/coverage` | Get test coverage summary | Optional |
| GET | `/rtm/gaps` | Find requirements with no test coverage | Optional |
| GET | `/rtm/export/{format}` | Export RTM as markdown, csv, or html | Optional |
| POST | `/rtm/snapshot` | Save a point-in-time RTM snapshot | Optional |
| GET | `/rtm/snapshots` | List saved RTM snapshots | Optional |
| GET | `/rtm/requirement/{id}/tests` | Get tests linked to a requirement | Optional |
| GET | `/rtm/test/{name}/requirements` | Get requirements linked to a test | Optional |
| POST | `/rtm/entry` | Manually link a requirement to a test | Optional |
| DELETE | `/rtm/entry/{id}` | Remove a requirement-test link | Optional |

## Memory

Prefix: `/api/memory` | Source: `orchestrator/api/memory.py`

| Method | Path | Description | Auth Required |
|--------|------|-------------|---------------|
| GET | `/api/memory/patterns` | Get stored selector patterns | Optional |
| POST | `/api/memory/similar` | Find similar patterns via vector search | Optional |
| GET | `/api/memory/selectors` | Get selector recommendations | Optional |
| GET | `/api/memory/coverage/summary` | Test coverage summary from memory | Optional |
| GET | `/api/memory/coverage/gaps` | Coverage gaps | Optional |
| GET | `/api/memory/coverage/suggestions` | AI-suggested tests to improve coverage | Optional |
| GET | `/api/memory/graph/stats` | Graph store statistics | Optional |
| GET | `/api/memory/graph/pages` | Pages in the knowledge graph | Optional |
| GET | `/api/memory/graph/flows` | User flows in the knowledge graph | Optional |
| GET | `/api/memory/stats` | Overall memory system statistics | Optional |
| GET | `/api/memory/projects` | Memory data grouped by project | Optional |

## PRD Processing

Prefix: `/api/prd` | Source: `orchestrator/api/prd.py`

| Method | Path | Description | Auth Required |
|--------|------|-------------|---------------|
| POST | `/api/prd/upload` | Upload a PRD document (PDF, multipart/form-data) | Optional |
| GET | `/api/prd/projects` | List uploaded PRD projects | Optional |
| DELETE | `/api/prd/{project_id}` | Delete a PRD project | Optional |
| GET | `/api/prd/{project_id}/features` | List features extracted from PRD | Optional |
| POST | `/api/prd/{project_id}/generate-plan` | Generate test plan for a feature | Optional |
| GET | `/api/prd/generation/{id}` | Get generation job status | Optional |
| POST | `/api/prd/generation/{id}/stop` | Stop a running generation | Optional |
| GET | `/api/prd/generation/{id}/log/stream` | Stream generation log (SSE) | Optional |
| GET | `/api/prd/{project_id}/generations` | List generation history | Optional |
| POST | `/api/prd/generate-test` | Generate a test from a plan | Optional |
| POST | `/api/prd/heal-test` | Heal a failing test | Optional |
| POST | `/api/prd/run-test` | Run a generated test | Optional |
| GET | `/api/prd/queue/status` | PRD processing queue status | Optional |

## Agents

Source: `orchestrator/api/main.py`

| Method | Path | Description | Auth Required |
|--------|------|-------------|---------------|
| POST | `/api/agents/runs` | Run an autonomous agent (exploratory, writer, synthesis) | Optional |
| GET | `/api/agents/runs` | List agent runs | Optional |
| GET | `/api/agents/runs/{id}` | Get agent run details | Optional |
| POST | `/api/agents/exploratory` | Run enhanced exploratory testing | Optional |
| POST | `/api/agents/exploratory/{run_id}/synthesize` | Generate specs from exploration | Optional |
| GET | `/api/agents/exploratory/{run_id}/specs` | Get generated specs | Optional |
| GET | `/api/agents/exploratory/{run_id}/flows/{flow_id}` | Get flow details | Optional |
| POST | `/api/agents/exploratory/{run_id}/analyze-prerequisites` | Analyze flow prerequisites | Optional |
| POST | `/api/agents/exploratory/{run_id}/flows/{flow_id}/spec` | Generate spec for one flow | Optional |
| POST | `/api/agents/exploratory/{run_id}/flows/{flow_id}/generate` | Generate validated test via native pipeline | Optional |

Agent types: `exploratory`, `writer`, `spec-synthesis`.

## Auth Sessions

Source: `orchestrator/api/main.py`

| Method | Path | Description | Auth Required |
|--------|------|-------------|---------------|
| GET | `/api/agents/sessions` | List saved authentication sessions | Optional |
| POST | `/api/agents/sessions/{session_id}` | Save an authentication session | Optional |
| DELETE | `/api/agents/sessions/{session_id}` | Delete a saved session | Optional |

## Dashboard

Source: `orchestrator/api/dashboard.py`

| Method | Path | Description | Auth Required |
|--------|------|-------------|---------------|
| GET | `/dashboard` | Comprehensive test analytics | Optional |

Query parameters: `period` (default `30d`), `project_id`.

## Settings

Source: `orchestrator/api/settings.py`

| Method | Path | Description | Auth Required |
|--------|------|-------------|---------------|
| GET | `/settings` | Get current settings (API key masked) | Optional |
| POST | `/settings` | Update settings (writes to .env file) | Optional |

## Execution Settings

Source: `orchestrator/api/main.py`

| Method | Path | Description | Auth Required |
|--------|------|-------------|---------------|
| GET | `/execution-settings` | Get parallelism, headless mode, memory, DB type | Optional |
| PUT | `/execution-settings` | Update execution settings | Optional |

## Queue Management

Source: `orchestrator/api/main.py`

| Method | Path | Description | Auth Required |
|--------|------|-------------|---------------|
| GET | `/queue-status` | Running, queued counts and parallelism limit | Optional |
| POST | `/queue/clear` | Clear stuck queue entries | Optional |

## Browser Pool

Source: `orchestrator/api/main.py`

| Method | Path | Description | Auth Required |
|--------|------|-------------|---------------|
| GET | `/api/browser-pool/status` | Current pool utilization and slot details | Optional |
| GET | `/api/browser-pool/recent` | Recently completed browser operations | Optional |
| POST | `/api/browser-pool/cleanup` | Clean up stale browser slots | Optional |

## Resource Management

Source: `orchestrator/api/main.py`

| Method | Path | Description | Auth Required |
|--------|------|-------------|---------------|
| GET | `/api/resources/status` | **DEPRECATED** -- use `/api/browser-pool/status` | Optional |
| GET | `/api/agents/queue-status` | Agent queue status and browser slot usage | Optional |
| POST | `/api/resources/cleanup` | Force cleanup of stale resources | Optional |

## Health

Prefix: `/health` | Source: `orchestrator/api/health.py`

| Method | Path | Description | Auth Required |
|--------|------|-------------|---------------|
| GET | `/health` | Basic health check (returns `{"status": "ok"}`) | No |
| GET | `/health/storage` | Comprehensive storage health (DB, MinIO, local) | No |
| GET | `/health/backup` | Backup status and recent backups | No |
| GET | `/health/alerts` | Active health alerts | No |
| GET | `/health/archival/stats` | Archival system statistics | No |
| POST | `/health/storage/record` | Record a storage metric | No |

### Health Alert Thresholds

| Check | Warning | Critical |
|-------|---------|----------|
| Runs directory size | > 5 GB | > 10 GB |
| Last backup age | > 36 hours | > 48 hours |
| PostgreSQL DB size | > 5 GB | > 10 GB |

## Backup

Source: `orchestrator/api/main.py`

| Method | Path | Description | Auth Required |
|--------|------|-------------|---------------|
| POST | `/api/backup` | Trigger a manual database backup | Optional |
| GET | `/api/backup/status` | List recent backups and retention info | Optional |

## API Testing

Prefix: `/api-testing` | Source: `orchestrator/api/api_testing.py`

| Method | Path | Description | Auth Required |
|--------|------|-------------|---------------|
| POST | `/api-testing/specs` | Create API test spec | Optional |
| GET | `/api-testing/specs` | List API test specs | Optional |
| GET | `/api-testing/specs/{folder}` | Get API test spec details | Optional |
| PUT | `/api-testing/specs/{folder}` | Update API test spec | Optional |
| DELETE | `/api-testing/specs/{folder}` | Delete API test spec | Optional |
| POST | `/api-testing/import-openapi` | Import OpenAPI/Swagger spec | Optional |
| POST | `/api-testing/specs/{folder}/run` | Run API test (background job) | Optional |
| GET | `/api-testing/runs` | List API test run history | Optional |
| GET | `/api-testing/runs/{run_id}` | Get run details with logs | Optional |

## Load Testing

Prefix: `/load-testing` | Source: `orchestrator/api/load_testing.py`

| Method | Path | Description | Auth Required |
|--------|------|-------------|---------------|
| POST | `/load-testing/specs` | Create load test spec | Optional |
| GET | `/load-testing/specs` | List load test specs | Optional |
| GET | `/load-testing/specs/{folder}` | Get load test spec details | Optional |
| PUT | `/load-testing/specs/{folder}` | Update load test spec | Optional |
| DELETE | `/load-testing/specs/{folder}` | Delete load test spec | Optional |
| POST | `/load-testing/specs/{folder}/generate` | Generate K6 script from spec | Optional |
| POST | `/load-testing/specs/{folder}/run` | Execute load test (background job) | Optional |
| GET | `/load-testing/runs` | List load test runs | Optional |
| GET | `/load-testing/runs/{run_id}/status` | Real-time status with metrics | Optional |
| POST | `/load-testing/runs/{run_id}/stop` | Cancel running test | Optional |
| GET | `/load-testing/runs/compare` | Compare multiple runs with overlay charts | Optional |
| GET | `/load-testing/system-limits` | Current resource caps and worker status | Optional |

## Security Testing

Prefix: `/security-testing` | Source: `orchestrator/api/security_testing.py`

| Method | Path | Description | Auth Required |
|--------|------|-------------|---------------|
| POST | `/security-testing/specs` | Create security test spec | Optional |
| GET | `/security-testing/specs` | List security test specs | Optional |
| POST | `/security-testing/scan/quick` | Run quick scan (background) | Optional |
| POST | `/security-testing/scan/nuclei` | Run Nuclei scan (background) | Optional |
| POST | `/security-testing/scan/zap` | Run ZAP DAST scan (background) | Optional |
| POST | `/security-testing/scan/full` | Run all tiers sequentially | Optional |
| GET | `/security-testing/jobs/{job_id}` | Poll scan job status | Optional |
| GET | `/security-testing/runs` | List scan history | Optional |
| GET | `/security-testing/runs/{run_id}` | Scan details with findings | Optional |
| GET | `/security-testing/runs/{run_id}/findings` | Findings with severity filter | Optional |
| PATCH | `/security-testing/findings/{id}/status` | Update finding status | Optional |
| GET | `/security-testing/findings/summary` | Aggregated severity counts | Optional |
| POST | `/security-testing/analyze/{run_id}` | AI remediation analysis | Optional |
| POST | `/security-testing/generate-spec` | AI generates spec from exploration | Optional |

## LLM Testing

Prefix: `/llm-testing` | Source: `orchestrator/api/llm_testing.py`

### Providers

| Method | Path | Description | Auth Required |
|--------|------|-------------|---------------|
| POST | `/llm-testing/providers` | Register LLM provider | Optional |
| GET | `/llm-testing/providers` | List providers | Optional |
| PUT | `/llm-testing/providers/{id}` | Update provider | Optional |
| DELETE | `/llm-testing/providers/{id}` | Delete provider | Optional |

### Specs

| Method | Path | Description | Auth Required |
|--------|------|-------------|---------------|
| POST | `/llm-testing/specs` | Create LLM test spec | Optional |
| GET | `/llm-testing/specs` | List LLM test specs | Optional |
| PUT | `/llm-testing/specs/{name}` | Update spec | Optional |
| DELETE | `/llm-testing/specs/{name}` | Delete spec | Optional |
| GET | `/llm-testing/specs/{name}/versions` | List spec versions | Optional |
| POST | `/llm-testing/specs/{name}/suggest-improvements` | AI spec improvements | Optional |

### Execution

| Method | Path | Description | Auth Required |
|--------|------|-------------|---------------|
| POST | `/llm-testing/run` | Run suite against a provider (background) | Optional |
| POST | `/llm-testing/compare` | Compare multiple providers | Optional |
| POST | `/llm-testing/bulk-run` | Batch dataset operations | Optional |
| POST | `/llm-testing/bulk-compare` | Batch comparison | Optional |
| POST | `/llm-testing/generate-suite` | AI-generated test suite | Optional |
| POST | `/llm-testing/prompt-iterations` | A/B prompt testing | Optional |

### Datasets

| Method | Path | Description | Auth Required |
|--------|------|-------------|---------------|
| POST | `/llm-testing/datasets` | Create dataset | Optional |
| GET | `/llm-testing/datasets` | List datasets | Optional |
| PUT | `/llm-testing/datasets/{id}` | Update dataset | Optional |
| DELETE | `/llm-testing/datasets/{id}` | Delete dataset | Optional |
| POST | `/llm-testing/datasets/{id}/augment` | AI dataset augmentation | Optional |

### Schedules

| Method | Path | Description | Auth Required |
|--------|------|-------------|---------------|
| POST | `/llm-testing/schedules` | Create schedule | Optional |
| GET | `/llm-testing/schedules` | List schedules | Optional |
| PUT | `/llm-testing/schedules/{id}` | Update schedule | Optional |
| DELETE | `/llm-testing/schedules/{id}` | Delete schedule | Optional |

### Analytics

| Method | Path | Description | Auth Required |
|--------|------|-------------|---------------|
| GET | `/llm-testing/analytics/overview` | Overview stats | Optional |
| GET | `/llm-testing/analytics/trends` | Performance trends | Optional |
| GET | `/llm-testing/analytics/latency` | Latency distribution | Optional |
| GET | `/llm-testing/analytics/cost` | Cost tracking | Optional |
| GET | `/llm-testing/analytics/regressions` | Regression detection | Optional |
| GET | `/llm-testing/analytics/golden` | Golden dashboard | Optional |

## Database Testing

Prefix: `/database-testing` | Source: `orchestrator/api/database_testing.py`

| Method | Path | Description | Auth Required |
|--------|------|-------------|---------------|
| POST | `/database-testing/connections` | Create connection profile | Optional |
| GET | `/database-testing/connections` | List connections | Optional |
| PUT | `/database-testing/connections/{id}` | Update connection | Optional |
| DELETE | `/database-testing/connections/{id}` | Delete connection | Optional |
| POST | `/database-testing/connections/{id}/test` | Test connection | Optional |
| POST | `/database-testing/analyze/{conn_id}` | Schema analysis (background) | Optional |
| POST | `/database-testing/run/{conn_id}` | Run data quality checks | Optional |
| POST | `/database-testing/run-full/{conn_id}` | Full pipeline (analyze + generate + run) | Optional |
| POST | `/database-testing/suggest/{run_id}` | AI suggestions for failures | Optional |
| POST | `/database-testing/runs/{run_id}/approve-suggestions` | Apply approved fixes | Optional |
| POST | `/database-testing/generate-spec` | AI spec generation from schema | Optional |
| GET | `/database-testing/runs` | List run history | Optional |
| GET | `/database-testing/summary` | Project summary | Optional |

## Scheduling

Prefix: `/scheduling` | Source: `orchestrator/api/scheduling.py`

| Method | Path | Description | Auth Required |
|--------|------|-------------|---------------|
| POST | `/scheduling/{project_id}/schedules` | Create schedule | Optional |
| GET | `/scheduling/{project_id}/schedules` | List schedules | Optional |
| PUT | `/scheduling/{project_id}/schedules/{id}` | Update schedule | Optional |
| DELETE | `/scheduling/{project_id}/schedules/{id}` | Delete schedule | Optional |
| POST | `/scheduling/{project_id}/schedules/{id}/toggle` | Enable/disable | Optional |
| POST | `/scheduling/{project_id}/schedules/{id}/run-now` | Immediate execution | Optional |
| GET | `/scheduling/{project_id}/schedules/{id}/executions` | Execution history | Optional |
| GET | `/scheduling/{project_id}/schedules/{id}/next-runs` | Preview upcoming runs | Optional |
| POST | `/scheduling/validate-cron` | Validate cron expression | Optional |

## TestRail Integration

Prefix: `/testrail` | Source: `orchestrator/api/testrail.py`

All endpoints scoped to a project via `{project_id}` path parameter.

| Method | Path | Description | Auth Required |
|--------|------|-------------|---------------|
| GET | `/testrail/{project_id}/config` | Get TestRail config (API key masked) | Optional |
| POST | `/testrail/{project_id}/config` | Save TestRail credentials | Optional |
| DELETE | `/testrail/{project_id}/config` | Remove TestRail config | Optional |
| POST | `/testrail/{project_id}/test-connection` | Validate TestRail credentials | Optional |
| GET | `/testrail/{project_id}/remote-projects` | List TestRail projects | Optional |
| GET | `/testrail/{project_id}/remote-suites/{tr_project_id}` | List suites in a TestRail project | Optional |
| POST | `/testrail/{project_id}/push-cases` | Push specs as test cases to TestRail | Optional |
| GET | `/testrail/{project_id}/mappings` | View local-to-TestRail case mappings | Optional |
| DELETE | `/testrail/{project_id}/mappings/{mapping_id}` | Delete a case mapping | Optional |
| GET | `/testrail/{project_id}/sync-preview/{batch_id}` | Preview batch result sync | Optional |
| POST | `/testrail/{project_id}/sync-results` | Push batch results as a TestRail run | Optional |

## CI/CD Integration

### GitHub

Prefix: `/github` | Source: `orchestrator/api/github_ci.py`

GitHub Actions workflow generation and webhook handling.

### GitLab

Prefix: `/gitlab` | Source: `orchestrator/api/gitlab_ci.py`

GitLab CI pipeline configuration.

## Jira Integration

Prefix: `/jira` | Source: `orchestrator/api/jira.py`

Issue tracking integration for linking test results to Jira tickets.

## Analytics

Prefix: `/analytics` | Source: `orchestrator/api/analytics.py`

Cross-feature analytics endpoints for aggregated reporting.

## Chat / AI Assistant

Prefix: `/chat` | Source: `orchestrator/api/chat.py`

AI assistant chat endpoints with conversation persistence and tool invocation.

## Import / Export

Source: `orchestrator/api/main.py`

| Method | Path | Description | Auth Required |
|--------|------|-------------|---------------|
| POST | `/import/testrail` | Import test cases from TestRail CSV | Optional |
| POST | `/export/testrail` | Export specs as TestRail-compatible XML or CSV | Optional |

## Static Files

| Path Pattern | Description |
|-------------|-------------|
| `/artifacts/{run_id}/...` | Screenshots, videos, and Playwright HTML reports from test runs |

## Debug

Source: `orchestrator/api/main.py`

| Method | Path | Description | Auth Required |
|--------|------|-------------|---------------|
| GET | `/debug-imports` | Check sys.path and test import resolution | No |

Not intended for production use.

## Related

- [API Overview](api-overview.md)
- [Environment Variables](environment-variables.md)
