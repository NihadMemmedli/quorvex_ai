# API Endpoints

![API testing dashboard for API endpoint workflow context](../assets/ui/api-testing.png)

<p class="caption">API testing dashboard for API endpoint workflow context.</p>


Endpoint catalog for the Quorvex AI REST API. For conventions (authentication, errors, pagination, rate limiting), see [API Overview](api-overview.md).

## Authentication

Prefix: `/auth` | Source: `orchestrator/api/auth.py`

| Method | Path | Description | Auth Required | Rate Limit |
|--------|------|-------------|---------------|------------|
| POST | `/auth/register` | Register a new user | No | 3/min |
| POST | `/auth/login` | Login with email and password | No | 10/min |
| POST | `/auth/refresh` | Refresh access token using refresh token | No | 30/min |
| POST | `/auth/logout` | Revoke a specific refresh token | No | -- |
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
| POST | `/specs/rename` | Rename a spec or folder | Optional |
| POST | `/specs/create-folder` | Create a spec folder | Optional |
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
| DELETE | `/runs/{id}` | Delete a run and associated artifacts | Optional |
| POST | `/runs` | Create and start a single test run | Optional |
| POST | `/runs/{id}/stop` | Stop a running or queued test | Optional |
| POST | `/runs/{id}/progress` | Update run stage progress (called by CLI) | Optional |
| POST | `/runs/{id}/agentic-summary` | Generate or refresh an agentic run summary | Optional |
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
| PATCH | `/regression/batches/{id}` | Update batch metadata | Optional |
| POST | `/regression/batches/{id}/cancel` | Cancel a running regression batch | Optional |
| POST | `/regression/batches/{id}/rerun-failed` | Rerun failed tests in a batch | Optional |
| DELETE | `/regression/batches/{id}` | Delete batch and all associated runs | Optional |
| GET | `/regression/batches/trend` | Batch execution trend data | Optional |
| GET | `/regression/batches/{id}/error-summary` | Error summary for one batch | Optional |
| POST | `/regression/batches/compare` | Compare two regression batches | Optional |
| GET | `/regression/spec-history` | Historical status for specs | Optional |
| GET | `/regression/flaky-tests` | List detected flaky tests | Optional |
| GET | `/regression/debug/test-counts` | Debug: show test counts across all batches | Optional |
| GET | `/regression/debug/batch/{id}/test-counts` | Debug: show test counts for one batch | Optional |

## Exploration

Prefix: `/exploration` | Source: `orchestrator/api/exploration.py`

| Method | Path | Description | Auth Required | Rate Limit |
|--------|------|-------------|---------------|------------|
| GET | `/exploration/health` | Check exploration service health | Optional | -- |
| POST | `/exploration/start` | Start an AI exploration session | Optional | 5/min |
| GET | `/exploration/spec-gen-jobs` | List exploration spec-generation jobs | Optional | -- |
| GET | `/exploration/spec-gen-jobs/{id}` | Get exploration spec-generation job status | Optional | -- |
| GET | `/exploration` | List exploration sessions | Optional | -- |
| GET | `/exploration/{id}` | Get exploration session details | Optional | -- |
| GET | `/exploration/{id}/artifacts` | List artifacts for an exploration session | Optional | -- |
| GET | `/exploration/{id}/details` | Get full exploration details | Optional | -- |
| GET | `/exploration/{id}/results` | Get exploration results (pages, flows, APIs) | Optional | -- |
| POST | `/exploration/{id}/stop` | Stop a running exploration | Optional | 10/min |
| GET | `/exploration/{id}/flows` | Get discovered user flows | Optional | -- |
| PUT | `/exploration/{id}/flows/{flow_id}` | Update a discovered flow | Optional | -- |
| DELETE | `/exploration/{id}/flows/{flow_id}` | Delete a discovered flow | Optional | -- |
| GET | `/exploration/{id}/apis` | Get discovered API endpoints | Optional | -- |
| PUT | `/exploration/{id}/apis/{endpoint_id}` | Update a discovered API endpoint | Optional | -- |
| DELETE | `/exploration/{id}/apis/{endpoint_id}` | Delete a discovered API endpoint | Optional | -- |
| GET | `/exploration/{id}/issues` | Get issues discovered during exploration | Optional | -- |
| POST | `/exploration/{id}/generate-api-specs` | Generate API specs from exploration results | Optional | -- |
| POST | `/exploration/{id}/generate-api-tests` | Generate API tests from exploration results | Optional | -- |
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
| GET | `/requirements/generate-jobs/{id}` | Get requirement generation job status | Optional |
| POST | `/requirements/bulk` | Create requirements in bulk | Optional |
| POST | `/requirements/bulk-generate-specs` | Start bulk spec generation for requirements | Optional |
| GET | `/requirements/bulk-generate-jobs/{id}` | Get bulk spec generation job status | Optional |
| GET | `/requirements/duplicates` | Find duplicate requirements | Optional |
| POST | `/requirements/check-duplicate` | Check if a requirement is a duplicate | Optional |
| POST | `/requirements/merge` | Merge duplicate requirements | Optional |
| POST | `/requirements/review/decisions` | Apply bulk requirement review decisions | Optional |
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
| GET | `/rtm/generate-jobs/{id}` | Get RTM generation job status | Optional |
| GET | `/rtm/coverage` | Get test coverage summary | Optional |
| GET | `/rtm/gaps` | Find requirements with no test coverage | Optional |
| GET | `/rtm/export/{format}` | Export RTM as markdown, csv, or html | Optional |
| POST | `/rtm/snapshot` | Save a point-in-time RTM snapshot | Optional |
| GET | `/rtm/snapshots` | List saved RTM snapshots | Optional |
| GET | `/rtm/snapshot/{id}` | Get one RTM snapshot with entries | Optional |
| GET | `/rtm/trend` | RTM coverage trend data | Optional |
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
| GET | `/api/memory/graph/knowledge` | Knowledge graph facts and relationships | Optional |
| GET | `/api/memory/graph/memory/{id}` | Get graph details for one memory | Optional |
| GET | `/api/memory/graph/review` | List memory graph relationships pending review | Optional |
| PATCH | `/api/memory/graph/review/{edge_id}/approve` | Approve a memory graph relationship | Optional |
| PATCH | `/api/memory/graph/review/{edge_id}/reject` | Reject a memory graph relationship | Optional |
| POST | `/api/memory/graph/rebuild` | Rebuild memory graph indexes | Optional |
| GET | `/api/memory/stats` | Overall memory system statistics | Optional |
| GET | `/api/memory/agent` | List or search curated agent memories | Optional |
| POST | `/api/memory/agent` | Create a curated agent memory | Optional |
| PATCH | `/api/memory/agent/{memory_id}` | Update an agent memory | Optional |
| POST | `/api/memory/agent/consolidate` | Extract durable memories from a text block | Optional |
| POST | `/api/memory/agent/verify-stale` | Mark stale active memories for review | Optional |
| PATCH | `/api/memory/agent/{memory_id}/approve` | Approve a review-required memory | Optional |
| PATCH | `/api/memory/agent/{memory_id}/verify` | Mark a memory as verified | Optional |
| PATCH | `/api/memory/agent/{memory_id}/archive` | Archive an agent memory | Optional |
| DELETE | `/api/memory/agent/{memory_id}` | Delete an agent memory and vector index document | Optional |
| GET | `/api/memory/agent/context` | Return formatted memory context for prompt injection | Optional |
| GET | `/api/memory/context-preview` | Preview prompt-ready memory context | Optional |
| GET | `/api/memory/context` | Return unified structured memory bundle | Optional |
| GET | `/api/memory/injections` | List recent memory injection telemetry | Optional |
| POST | `/api/memory/injections/{injection_event_id}/feedback` | Submit feedback for memories used in an injection event | Optional |
| GET | `/api/memory/feedback` | Return aggregate feedback stats for selected memories | Optional |
| GET | `/api/memory/session-recall/recent` | Browse recent assistant conversations | Optional |
| GET | `/api/memory/session-recall/search` | Search assistant conversation memory | Optional |
| GET | `/api/memory/session-recall/window` | Return an anchored conversation window | Optional |
| GET | `/api/memory/health` | Report memory system health and embedding mode | Optional |
| GET | `/api/memory/diagnostics` | Report memory health, stale records, and recommended repair actions | Optional |
| GET | `/api/memory/effectiveness` | Summarize whether injected memory correlates with successful outcomes | Optional |
| POST | `/api/memory/repair` | Run conservative memory repair actions, optionally as a dry run | Optional |
| GET | `/api/memory/browser` | Inspect browser exploration memory | Optional |
| GET | `/api/memory/browser/frontier` | Inspect ranked browser frontier work | Optional |
| POST | `/api/memory/browser/frontier/claim` | Lease frontier items for a worker | Optional |
| PATCH | `/api/memory/browser/frontier/{frontier_id}/complete` | Mark frontier work completed | Optional |
| PATCH | `/api/memory/browser/frontier/{frontier_id}/fail` | Mark frontier work failed and retryable | Optional |
| PATCH | `/api/memory/browser/frontier/{frontier_id}/skip` | Skip stale, risky, or irrelevant frontier work | Optional |
| GET | `/api/memory/projects` | Memory data grouped by project | Optional |

## Autonomous Diagnostics

Source: `orchestrator/api/autonomous.py`

| Method | Path | Description | Auth Required |
|--------|------|-------------|---------------|
| GET | `/autonomous/{project_id}/diagnostics` | Inspect autonomous mission health for a project | Optional |
| POST | `/autonomous/{project_id}/diagnostics/backfill` | Backfill canonical autonomous state and return refreshed diagnostics | Yes |
| POST | `/autonomous/{project_id}/diagnostics/monitor` | Run the autonomous diagnostics monitor for a project | Yes |
| POST | `/autonomous/{project_id}/diagnostics/recover` | Recover stale autonomous work and return refreshed diagnostics | Yes |

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
| POST | `/api/prd/{project_id}/features/{feature_slug}/requirements` | Add a requirement to a PRD feature | Optional |
| PUT | `/api/prd/{project_id}/features/{feature_slug}/requirements/{index}` | Update a PRD feature requirement | Optional |
| DELETE | `/api/prd/{project_id}/features/{feature_slug}/requirements/{index}` | Delete a PRD feature requirement | Optional |
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
| GET | `/api/agents/runs/{id}/events` | List persisted lifecycle events for an agent run | Optional |
| GET | `/api/agents/runs/{id}/events/stream` | Stream agent run lifecycle events over SSE | Optional |
| GET | `/api/agents/temporal/health` | Check Temporal readiness for standalone agent runs | Optional |
| POST | `/api/agents/runs/{id}/pause` | Pause an agent run | Optional |
| POST | `/api/agents/runs/{id}/resume` | Resume an agent run | Optional |
| POST | `/api/agents/runs/{id}/cancel` | Cancel an agent run | Optional |
| GET | `/api/agents/runs/{id}/report` | Get an agent run report | Optional |
| GET | `/api/agents/reports/search` | Search generated agent reports | Optional |
| GET | `/api/agents/tools/catalog` | List available agent tools | Optional |
| GET | `/api/agents/definitions` | List custom agent definitions | Optional |
| POST | `/api/agents/definitions` | Create a custom agent definition | Optional |
| GET | `/api/agents/definitions/{id}` | Get a custom agent definition | Optional |
| PUT | `/api/agents/definitions/{id}` | Update a custom agent definition | Optional |
| DELETE | `/api/agents/definitions/{id}` | Delete a custom agent definition | Optional |
| POST | `/api/agents/definitions/{id}/runs` | Run a custom agent definition | Optional |
| POST | `/api/agents/exploratory` | Run enhanced exploratory testing | Optional |
| POST | `/api/agents/exploratory/{run_id}/synthesize` | Generate specs from exploration | Optional |
| GET | `/api/agents/exploratory/{run_id}/specs` | Get generated specs | Optional |
| GET | `/api/agents/exploratory/{run_id}/flows/{flow_id}` | Get flow details | Optional |
| PUT | `/api/agents/exploratory/{run_id}/flows/{flow_id}` | Update exploratory flow details | Optional |
| DELETE | `/api/agents/exploratory/{run_id}/flows/{flow_id}` | Delete exploratory flow details | Optional |
| POST | `/api/agents/exploratory/{run_id}/analyze-prerequisites` | Analyze flow prerequisites | Optional |
| POST | `/api/agents/exploratory/{run_id}/flows/{flow_id}/spec` | Generate spec for one flow | Optional |
| POST | `/api/agents/exploratory/{run_id}/flows/{flow_id}/generate` | Generate validated test via native pipeline | Optional |
| GET | `/api/agents/exploratory/flow-spec-jobs/{id}` | Get exploratory flow-spec job status | Optional |
| POST | `/api/agents/queue-flush` | Clear queued agent work | Optional |
| POST | `/api/agents/queue-clean-orphans` | Clean orphaned agent queue entries | Optional |

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
| POST | `/settings/test-connection` | Test AI provider settings without saving | Optional |

## Execution Settings

Source: `orchestrator/api/main.py`

| Method | Path | Description | Auth Required |
|--------|------|-------------|---------------|
| GET | `/execution-settings` | Get the persisted global browser concurrency cap (`parallelism`), headless mode, memory, DB type | Optional |
| PUT | `/execution-settings` | Update execution settings and the active browser pool max | Optional |

## Queue Management

Source: `orchestrator/api/main.py`

| Method | Path | Description | Auth Required |
|--------|------|-------------|---------------|
| GET | `/queue-status` | Browser pool running/queued/max totals plus legacy test-run queue diagnostics | Optional |
| POST | `/queue/clear` | Clear stuck queue entries | Optional |

## Browser Pool

Source: `orchestrator/api/main.py`

| Method | Path | Description | Auth Required |
|--------|------|-------------|---------------|
| GET | `/api/browser-pool/status` | Source-of-truth pool utilization, queued work, and `by_type` slot usage | Optional |
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
| POST | `/api-testing/specs/folder` | Create a nested API spec folder | Optional |
| PUT | `/api-testing/specs/{name}/tags` | Update tags for an API test spec | Optional |
| POST | `/api-testing/specs/bulk-generate` | Generate tests for multiple API specs | Optional |
| POST | `/api-testing/specs/bulk-run` | Run multiple API specs | Optional |
| POST | `/api-testing/generate` | Generate a Playwright API test from a saved spec | Optional |
| POST | `/api-testing/create-and-generate` | Create a spec and immediately start generation | Optional |
| POST | `/api-testing/edge-cases` | Generate edge-case checks for an API spec | Optional |
| GET | `/api-testing/jobs` | List API generation jobs | Optional |
| GET | `/api-testing/jobs/{job_id}` | Get API generation job status | Optional |
| GET | `/api-testing/jobs/{job_id}/logs` | Get API generation job logs | Optional |
| GET | `/api-testing/generated-tests` | List generated API test files | Optional |
| GET | `/api-testing/generated-tests/summary` | Summary of generated API tests | Optional |
| GET | `/api-testing/generated-tests/{name}` | Get generated API test code | Optional |
| PUT | `/api-testing/generated-tests/{name}` | Update generated API test code | Optional |
| DELETE | `/api-testing/generated-tests/{name}` | Delete generated API test code | Optional |
| POST | `/api-testing/import-openapi` | Import OpenAPI/Swagger spec | Optional |
| POST | `/api-testing/import-openapi-file` | Import an uploaded OpenAPI/Swagger file | Optional |
| GET | `/api-testing/import-history` | List OpenAPI import history | Optional |
| POST | `/api-testing/run` | Run API test (background job) | Optional |
| POST | `/api-testing/run-direct` | Run API test directly | Optional |
| GET | `/api-testing/runs` | List API test run history | Optional |
| GET | `/api-testing/runs/latest-by-spec` | Get the latest run for a spec | Optional |
| GET | `/api-testing/runs/{run_id}` | Get run details with logs | Optional |
| POST | `/api-testing/runs/{run_id}/retry` | Retry an API test run | Optional |

API Testing coverage groups:

| Group | Main endpoints |
|-------|----------------|
| Specs | `/api-testing/specs`, `/api-testing/specs/{name}`, `/api-testing/specs/folder`, `/api-testing/specs/{name}/tags` |
| Generation jobs | `/api-testing/generate`, `/api-testing/create-and-generate`, `/api-testing/jobs`, `/api-testing/jobs/{job_id}/logs` |
| Generated tests | `/api-testing/generated-tests`, `/api-testing/generated-tests/{name}`, `/api-testing/generated-tests/summary` |
| OpenAPI import | `/api-testing/import-openapi`, `/api-testing/import-openapi-file`, `/api-testing/import-history` |
| Runs | `/api-testing/run`, `/api-testing/run-direct`, `/api-testing/runs`, `/api-testing/runs/latest-by-spec`, `/api-testing/runs/{run_id}/retry` |
| Bulk operations | `/api-testing/specs/bulk-generate`, `/api-testing/specs/bulk-run`, `/api-testing/edge-cases` |

## Load Testing

Prefix: `/load-testing` | Source: `orchestrator/api/load_testing.py`

| Method | Path | Description | Auth Required |
|--------|------|-------------|---------------|
| POST | `/load-testing/specs` | Create load test spec | Optional |
| GET | `/load-testing/specs` | List load test specs | Optional |
| GET | `/load-testing/specs/{folder}` | Get load test spec details | Optional |
| PUT | `/load-testing/specs/{folder}` | Update load test spec | Optional |
| DELETE | `/load-testing/specs/{folder}` | Delete load test spec | Optional |
| POST | `/load-testing/generate` | Generate K6 script | Optional |
| POST | `/load-testing/run` | Execute load test (background job) | Optional |
| POST | `/load-testing/run-from-spec` | Execute load test from a saved spec | Optional |
| GET | `/load-testing/runs` | List load test runs | Optional |
| GET | `/load-testing/runs/{run_id}` | Run details with metrics | Optional |
| GET | `/load-testing/runs/{run_id}/timeseries` | Time-series metrics for one run | Optional |
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
| POST | `/llm-testing/providers/{id}/health-check` | Check provider connectivity and model response health | Optional |
| GET | `/llm-testing/openrouter/models` | List OpenRouter model metadata | Optional |
| POST | `/llm-testing/openrouter/demo` | Run an OpenRouter demo request | Optional |
| POST | `/llm-testing/demo-content` | Seed demo providers, specs, datasets, or runs | Optional |

### Specs

| Method | Path | Description | Auth Required |
|--------|------|-------------|---------------|
| POST | `/llm-testing/specs` | Create LLM test spec | Optional |
| GET | `/llm-testing/specs` | List LLM test specs | Optional |
| PUT | `/llm-testing/specs/{name}` | Update spec | Optional |
| DELETE | `/llm-testing/specs/{name}` | Delete spec | Optional |
| GET | `/llm-testing/specs/{name}/versions` | List spec versions | Optional |
| POST | `/llm-testing/specs/{name}/versions` | Create a saved spec version | Optional |
| GET | `/llm-testing/specs/{name}/versions/{version}` | Get one saved spec version | Optional |
| POST | `/llm-testing/specs/{name}/versions/{version}/restore` | Restore a saved spec version | Optional |
| POST | `/llm-testing/specs/{name}/suggest-improvements` | AI spec improvements | Optional |

### Execution

| Method | Path | Description | Auth Required |
|--------|------|-------------|---------------|
| POST | `/llm-testing/run` | Run suite against a provider (background) | Optional |
| GET | `/llm-testing/jobs/{job_id}` | Get LLM test job status | Optional |
| GET | `/llm-testing/runs` | List LLM test runs | Optional |
| GET | `/llm-testing/runs/{run_id}` | Get LLM test run detail | Optional |
| GET | `/llm-testing/runs/{run_id}/results` | Get case-level LLM test results | Optional |
| POST | `/llm-testing/compare` | Compare multiple providers | Optional |
| GET | `/llm-testing/comparisons` | List comparison runs | Optional |
| GET | `/llm-testing/comparisons/{comparison_id}` | Get comparison detail | Optional |
| GET | `/llm-testing/comparisons/{comparison_id}/matrix` | Get provider/spec scoring matrix | Optional |
| POST | `/llm-testing/bulk-run` | Batch dataset operations | Optional |
| POST | `/llm-testing/bulk-compare` | Batch comparison | Optional |
| POST | `/llm-testing/generate-suite` | AI-generated test suite | Optional |
| GET | `/llm-testing/prompt-iterations` | List prompt-iteration experiments | Optional |
| POST | `/llm-testing/prompt-iterations` | A/B prompt testing | Optional |
| GET | `/llm-testing/prompt-iterations/{iteration_id}` | Get prompt-iteration detail | Optional |

### Datasets

| Method | Path | Description | Auth Required |
|--------|------|-------------|---------------|
| POST | `/llm-testing/datasets` | Create dataset | Optional |
| GET | `/llm-testing/datasets` | List datasets | Optional |
| PUT | `/llm-testing/datasets/{id}` | Update dataset | Optional |
| DELETE | `/llm-testing/datasets/{id}` | Delete dataset | Optional |
| GET | `/llm-testing/datasets/{id}` | Get dataset detail | Optional |
| POST | `/llm-testing/datasets/import-csv` | Import dataset cases from CSV | Optional |
| POST | `/llm-testing/datasets/from-spec/{spec_name}` | Create a dataset from a spec | Optional |
| POST | `/llm-testing/datasets/{id}/cases` | Add a dataset case | Optional |
| PUT | `/llm-testing/datasets/{id}/cases/{case_id}` | Update a dataset case | Optional |
| DELETE | `/llm-testing/datasets/{id}/cases/{case_id}` | Delete a dataset case | Optional |
| POST | `/llm-testing/datasets/{id}/augment` | AI dataset augmentation | Optional |
| POST | `/llm-testing/datasets/{id}/augment/{job_id}/accept` | Accept generated augmentation cases | Optional |
| GET | `/llm-testing/datasets/{id}/export` | Export dataset cases | Optional |
| POST | `/llm-testing/datasets/{id}/to-spec` | Convert a dataset to a spec | Optional |
| POST | `/llm-testing/datasets/{id}/duplicate` | Duplicate a dataset | Optional |
| POST | `/llm-testing/datasets/{id}/golden` | Mark dataset as golden baseline | Optional |
| GET | `/llm-testing/datasets/{id}/diff` | Diff dataset versions | Optional |
| GET | `/llm-testing/datasets/{id}/versions` | List dataset versions | Optional |
| POST | `/llm-testing/datasets/{id}/compare` | Compare dataset runs | Optional |
| POST | `/llm-testing/datasets/{id}/run` | Run a dataset directly | Optional |

### Schedules

| Method | Path | Description | Auth Required |
|--------|------|-------------|---------------|
| POST | `/llm-testing/schedules` | Create schedule | Optional |
| GET | `/llm-testing/schedules` | List schedules | Optional |
| GET | `/llm-testing/schedules/{id}` | Get schedule detail | Optional |
| PUT | `/llm-testing/schedules/{id}` | Update schedule | Optional |
| DELETE | `/llm-testing/schedules/{id}` | Delete schedule | Optional |
| POST | `/llm-testing/schedules/{id}/run-now` | Trigger schedule immediately | Optional |

### Analytics

| Method | Path | Description | Auth Required |
|--------|------|-------------|---------------|
| GET | `/llm-testing/analytics/overview` | Overview stats | Optional |
| GET | `/llm-testing/analytics/trends` | Performance trends | Optional |
| GET | `/llm-testing/analytics/latency-distribution` | Latency distribution | Optional |
| GET | `/llm-testing/analytics/cost-tracking` | Cost tracking | Optional |
| GET | `/llm-testing/analytics/regressions` | Regression detection | Optional |
| GET | `/llm-testing/analytics/dataset-performance` | Dataset performance analytics | Optional |
| GET | `/llm-testing/analytics/dataset-trends` | Dataset performance trends | Optional |
| GET | `/llm-testing/analytics/golden-dashboard` | Golden dashboard | Optional |

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

### Unified Control Center

Prefix: `/projects/{project_id}/ci` | Source: `orchestrator/api/ci_control.py`

Provider-neutral CI/CD control surface for the dashboard.

| Method | Path | Description | Auth Required |
|--------|------|-------------|---------------|
| GET | `/projects/{project_id}/ci/providers` | List configured CI providers and capabilities | Optional |
| GET | `/projects/{project_id}/ci/workflows` | List normalized provider workflows | Optional |
| GET | `/projects/{project_id}/ci/runs` | List normalized CI runs across providers | Optional |
| POST | `/projects/{project_id}/ci/runs/sync` | Sync recent provider runs into normalized CI run history | Optional |
| GET | `/projects/{project_id}/ci/runs/{provider}/{mapping_id}` | Get run details with jobs/artifacts | Optional |
| POST | `/projects/{project_id}/ci/workflows/dispatch` | Dispatch a GitHub workflow or GitLab pipeline | Optional |
| POST | `/projects/{project_id}/ci/runs/{provider}/{mapping_id}/cancel` | Cancel a provider run | Optional |
| POST | `/projects/{project_id}/ci/runs/{provider}/{mapping_id}/rerun` | Rerun a provider run | Optional |
| GET | `/projects/{project_id}/ci/runs/{provider}/{mapping_id}/logs` | Fetch provider run/job log access | Optional |
| POST | `/projects/{project_id}/ci/workflow-change-requests` | Generate and validate a GitHub Actions workflow draft | Optional |
| POST | `/projects/{project_id}/ci/workflow-change-requests/{change_id}/pull-request` | Open a draft GitHub PR for a generated workflow | Optional |
| GET | `/projects/{project_id}/ci/audit-events` | List CI actions initiated from Quorvex | Optional |

### GitHub

Prefix: `/github` | Source: `orchestrator/api/github_ci.py`

GitHub Actions workflow generation and webhook handling.

| Surface | Endpoints | Auth/secret expectations |
|---------|-----------|--------------------------|
| Configuration | `GET/POST/DELETE /github/{project_id}/config`, `POST /github/{project_id}/test-connection` | Stores provider token/config in project-scoped credentials |
| Remote discovery | `GET /github/{project_id}/remote-repos`, `GET /github/{project_id}/remote-workflows`, `GET /github/{project_id}/pull-requests` | Requires GitHub token with repository read access |
| Workflow runs | `GET /github/{project_id}/pipelines`, `GET /github/{project_id}/pipelines/{pipeline_mapping_id}`, `POST /github/{project_id}/trigger-workflow`, `POST /github/{project_id}/sync-runs` | Requires workflow read/dispatch permissions for the target repository |
| PR advisor | `POST /github/{project_id}/pr-advisor/analyze`, `GET /github/{project_id}/pr-advisor/analyses`, `POST /github/{project_id}/pr-advisor/analyses/{analysis_id}/run` | Requires pull request and repository read access |
| Quality gates | `GET/PUT /github/{project_id}/quality-gates/config`, `POST /github/{project_id}/quality-gates/pr/start`, `GET /github/{project_id}/quality-gates/pr/status` | Requires repository read access; status posting depends on configured write permissions |
| Repository index | `POST /github/{project_id}/repository-index`, `GET /github/{project_id}/repository-index/latest` | Requires repository content read access |
| Webhook | `POST /github/webhook/github` | Verify using the configured GitHub webhook secret |

### GitLab

Prefix: `/gitlab` | Source: `orchestrator/api/gitlab_ci.py`

GitLab CI pipeline configuration.

| Surface | Endpoints | Auth/secret expectations |
|---------|-----------|--------------------------|
| Configuration | `GET/POST/DELETE /gitlab/{project_id}/config`, `POST /gitlab/{project_id}/test-connection` | Stores GitLab token/config in project-scoped credentials |
| Remote discovery | `GET /gitlab/{project_id}/remote-projects` | Requires GitLab project read access |
| Pipeline runs | `GET /gitlab/{project_id}/pipelines`, `GET /gitlab/{project_id}/pipelines/{mapping_id}`, `POST /gitlab/{project_id}/trigger-pipeline` | Requires pipeline read/trigger permissions |
| Webhook | `POST /gitlab/webhook/gitlab` | Verify using the configured GitLab webhook secret |

## Jira Integration

Prefix: `/jira` | Source: `orchestrator/api/jira.py`

Issue tracking integration for linking test results to Jira tickets.

| Surface | Endpoints | Auth/secret expectations |
|---------|-----------|--------------------------|
| Configuration | `GET/POST/DELETE /jira/{project_id}/config`, `POST /jira/{project_id}/test-connection` | Stores Jira URL, user, and token in project-scoped credentials |
| Remote discovery | `GET /jira/{project_id}/remote-projects`, `GET /jira/{project_id}/remote-issue-types/{jira_project_key}` | Requires Jira project read access |
| Issue creation | `POST /jira/{project_id}/create-issue`, `GET /jira/{project_id}/issues`, `GET /jira/{project_id}/issues/{run_id}` | Requires issue create/read permissions |
| Bug reports | `POST /jira/{project_id}/generate-bug-report/{run_id}`, `GET /jira/{project_id}/bug-report-jobs/{job_id}` | Uses run artifacts and stored Jira config |

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

## Complete Route Coverage Index

This generated index is used by `scripts/check_docs_drift.py` to keep the endpoint reference aligned with FastAPI decorators. The curated sections above explain the main product surfaces; this table provides full method/path coverage.

| Method | Path | Source |
|--------|------|--------|
| GET | `/analytics/coverage-overview` | `orchestrator/api/analytics.py` |
| GET | `/analytics/failure-classification` | `orchestrator/api/analytics.py` |
| GET | `/analytics/flake-detection` | `orchestrator/api/analytics.py` |
| GET | `/analytics/pass-rate-trends` | `orchestrator/api/analytics.py` |
| DELETE | `/analytics/quarantine/{spec_name}` | `orchestrator/api/analytics.py` |
| POST | `/analytics/quarantine/{spec_name}` | `orchestrator/api/analytics.py` |
| GET | `/analytics/spec-performance` | `orchestrator/api/analytics.py` |
| POST | `/api-testing/create-and-generate` | `orchestrator/api/api_testing.py` |
| POST | `/api-testing/edge-cases` | `orchestrator/api/api_testing.py` |
| POST | `/api-testing/generate` | `orchestrator/api/api_testing.py` |
| GET | `/api-testing/generated-tests` | `orchestrator/api/api_testing.py` |
| GET | `/api-testing/generated-tests/summary` | `orchestrator/api/api_testing.py` |
| DELETE | `/api-testing/generated-tests/{name}` | `orchestrator/api/api_testing.py` |
| GET | `/api-testing/generated-tests/{name}` | `orchestrator/api/api_testing.py` |
| PUT | `/api-testing/generated-tests/{name}` | `orchestrator/api/api_testing.py` |
| GET | `/api-testing/import-history` | `orchestrator/api/api_testing.py` |
| POST | `/api-testing/import-openapi` | `orchestrator/api/api_testing.py` |
| POST | `/api-testing/import-openapi-file` | `orchestrator/api/api_testing.py` |
| GET | `/api-testing/jobs` | `orchestrator/api/api_testing.py` |
| GET | `/api-testing/jobs/{job_id}` | `orchestrator/api/api_testing.py` |
| GET | `/api-testing/jobs/{job_id}/logs` | `orchestrator/api/api_testing.py` |
| POST | `/api-testing/run` | `orchestrator/api/api_testing.py` |
| POST | `/api-testing/run-direct` | `orchestrator/api/api_testing.py` |
| GET | `/api-testing/runs` | `orchestrator/api/api_testing.py` |
| GET | `/api-testing/runs/latest-by-spec` | `orchestrator/api/api_testing.py` |
| GET | `/api-testing/runs/{run_id}` | `orchestrator/api/api_testing.py` |
| POST | `/api-testing/runs/{run_id}/retry` | `orchestrator/api/api_testing.py` |
| GET | `/api-testing/specs` | `orchestrator/api/api_testing.py` |
| POST | `/api-testing/specs` | `orchestrator/api/api_testing.py` |
| POST | `/api-testing/specs/bulk-generate` | `orchestrator/api/api_testing.py` |
| POST | `/api-testing/specs/bulk-run` | `orchestrator/api/api_testing.py` |
| POST | `/api-testing/specs/folder` | `orchestrator/api/api_testing.py` |
| DELETE | `/api-testing/specs/{name}` | `orchestrator/api/api_testing.py` |
| GET | `/api-testing/specs/{name}` | `orchestrator/api/api_testing.py` |
| PUT | `/api-testing/specs/{name}` | `orchestrator/api/api_testing.py` |
| PUT | `/api-testing/specs/{name}/tags` | `orchestrator/api/api_testing.py` |
| GET | `/api/agents/definitions` | `orchestrator/api/main.py` |
| POST | `/api/agents/definitions` | `orchestrator/api/main.py` |
| DELETE | `/api/agents/definitions/{definition_id}` | `orchestrator/api/main.py` |
| GET | `/api/agents/definitions/{definition_id}` | `orchestrator/api/main.py` |
| PUT | `/api/agents/definitions/{definition_id}` | `orchestrator/api/main.py` |
| POST | `/api/agents/definitions/{definition_id}/runs` | `orchestrator/api/main.py` |
| POST | `/api/agents/exploratory` | `orchestrator/api/main.py` |
| GET | `/api/agents/exploratory/flow-spec-jobs/{job_id}` | `orchestrator/api/main.py` |
| POST | `/api/agents/exploratory/{run_id}/analyze-prerequisites` | `orchestrator/api/main.py` |
| DELETE | `/api/agents/exploratory/{run_id}/flows/{flow_id}` | `orchestrator/api/main.py` |
| GET | `/api/agents/exploratory/{run_id}/flows/{flow_id}` | `orchestrator/api/main.py` |
| PUT | `/api/agents/exploratory/{run_id}/flows/{flow_id}` | `orchestrator/api/main.py` |
| POST | `/api/agents/exploratory/{run_id}/flows/{flow_id}/generate` | `orchestrator/api/main.py` |
| POST | `/api/agents/exploratory/{run_id}/flows/{flow_id}/spec` | `orchestrator/api/main.py` |
| GET | `/api/agents/exploratory/{run_id}/specs` | `orchestrator/api/main.py` |
| POST | `/api/agents/exploratory/{run_id}/synthesize` | `orchestrator/api/main.py` |
| POST | `/api/agents/queue-clean-orphans` | `orchestrator/api/main.py` |
| POST | `/api/agents/queue-flush` | `orchestrator/api/main.py` |
| GET | `/api/agents/queue-status` | `orchestrator/api/main.py` |
| GET | `/api/agents/reports/search` | `orchestrator/api/main.py` |
| GET | `/api/agents/runs` | `orchestrator/api/main.py` |
| POST | `/api/agents/runs` | `orchestrator/api/main.py` |
| GET | `/api/agents/runs/{id}` | `orchestrator/api/main.py` |
| POST | `/api/agents/runs/{id}/cancel` | `orchestrator/api/main.py` |
| GET | `/api/agents/runs/{id}/events` | `orchestrator/api/main.py` |
| GET | `/api/agents/runs/{id}/events/stream` | `orchestrator/api/main.py` |
| POST | `/api/agents/runs/{id}/pause` | `orchestrator/api/main.py` |
| GET | `/api/agents/runs/{id}/report` | `orchestrator/api/main.py` |
| POST | `/api/agents/runs/{id}/resume` | `orchestrator/api/main.py` |
| GET | `/api/agents/sessions` | `orchestrator/api/main.py` |
| DELETE | `/api/agents/sessions/{session_id}` | `orchestrator/api/main.py` |
| POST | `/api/agents/sessions/{session_id}` | `orchestrator/api/main.py` |
| GET | `/api/agents/tools/catalog` | `orchestrator/api/main.py` |
| POST | `/api/backup` | `orchestrator/api/main.py` |
| GET | `/api/backup/status` | `orchestrator/api/main.py` |
| POST | `/api/browser-pool/cleanup` | `orchestrator/api/main.py` |
| GET | `/api/browser-pool/recent` | `orchestrator/api/main.py` |
| GET | `/api/browser-pool/status` | `orchestrator/api/main.py` |
| GET | `/api/key-rotation/status` | `orchestrator/api/main.py` |
| GET | `/api/memory/agent` | `orchestrator/api/memory.py` |
| POST | `/api/memory/agent` | `orchestrator/api/memory.py` |
| POST | `/api/memory/agent/consolidate` | `orchestrator/api/memory.py` |
| GET | `/api/memory/agent/context` | `orchestrator/api/memory.py` |
| POST | `/api/memory/agent/verify-stale` | `orchestrator/api/memory.py` |
| DELETE | `/api/memory/agent/{memory_id}` | `orchestrator/api/memory.py` |
| PATCH | `/api/memory/agent/{memory_id}` | `orchestrator/api/memory.py` |
| PATCH | `/api/memory/agent/{memory_id}/approve` | `orchestrator/api/memory.py` |
| PATCH | `/api/memory/agent/{memory_id}/archive` | `orchestrator/api/memory.py` |
| PATCH | `/api/memory/agent/{memory_id}/verify` | `orchestrator/api/memory.py` |
| GET | `/api/memory/browser` | `orchestrator/api/memory.py` |
| GET | `/api/memory/browser/frontier` | `orchestrator/api/memory.py` |
| POST | `/api/memory/browser/frontier/claim` | `orchestrator/api/memory.py` |
| PATCH | `/api/memory/browser/frontier/{frontier_id}/complete` | `orchestrator/api/memory.py` |
| PATCH | `/api/memory/browser/frontier/{frontier_id}/fail` | `orchestrator/api/memory.py` |
| PATCH | `/api/memory/browser/frontier/{frontier_id}/skip` | `orchestrator/api/memory.py` |
| GET | `/api/memory/context` | `orchestrator/api/memory.py` |
| GET | `/api/memory/context-preview` | `orchestrator/api/memory.py` |
| GET | `/api/memory/coverage/gaps` | `orchestrator/api/memory.py` |
| GET | `/api/memory/coverage/suggestions` | `orchestrator/api/memory.py` |
| GET | `/api/memory/coverage/summary` | `orchestrator/api/memory.py` |
| GET | `/api/memory/diagnostics` | `orchestrator/api/memory.py` |
| GET | `/api/memory/effectiveness` | `orchestrator/api/memory.py` |
| GET | `/api/memory/feedback` | `orchestrator/api/memory.py` |
| GET | `/api/memory/graph/flows` | `orchestrator/api/memory.py` |
| GET | `/api/memory/graph/knowledge` | `orchestrator/api/memory.py` |
| GET | `/api/memory/graph/memory/{memory_id}` | `orchestrator/api/memory.py` |
| GET | `/api/memory/graph/pages` | `orchestrator/api/memory.py` |
| POST | `/api/memory/graph/rebuild` | `orchestrator/api/memory.py` |
| GET | `/api/memory/graph/review` | `orchestrator/api/memory.py` |
| PATCH | `/api/memory/graph/review/{edge_id}/approve` | `orchestrator/api/memory.py` |
| PATCH | `/api/memory/graph/review/{edge_id}/reject` | `orchestrator/api/memory.py` |
| GET | `/api/memory/graph/stats` | `orchestrator/api/memory.py` |
| GET | `/api/memory/health` | `orchestrator/api/memory.py` |
| GET | `/api/memory/injections` | `orchestrator/api/memory.py` |
| POST | `/api/memory/injections/{injection_event_id}/feedback` | `orchestrator/api/memory.py` |
| GET | `/api/memory/patterns` | `orchestrator/api/memory.py` |
| GET | `/api/memory/projects` | `orchestrator/api/memory.py` |
| POST | `/api/memory/repair` | `orchestrator/api/memory.py` |
| GET | `/api/memory/selectors` | `orchestrator/api/memory.py` |
| GET | `/api/memory/session-recall/recent` | `orchestrator/api/memory.py` |
| GET | `/api/memory/session-recall/search` | `orchestrator/api/memory.py` |
| GET | `/api/memory/session-recall/window` | `orchestrator/api/memory.py` |
| POST | `/api/memory/similar` | `orchestrator/api/memory.py` |
| GET | `/api/memory/stats` | `orchestrator/api/memory.py` |
| GET | `/api/mobile-testing/health` | `orchestrator/api/main.py` |
| POST | `/api/prd/generate-test` | `orchestrator/api/prd.py` |
| GET | `/api/prd/generation/{generation_id}` | `orchestrator/api/prd.py` |
| GET | `/api/prd/generation/{generation_id}/log/stream` | `orchestrator/api/prd.py` |
| POST | `/api/prd/generation/{generation_id}/stop` | `orchestrator/api/prd.py` |
| POST | `/api/prd/heal-test` | `orchestrator/api/prd.py` |
| GET | `/api/prd/projects` | `orchestrator/api/prd.py` |
| GET | `/api/prd/queue/status` | `orchestrator/api/prd.py` |
| POST | `/api/prd/run-test` | `orchestrator/api/prd.py` |
| POST | `/api/prd/upload` | `orchestrator/api/prd.py` |
| DELETE | `/api/prd/{project_id}` | `orchestrator/api/prd.py` |
| GET | `/api/prd/{project_id}/features` | `orchestrator/api/prd.py` |
| POST | `/api/prd/{project_id}/features/{feature_slug}/requirements` | `orchestrator/api/prd.py` |
| DELETE | `/api/prd/{project_id}/features/{feature_slug}/requirements/{req_index}` | `orchestrator/api/prd.py` |
| PUT | `/api/prd/{project_id}/features/{feature_slug}/requirements/{req_index}` | `orchestrator/api/prd.py` |
| POST | `/api/prd/{project_id}/generate-plan` | `orchestrator/api/prd.py` |
| GET | `/api/prd/{project_id}/generations` | `orchestrator/api/prd.py` |
| POST | `/api/resources/cleanup` | `orchestrator/api/main.py` |
| GET | `/api/resources/status` | `orchestrator/api/main.py` |
| POST | `/auth/login` | `orchestrator/api/auth.py` |
| POST | `/auth/logout` | `orchestrator/api/auth.py` |
| POST | `/auth/logout-all` | `orchestrator/api/auth.py` |
| GET | `/auth/me` | `orchestrator/api/auth.py` |
| POST | `/auth/refresh` | `orchestrator/api/auth.py` |
| POST | `/auth/register` | `orchestrator/api/auth.py` |
| GET | `/autonomous/{project_id}/approvals` | `orchestrator/api/autonomous.py` |
| POST | `/autonomous/{project_id}/approvals/{approval_id}/approve` | `orchestrator/api/autonomous.py` |
| POST | `/autonomous/{project_id}/approvals/{approval_id}/reject` | `orchestrator/api/autonomous.py` |
| GET | `/autonomous/{project_id}/diagnostics` | `orchestrator/api/autonomous.py` |
| POST | `/autonomous/{project_id}/diagnostics/backfill` | `orchestrator/api/autonomous.py` |
| POST | `/autonomous/{project_id}/diagnostics/monitor` | `orchestrator/api/autonomous.py` |
| POST | `/autonomous/{project_id}/diagnostics/recover` | `orchestrator/api/autonomous.py` |
| POST | `/autonomous/{project_id}/findings/{finding_id}/approve` | `orchestrator/api/autonomous.py` |
| POST | `/autonomous/{project_id}/findings/{finding_id}/reject` | `orchestrator/api/autonomous.py` |
| POST | `/autonomous/{project_id}/findings/{finding_id}/resolve` | `orchestrator/api/autonomous.py` |
| GET | `/autonomous/{project_id}/missions` | `orchestrator/api/autonomous.py` |
| POST | `/autonomous/{project_id}/missions` | `orchestrator/api/autonomous.py` |
| DELETE | `/autonomous/{project_id}/missions/{mission_id}` | `orchestrator/api/autonomous.py` |
| GET | `/autonomous/{project_id}/missions/{mission_id}` | `orchestrator/api/autonomous.py` |
| PATCH | `/autonomous/{project_id}/missions/{mission_id}` | `orchestrator/api/autonomous.py` |
| GET | `/autonomous/{project_id}/missions/{mission_id}/app-changes` | `orchestrator/api/autonomous.py` |
| POST | `/autonomous/{project_id}/missions/{mission_id}/cancel` | `orchestrator/api/autonomous.py` |
| GET | `/autonomous/{project_id}/missions/{mission_id}/events` | `orchestrator/api/autonomous.py` |
| GET | `/autonomous/{project_id}/missions/{mission_id}/events/stream` | `orchestrator/api/autonomous.py` |
| GET | `/autonomous/{project_id}/missions/{mission_id}/findings` | `orchestrator/api/autonomous.py` |
| POST | `/autonomous/{project_id}/missions/{mission_id}/pause` | `orchestrator/api/autonomous.py` |
| POST | `/autonomous/{project_id}/missions/{mission_id}/resume` | `orchestrator/api/autonomous.py` |
| GET | `/autonomous/{project_id}/missions/{mission_id}/runs` | `orchestrator/api/autonomous.py` |
| POST | `/autonomous/{project_id}/missions/{mission_id}/start` | `orchestrator/api/autonomous.py` |
| GET | `/autonomous/{project_id}/missions/{mission_id}/status` | `orchestrator/api/autonomous.py` |
| GET | `/autonomous/{project_id}/missions/{mission_id}/team-timeline` | `orchestrator/api/autonomous.py` |
| GET | `/autonomous/{project_id}/missions/{mission_id}/work-items` | `orchestrator/api/autonomous.py` |
| GET | `/autonomous/{project_id}/proposal-review` | `orchestrator/api/autonomous.py` |
| GET | `/autonomous/{project_id}/proposals` | `orchestrator/api/autonomous.py` |
| POST | `/autonomous/{project_id}/proposals/refresh-reviews` | `orchestrator/api/autonomous.py` |
| GET | `/autonomous/{project_id}/proposals/{proposal_id}` | `orchestrator/api/autonomous.py` |
| POST | `/autonomous/{project_id}/proposals/{proposal_id}/approve` | `orchestrator/api/autonomous.py` |
| GET | `/autonomous/{project_id}/proposals/{proposal_id}/audit` | `orchestrator/api/autonomous.py` |
| POST | `/autonomous/{project_id}/proposals/{proposal_id}/materialize` | `orchestrator/api/autonomous.py` |
| POST | `/autonomous/{project_id}/proposals/{proposal_id}/refresh-review` | `orchestrator/api/autonomous.py` |
| POST | `/autonomous/{project_id}/proposals/{proposal_id}/reject` | `orchestrator/api/autonomous.py` |
| GET | `/autonomous/{project_id}/work-items` | `orchestrator/api/autonomous.py` |
| POST | `/autonomous/{project_id}/work-items/{work_item_id}/accept` | `orchestrator/api/autonomous.py` |
| POST | `/autonomous/{project_id}/work-items/{work_item_id}/cancel` | `orchestrator/api/autonomous.py` |
| GET | `/autonomous/{project_id}/work-items/{work_item_id}/events` | `orchestrator/api/autonomous.py` |
| GET | `/autonomous/{project_id}/work-items/{work_item_id}/events/stream` | `orchestrator/api/autonomous.py` |
| POST | `/autonomous/{project_id}/work-items/{work_item_id}/needs-revision` | `orchestrator/api/autonomous.py` |
| POST | `/autonomous/{project_id}/work-items/{work_item_id}/reject` | `orchestrator/api/autonomous.py` |
| POST | `/autonomous/{project_id}/work-items/{work_item_id}/retry` | `orchestrator/api/autonomous.py` |
| GET | `/autopilot/sessions` | `orchestrator/api/autopilot.py` |
| POST | `/autopilot/start` | `orchestrator/api/autopilot.py` |
| DELETE | `/autopilot/{session_id}` | `orchestrator/api/autopilot.py` |
| GET | `/autopilot/{session_id}` | `orchestrator/api/autopilot.py` |
| POST | `/autopilot/{session_id}/answer` | `orchestrator/api/autopilot.py` |
| POST | `/autopilot/{session_id}/cancel` | `orchestrator/api/autopilot.py` |
| GET | `/autopilot/{session_id}/live` | `orchestrator/api/autopilot.py` |
| POST | `/autopilot/{session_id}/pause` | `orchestrator/api/autopilot.py` |
| GET | `/autopilot/{session_id}/phases` | `orchestrator/api/autopilot.py` |
| GET | `/autopilot/{session_id}/questions` | `orchestrator/api/autopilot.py` |
| POST | `/autopilot/{session_id}/resume` | `orchestrator/api/autopilot.py` |
| GET | `/autopilot/{session_id}/spec-tasks` | `orchestrator/api/autopilot.py` |
| GET | `/autopilot/{session_id}/test-tasks` | `orchestrator/api/autopilot.py` |
| GET | `/autopilot/{session_id}/test-tasks/{task_id}` | `orchestrator/api/autopilot.py` |
| POST | `/autopilot/{session_id}/test-tasks/{task_id}/stop` | `orchestrator/api/autopilot.py` |
| POST | `/chat/claude-code` | `orchestrator/api/chat.py` |
| GET | `/chat/conversations` | `orchestrator/api/chat.py` |
| POST | `/chat/conversations` | `orchestrator/api/chat.py` |
| GET | `/chat/conversations/recent-summaries` | `orchestrator/api/chat.py` |
| GET | `/chat/conversations/search` | `orchestrator/api/chat.py` |
| DELETE | `/chat/conversations/{conversation_id}` | `orchestrator/api/chat.py` |
| PUT | `/chat/conversations/{conversation_id}` | `orchestrator/api/chat.py` |
| POST | `/chat/conversations/{conversation_id}/auto-title` | `orchestrator/api/chat.py` |
| POST | `/chat/conversations/{conversation_id}/feedback` | `orchestrator/api/chat.py` |
| POST | `/chat/conversations/{conversation_id}/generate-summary` | `orchestrator/api/chat.py` |
| GET | `/chat/conversations/{conversation_id}/messages` | `orchestrator/api/chat.py` |
| POST | `/chat/conversations/{conversation_id}/messages` | `orchestrator/api/chat.py` |
| POST | `/chat/conversations/{conversation_id}/messages/bulk` | `orchestrator/api/chat.py` |
| PATCH | `/chat/conversations/{conversation_id}/messages/{message_id}/content-json` | `orchestrator/api/chat.py` |
| PATCH | `/chat/conversations/{conversation_id}/star` | `orchestrator/api/chat.py` |
| GET | `/chat/project-context` | `orchestrator/api/chat.py` |
| GET | `/chat/resolve-entity` | `orchestrator/api/chat.py` |
| GET | `/chat/search-entities` | `orchestrator/api/chat.py` |
| GET | `/dashboard` | `orchestrator/api/dashboard.py` |
| POST | `/database-testing/analyze/{conn_id}` | `orchestrator/api/database_testing.py` |
| GET | `/database-testing/connections` | `orchestrator/api/database_testing.py` |
| POST | `/database-testing/connections` | `orchestrator/api/database_testing.py` |
| DELETE | `/database-testing/connections/{conn_id}` | `orchestrator/api/database_testing.py` |
| GET | `/database-testing/connections/{conn_id}` | `orchestrator/api/database_testing.py` |
| PUT | `/database-testing/connections/{conn_id}` | `orchestrator/api/database_testing.py` |
| POST | `/database-testing/connections/{conn_id}/query` | `orchestrator/api/database_testing.py` |
| GET | `/database-testing/connections/{conn_id}/schema` | `orchestrator/api/database_testing.py` |
| POST | `/database-testing/connections/{conn_id}/test` | `orchestrator/api/database_testing.py` |
| POST | `/database-testing/generate-spec` | `orchestrator/api/database_testing.py` |
| POST | `/database-testing/generated-specs/save` | `orchestrator/api/database_testing.py` |
| GET | `/database-testing/jobs/{job_id}` | `orchestrator/api/database_testing.py` |
| POST | `/database-testing/run-full/{conn_id}` | `orchestrator/api/database_testing.py` |
| POST | `/database-testing/run/{conn_id}` | `orchestrator/api/database_testing.py` |
| GET | `/database-testing/runs` | `orchestrator/api/database_testing.py` |
| GET | `/database-testing/runs/{run_id}` | `orchestrator/api/database_testing.py` |
| POST | `/database-testing/runs/{run_id}/approve-suggestions` | `orchestrator/api/database_testing.py` |
| GET | `/database-testing/runs/{run_id}/checks` | `orchestrator/api/database_testing.py` |
| GET | `/database-testing/runs/{run_id}/schema` | `orchestrator/api/database_testing.py` |
| GET | `/database-testing/runs/{run_id}/suggestions` | `orchestrator/api/database_testing.py` |
| GET | `/database-testing/specs` | `orchestrator/api/database_testing.py` |
| POST | `/database-testing/specs` | `orchestrator/api/database_testing.py` |
| DELETE | `/database-testing/specs/{name}` | `orchestrator/api/database_testing.py` |
| GET | `/database-testing/specs/{name}` | `orchestrator/api/database_testing.py` |
| PUT | `/database-testing/specs/{name}` | `orchestrator/api/database_testing.py` |
| POST | `/database-testing/suggest/{run_id}` | `orchestrator/api/database_testing.py` |
| GET | `/database-testing/summary` | `orchestrator/api/database_testing.py` |
| GET | `/debug-imports` | `orchestrator/api/main.py` |
| GET | `/execution-settings` | `orchestrator/api/main.py` |
| PUT | `/execution-settings` | `orchestrator/api/main.py` |
| GET | `/exploration` | `orchestrator/api/exploration.py` |
| GET | `/exploration/health` | `orchestrator/api/exploration.py` |
| GET | `/exploration/queue/status` | `orchestrator/api/exploration.py` |
| GET | `/exploration/spec-gen-jobs` | `orchestrator/api/exploration.py` |
| GET | `/exploration/spec-gen-jobs/{job_id}` | `orchestrator/api/exploration.py` |
| POST | `/exploration/start` | `orchestrator/api/exploration.py` |
| GET | `/exploration/{session_id}` | `orchestrator/api/exploration.py` |
| GET | `/exploration/{session_id}/apis` | `orchestrator/api/exploration.py` |
| DELETE | `/exploration/{session_id}/apis/{endpoint_id}` | `orchestrator/api/exploration.py` |
| PUT | `/exploration/{session_id}/apis/{endpoint_id}` | `orchestrator/api/exploration.py` |
| GET | `/exploration/{session_id}/artifacts` | `orchestrator/api/exploration.py` |
| GET | `/exploration/{session_id}/details` | `orchestrator/api/exploration.py` |
| GET | `/exploration/{session_id}/flows` | `orchestrator/api/exploration.py` |
| GET | `/exploration/{session_id}/flows/review` | `orchestrator/api/exploration.py` |
| POST | `/exploration/{session_id}/flows/review/decisions` | `orchestrator/api/exploration.py` |
| DELETE | `/exploration/{session_id}/flows/{flow_id}` | `orchestrator/api/exploration.py` |
| PUT | `/exploration/{session_id}/flows/{flow_id}` | `orchestrator/api/exploration.py` |
| POST | `/exploration/{session_id}/flows/{flow_id}/approve` | `orchestrator/api/exploration.py` |
| POST | `/exploration/{session_id}/flows/{flow_id}/reject` | `orchestrator/api/exploration.py` |
| POST | `/exploration/{session_id}/generate-api-specs` | `orchestrator/api/exploration.py` |
| POST | `/exploration/{session_id}/generate-api-tests` | `orchestrator/api/exploration.py` |
| GET | `/exploration/{session_id}/issues` | `orchestrator/api/exploration.py` |
| GET | `/exploration/{session_id}/results` | `orchestrator/api/exploration.py` |
| POST | `/exploration/{session_id}/stop` | `orchestrator/api/exploration.py` |
| POST | `/export/testrail` | `orchestrator/api/main.py` |
| POST | `/github/webhook/github` | `orchestrator/api/github_ci.py` |
| DELETE | `/github/{project_id}/config` | `orchestrator/api/github_ci.py` |
| GET | `/github/{project_id}/config` | `orchestrator/api/github_ci.py` |
| POST | `/github/{project_id}/config` | `orchestrator/api/github_ci.py` |
| GET | `/github/{project_id}/pipelines` | `orchestrator/api/github_ci.py` |
| GET | `/github/{project_id}/pipelines/{pipeline_mapping_id}` | `orchestrator/api/github_ci.py` |
| GET | `/github/{project_id}/pr-advisor/analyses` | `orchestrator/api/github_ci.py` |
| GET | `/github/{project_id}/pr-advisor/analyses/{analysis_id}` | `orchestrator/api/github_ci.py` |
| POST | `/github/{project_id}/pr-advisor/analyses/{analysis_id}/run` | `orchestrator/api/github_ci.py` |
| POST | `/github/{project_id}/pr-advisor/analyze` | `orchestrator/api/github_ci.py` |
| GET | `/github/{project_id}/pull-requests` | `orchestrator/api/github_ci.py` |
| GET | `/github/{project_id}/quality-gates/config` | `orchestrator/api/github_ci.py` |
| PUT | `/github/{project_id}/quality-gates/config` | `orchestrator/api/github_ci.py` |
| GET | `/github/{project_id}/quality-gates/pr` | `orchestrator/api/github_ci.py` |
| POST | `/github/{project_id}/quality-gates/pr/start` | `orchestrator/api/github_ci.py` |
| GET | `/github/{project_id}/quality-gates/pr/status` | `orchestrator/api/github_ci.py` |
| GET | `/github/{project_id}/quality-gates/pr/{analysis_id}` | `orchestrator/api/github_ci.py` |
| GET | `/github/{project_id}/remote-repos` | `orchestrator/api/github_ci.py` |
| GET | `/github/{project_id}/remote-workflows` | `orchestrator/api/github_ci.py` |
| POST | `/github/{project_id}/repository-index` | `orchestrator/api/github_ci.py` |
| GET | `/github/{project_id}/repository-index/latest` | `orchestrator/api/github_ci.py` |
| POST | `/github/{project_id}/sync-runs` | `orchestrator/api/github_ci.py` |
| POST | `/github/{project_id}/test-connection` | `orchestrator/api/github_ci.py` |
| POST | `/github/{project_id}/trigger-workflow` | `orchestrator/api/github_ci.py` |
| POST | `/gitlab/webhook/gitlab` | `orchestrator/api/gitlab_ci.py` |
| DELETE | `/gitlab/{project_id}/config` | `orchestrator/api/gitlab_ci.py` |
| GET | `/gitlab/{project_id}/config` | `orchestrator/api/gitlab_ci.py` |
| POST | `/gitlab/{project_id}/config` | `orchestrator/api/gitlab_ci.py` |
| GET | `/gitlab/{project_id}/pipelines` | `orchestrator/api/gitlab_ci.py` |
| GET | `/gitlab/{project_id}/pipelines/{mapping_id}` | `orchestrator/api/gitlab_ci.py` |
| GET | `/gitlab/{project_id}/remote-projects` | `orchestrator/api/gitlab_ci.py` |
| POST | `/gitlab/{project_id}/test-connection` | `orchestrator/api/gitlab_ci.py` |
| POST | `/gitlab/{project_id}/trigger-pipeline` | `orchestrator/api/gitlab_ci.py` |
| GET | `/health` | `orchestrator/api/main.py` |
| GET | `/health/alerts` | `orchestrator/api/health.py` |
| GET | `/health/archival/stats` | `orchestrator/api/health.py` |
| GET | `/health/backup` | `orchestrator/api/health.py` |
| GET | `/health/storage` | `orchestrator/api/health.py` |
| POST | `/health/storage/record` | `orchestrator/api/health.py` |
| POST | `/import/testrail` | `orchestrator/api/main.py` |
| GET | `/jira/{project_id}/bug-report-jobs/{job_id}` | `orchestrator/api/jira.py` |
| DELETE | `/jira/{project_id}/config` | `orchestrator/api/jira.py` |
| GET | `/jira/{project_id}/config` | `orchestrator/api/jira.py` |
| POST | `/jira/{project_id}/config` | `orchestrator/api/jira.py` |
| POST | `/jira/{project_id}/create-issue` | `orchestrator/api/jira.py` |
| POST | `/jira/{project_id}/generate-bug-report/{run_id}` | `orchestrator/api/jira.py` |
| GET | `/jira/{project_id}/issues` | `orchestrator/api/jira.py` |
| GET | `/jira/{project_id}/issues/{run_id}` | `orchestrator/api/jira.py` |
| GET | `/jira/{project_id}/remote-issue-types/{jira_project_key}` | `orchestrator/api/jira.py` |
| GET | `/jira/{project_id}/remote-projects` | `orchestrator/api/jira.py` |
| POST | `/jira/{project_id}/test-connection` | `orchestrator/api/jira.py` |
| GET | `/llm-testing/analytics/cost-tracking` | `orchestrator/api/llm_testing.py` |
| GET | `/llm-testing/analytics/dataset-performance` | `orchestrator/api/llm_testing.py` |
| GET | `/llm-testing/analytics/dataset-trends` | `orchestrator/api/llm_testing.py` |
| GET | `/llm-testing/analytics/golden-dashboard` | `orchestrator/api/llm_testing.py` |
| GET | `/llm-testing/analytics/latency-distribution` | `orchestrator/api/llm_testing.py` |
| GET | `/llm-testing/analytics/overview` | `orchestrator/api/llm_testing.py` |
| GET | `/llm-testing/analytics/regressions` | `orchestrator/api/llm_testing.py` |
| GET | `/llm-testing/analytics/trends` | `orchestrator/api/llm_testing.py` |
| POST | `/llm-testing/bulk-compare` | `orchestrator/api/llm_testing.py` |
| POST | `/llm-testing/bulk-run` | `orchestrator/api/llm_testing.py` |
| POST | `/llm-testing/compare` | `orchestrator/api/llm_testing.py` |
| GET | `/llm-testing/comparisons` | `orchestrator/api/llm_testing.py` |
| GET | `/llm-testing/comparisons/{comparison_id}` | `orchestrator/api/llm_testing.py` |
| GET | `/llm-testing/comparisons/{comparison_id}/matrix` | `orchestrator/api/llm_testing.py` |
| GET | `/llm-testing/datasets` | `orchestrator/api/llm_testing.py` |
| POST | `/llm-testing/datasets` | `orchestrator/api/llm_testing.py` |
| POST | `/llm-testing/datasets/from-spec/{spec_name}` | `orchestrator/api/llm_testing.py` |
| POST | `/llm-testing/datasets/import-csv` | `orchestrator/api/llm_testing.py` |
| DELETE | `/llm-testing/datasets/{dataset_id}` | `orchestrator/api/llm_testing.py` |
| GET | `/llm-testing/datasets/{dataset_id}` | `orchestrator/api/llm_testing.py` |
| PUT | `/llm-testing/datasets/{dataset_id}` | `orchestrator/api/llm_testing.py` |
| POST | `/llm-testing/datasets/{dataset_id}/augment` | `orchestrator/api/llm_testing.py` |
| POST | `/llm-testing/datasets/{dataset_id}/augment/{job_id}/accept` | `orchestrator/api/llm_testing.py` |
| POST | `/llm-testing/datasets/{dataset_id}/cases` | `orchestrator/api/llm_testing.py` |
| DELETE | `/llm-testing/datasets/{dataset_id}/cases/{case_id}` | `orchestrator/api/llm_testing.py` |
| PUT | `/llm-testing/datasets/{dataset_id}/cases/{case_id}` | `orchestrator/api/llm_testing.py` |
| POST | `/llm-testing/datasets/{dataset_id}/compare` | `orchestrator/api/llm_testing.py` |
| GET | `/llm-testing/datasets/{dataset_id}/diff` | `orchestrator/api/llm_testing.py` |
| POST | `/llm-testing/datasets/{dataset_id}/duplicate` | `orchestrator/api/llm_testing.py` |
| GET | `/llm-testing/datasets/{dataset_id}/export` | `orchestrator/api/llm_testing.py` |
| POST | `/llm-testing/datasets/{dataset_id}/golden` | `orchestrator/api/llm_testing.py` |
| POST | `/llm-testing/datasets/{dataset_id}/run` | `orchestrator/api/llm_testing.py` |
| POST | `/llm-testing/datasets/{dataset_id}/to-spec` | `orchestrator/api/llm_testing.py` |
| GET | `/llm-testing/datasets/{dataset_id}/versions` | `orchestrator/api/llm_testing.py` |
| POST | `/llm-testing/demo-content` | `orchestrator/api/llm_testing.py` |
| POST | `/llm-testing/generate-suite` | `orchestrator/api/llm_testing.py` |
| GET | `/llm-testing/jobs/{job_id}` | `orchestrator/api/llm_testing.py` |
| POST | `/llm-testing/openrouter/demo` | `orchestrator/api/llm_testing.py` |
| GET | `/llm-testing/openrouter/models` | `orchestrator/api/llm_testing.py` |
| GET | `/llm-testing/prompt-iterations` | `orchestrator/api/llm_testing.py` |
| POST | `/llm-testing/prompt-iterations` | `orchestrator/api/llm_testing.py` |
| GET | `/llm-testing/prompt-iterations/{iteration_id}` | `orchestrator/api/llm_testing.py` |
| GET | `/llm-testing/providers` | `orchestrator/api/llm_testing.py` |
| POST | `/llm-testing/providers` | `orchestrator/api/llm_testing.py` |
| DELETE | `/llm-testing/providers/{provider_id}` | `orchestrator/api/llm_testing.py` |
| PUT | `/llm-testing/providers/{provider_id}` | `orchestrator/api/llm_testing.py` |
| POST | `/llm-testing/providers/{provider_id}/health-check` | `orchestrator/api/llm_testing.py` |
| POST | `/llm-testing/run` | `orchestrator/api/llm_testing.py` |
| GET | `/llm-testing/runs` | `orchestrator/api/llm_testing.py` |
| GET | `/llm-testing/runs/{run_id}` | `orchestrator/api/llm_testing.py` |
| GET | `/llm-testing/runs/{run_id}/results` | `orchestrator/api/llm_testing.py` |
| GET | `/llm-testing/schedules` | `orchestrator/api/llm_testing.py` |
| POST | `/llm-testing/schedules` | `orchestrator/api/llm_testing.py` |
| DELETE | `/llm-testing/schedules/{schedule_id}` | `orchestrator/api/llm_testing.py` |
| GET | `/llm-testing/schedules/{schedule_id}` | `orchestrator/api/llm_testing.py` |
| PUT | `/llm-testing/schedules/{schedule_id}` | `orchestrator/api/llm_testing.py` |
| POST | `/llm-testing/schedules/{schedule_id}/run-now` | `orchestrator/api/llm_testing.py` |
| GET | `/llm-testing/specs` | `orchestrator/api/llm_testing.py` |
| POST | `/llm-testing/specs` | `orchestrator/api/llm_testing.py` |
| DELETE | `/llm-testing/specs/{name}` | `orchestrator/api/llm_testing.py` |
| GET | `/llm-testing/specs/{name}` | `orchestrator/api/llm_testing.py` |
| PUT | `/llm-testing/specs/{name}` | `orchestrator/api/llm_testing.py` |
| POST | `/llm-testing/specs/{name}/suggest-improvements` | `orchestrator/api/llm_testing.py` |
| GET | `/llm-testing/specs/{name}/versions` | `orchestrator/api/llm_testing.py` |
| POST | `/llm-testing/specs/{name}/versions` | `orchestrator/api/llm_testing.py` |
| GET | `/llm-testing/specs/{name}/versions/{version}` | `orchestrator/api/llm_testing.py` |
| POST | `/llm-testing/specs/{name}/versions/{version}/restore` | `orchestrator/api/llm_testing.py` |
| GET | `/load-testing/dashboard` | `orchestrator/api/load_testing.py` |
| POST | `/load-testing/force-unlock` | `orchestrator/api/load_testing.py` |
| POST | `/load-testing/generate` | `orchestrator/api/load_testing.py` |
| GET | `/load-testing/jobs` | `orchestrator/api/load_testing.py` |
| GET | `/load-testing/jobs/{job_id}` | `orchestrator/api/load_testing.py` |
| GET | `/load-testing/jobs/{job_id}/logs` | `orchestrator/api/load_testing.py` |
| POST | `/load-testing/run` | `orchestrator/api/load_testing.py` |
| POST | `/load-testing/run-from-spec` | `orchestrator/api/load_testing.py` |
| GET | `/load-testing/runs` | `orchestrator/api/load_testing.py` |
| GET | `/load-testing/runs/compare` | `orchestrator/api/load_testing.py` |
| GET | `/load-testing/runs/latest-by-spec` | `orchestrator/api/load_testing.py` |
| GET | `/load-testing/runs/trends` | `orchestrator/api/load_testing.py` |
| GET | `/load-testing/runs/{run_id}` | `orchestrator/api/load_testing.py` |
| POST | `/load-testing/runs/{run_id}/analyze` | `orchestrator/api/load_testing.py` |
| POST | `/load-testing/runs/{run_id}/stop` | `orchestrator/api/load_testing.py` |
| GET | `/load-testing/runs/{run_id}/timeseries` | `orchestrator/api/load_testing.py` |
| GET | `/load-testing/scripts` | `orchestrator/api/load_testing.py` |
| GET | `/load-testing/scripts/{name}` | `orchestrator/api/load_testing.py` |
| GET | `/load-testing/scripts/{name}/download` | `orchestrator/api/load_testing.py` |
| GET | `/load-testing/specs` | `orchestrator/api/load_testing.py` |
| POST | `/load-testing/specs` | `orchestrator/api/load_testing.py` |
| DELETE | `/load-testing/specs/{name}` | `orchestrator/api/load_testing.py` |
| GET | `/load-testing/specs/{name}` | `orchestrator/api/load_testing.py` |
| PUT | `/load-testing/specs/{name}` | `orchestrator/api/load_testing.py` |
| GET | `/load-testing/status` | `orchestrator/api/load_testing.py` |
| GET | `/load-testing/system-limits` | `orchestrator/api/load_testing.py` |
| GET | `/projects` | `orchestrator/api/projects.py` |
| POST | `/projects` | `orchestrator/api/projects.py` |
| DELETE | `/projects/{project_id}` | `orchestrator/api/projects.py` |
| GET | `/projects/{project_id}` | `orchestrator/api/projects.py` |
| PUT | `/projects/{project_id}` | `orchestrator/api/projects.py` |
| POST | `/projects/{project_id}/assign-spec` | `orchestrator/api/projects.py` |
| POST | `/projects/{project_id}/bulk-assign-specs` | `orchestrator/api/projects.py` |
| GET | `/projects/{project_id}/ci/audit-events` | `orchestrator/api/ci_control.py` |
| GET | `/projects/{project_id}/ci/generated-tests` | `orchestrator/api/ci_control.py` |
| GET | `/projects/{project_id}/ci/providers` | `orchestrator/api/ci_control.py` |
| PATCH | `/projects/{project_id}/ci/providers/defaults` | `orchestrator/api/ci_control.py` |
| GET | `/projects/{project_id}/ci/runs` | `orchestrator/api/ci_control.py` |
| POST | `/projects/{project_id}/ci/runs/sync` | `orchestrator/api/ci_control.py` |
| GET | `/projects/{project_id}/ci/runs/{provider}/{mapping_id}` | `orchestrator/api/ci_control.py` |
| POST | `/projects/{project_id}/ci/runs/{provider}/{mapping_id}/cancel` | `orchestrator/api/ci_control.py` |
| GET | `/projects/{project_id}/ci/runs/{provider}/{mapping_id}/logs` | `orchestrator/api/ci_control.py` |
| POST | `/projects/{project_id}/ci/runs/{provider}/{mapping_id}/rerun` | `orchestrator/api/ci_control.py` |
| GET | `/projects/{project_id}/ci/test-subsets` | `orchestrator/api/ci_control.py` |
| POST | `/projects/{project_id}/ci/test-subsets` | `orchestrator/api/ci_control.py` |
| DELETE | `/projects/{project_id}/ci/test-subsets/{subset_id}` | `orchestrator/api/ci_control.py` |
| GET | `/projects/{project_id}/ci/test-subsets/{subset_id}` | `orchestrator/api/ci_control.py` |
| PATCH | `/projects/{project_id}/ci/test-subsets/{subset_id}` | `orchestrator/api/ci_control.py` |
| POST | `/projects/{project_id}/ci/test-subsets/{subset_id}/dispatch` | `orchestrator/api/ci_control.py` |
| POST | `/projects/{project_id}/ci/test-subsets/{subset_id}/preview` | `orchestrator/api/ci_control.py` |
| POST | `/projects/{project_id}/ci/test-subsets/{subset_id}/pull-request` | `orchestrator/api/ci_control.py` |
| POST | `/projects/{project_id}/ci/workflow-change-requests` | `orchestrator/api/ci_control.py` |
| POST | `/projects/{project_id}/ci/workflow-change-requests/{change_id}/pull-request` | `orchestrator/api/ci_control.py` |
| GET | `/projects/{project_id}/ci/workflows` | `orchestrator/api/ci_control.py` |
| POST | `/projects/{project_id}/ci/workflows/dispatch` | `orchestrator/api/ci_control.py` |
| GET | `/projects/{project_id}/credentials` | `orchestrator/api/projects.py` |
| POST | `/projects/{project_id}/credentials` | `orchestrator/api/projects.py` |
| DELETE | `/projects/{project_id}/credentials/{credential_key}` | `orchestrator/api/projects.py` |
| GET | `/projects/{project_id}/members` | `orchestrator/api/projects.py` |
| POST | `/projects/{project_id}/members` | `orchestrator/api/projects.py` |
| DELETE | `/projects/{project_id}/members/{user_id}` | `orchestrator/api/projects.py` |
| PUT | `/projects/{project_id}/members/{user_id}` | `orchestrator/api/projects.py` |
| GET | `/projects/{project_id}/my-role` | `orchestrator/api/projects.py` |
| GET | `/queue-status` | `orchestrator/api/main.py` |
| POST | `/queue/clear` | `orchestrator/api/main.py` |
| GET | `/recordings` | `orchestrator/api/recordings.py` |
| POST | `/recordings/start` | `orchestrator/api/recordings.py` |
| GET | `/recordings/{recording_id}` | `orchestrator/api/recordings.py` |
| GET | `/recordings/{recording_id}/code` | `orchestrator/api/recordings.py` |
| POST | `/recordings/{recording_id}/import` | `orchestrator/api/recordings.py` |
| POST | `/recordings/{recording_id}/stop` | `orchestrator/api/recordings.py` |
| GET | `/regression/batches` | `orchestrator/api/regression.py` |
| POST | `/regression/batches/compare` | `orchestrator/api/regression.py` |
| GET | `/regression/batches/trend` | `orchestrator/api/regression.py` |
| DELETE | `/regression/batches/{batch_id}` | `orchestrator/api/regression.py` |
| GET | `/regression/batches/{batch_id}` | `orchestrator/api/regression.py` |
| PATCH | `/regression/batches/{batch_id}` | `orchestrator/api/regression.py` |
| POST | `/regression/batches/{batch_id}/cancel` | `orchestrator/api/regression.py` |
| GET | `/regression/batches/{batch_id}/error-summary` | `orchestrator/api/regression.py` |
| GET | `/regression/batches/{batch_id}/export` | `orchestrator/api/regression.py` |
| PATCH | `/regression/batches/{batch_id}/refresh` | `orchestrator/api/regression.py` |
| POST | `/regression/batches/{batch_id}/rerun-failed` | `orchestrator/api/regression.py` |
| GET | `/regression/debug/batch/{batch_id}/test-counts` | `orchestrator/api/regression.py` |
| GET | `/regression/debug/test-counts` | `orchestrator/api/regression.py` |
| GET | `/regression/flaky-tests` | `orchestrator/api/regression.py` |
| GET | `/regression/spec-history` | `orchestrator/api/regression.py` |
| GET | `/requirements` | `orchestrator/api/requirements.py` |
| POST | `/requirements` | `orchestrator/api/requirements.py` |
| POST | `/requirements/bulk` | `orchestrator/api/requirements.py` |
| GET | `/requirements/bulk-generate-jobs/{job_id}` | `orchestrator/api/requirements.py` |
| POST | `/requirements/bulk-generate-specs` | `orchestrator/api/requirements.py` |
| GET | `/requirements/categories/list` | `orchestrator/api/requirements.py` |
| POST | `/requirements/check-duplicate` | `orchestrator/api/requirements.py` |
| GET | `/requirements/duplicates` | `orchestrator/api/requirements.py` |
| POST | `/requirements/generate` | `orchestrator/api/requirements.py` |
| GET | `/requirements/generate-jobs/{job_id}` | `orchestrator/api/requirements.py` |
| GET | `/requirements/health` | `orchestrator/api/requirements.py` |
| POST | `/requirements/merge` | `orchestrator/api/requirements.py` |
| POST | `/requirements/review/decisions` | `orchestrator/api/requirements.py` |
| GET | `/requirements/stats` | `orchestrator/api/requirements.py` |
| DELETE | `/requirements/{req_id}` | `orchestrator/api/requirements.py` |
| GET | `/requirements/{req_id}` | `orchestrator/api/requirements.py` |
| PUT | `/requirements/{req_id}` | `orchestrator/api/requirements.py` |
| POST | `/requirements/{req_id}/confirm` | `orchestrator/api/requirements.py` |
| POST | `/requirements/{req_id}/generate-spec` | `orchestrator/api/requirements.py` |
| POST | `/requirements/{req_id}/mark-stale` | `orchestrator/api/requirements.py` |
| POST | `/requirements/{req_id}/reject` | `orchestrator/api/requirements.py` |
| GET | `/requirements/{req_id}/spec-status` | `orchestrator/api/requirements.py` |
| GET | `/rtm` | `orchestrator/api/rtm.py` |
| GET | `/rtm/coverage` | `orchestrator/api/rtm.py` |
| POST | `/rtm/entry` | `orchestrator/api/rtm.py` |
| DELETE | `/rtm/entry/{entry_id}` | `orchestrator/api/rtm.py` |
| GET | `/rtm/export/{format}` | `orchestrator/api/rtm.py` |
| GET | `/rtm/gaps` | `orchestrator/api/rtm.py` |
| POST | `/rtm/generate` | `orchestrator/api/rtm.py` |
| GET | `/rtm/generate-jobs/{job_id}` | `orchestrator/api/rtm.py` |
| GET | `/rtm/requirement/{req_id}/tests` | `orchestrator/api/rtm.py` |
| POST | `/rtm/snapshot` | `orchestrator/api/rtm.py` |
| GET | `/rtm/snapshot/{snapshot_id}` | `orchestrator/api/rtm.py` |
| GET | `/rtm/snapshots` | `orchestrator/api/rtm.py` |
| GET | `/rtm/test/{test_name}/requirements` | `orchestrator/api/rtm.py` |
| GET | `/rtm/trend` | `orchestrator/api/rtm.py` |
| GET | `/runs` | `orchestrator/api/main.py` |
| POST | `/runs` | `orchestrator/api/main.py` |
| POST | `/runs/bulk` | `orchestrator/api/main.py` |
| DELETE | `/runs/{id}` | `orchestrator/api/main.py` |
| GET | `/runs/{id}` | `orchestrator/api/main.py` |
| POST | `/runs/{id}/agentic-summary` | `orchestrator/api/main.py` |
| GET | `/runs/{id}/log/stream` | `orchestrator/api/main.py` |
| POST | `/runs/{id}/progress` | `orchestrator/api/main.py` |
| POST | `/runs/{id}/stop` | `orchestrator/api/main.py` |
| POST | `/scheduling/validate-cron` | `orchestrator/api/scheduling.py` |
| GET | `/scheduling/{project_id}/executions` | `orchestrator/api/scheduling.py` |
| GET | `/scheduling/{project_id}/schedules` | `orchestrator/api/scheduling.py` |
| POST | `/scheduling/{project_id}/schedules` | `orchestrator/api/scheduling.py` |
| DELETE | `/scheduling/{project_id}/schedules/{schedule_id}` | `orchestrator/api/scheduling.py` |
| GET | `/scheduling/{project_id}/schedules/{schedule_id}` | `orchestrator/api/scheduling.py` |
| PUT | `/scheduling/{project_id}/schedules/{schedule_id}` | `orchestrator/api/scheduling.py` |
| GET | `/scheduling/{project_id}/schedules/{schedule_id}/executions` | `orchestrator/api/scheduling.py` |
| GET | `/scheduling/{project_id}/schedules/{schedule_id}/next-runs` | `orchestrator/api/scheduling.py` |
| POST | `/scheduling/{project_id}/schedules/{schedule_id}/run-now` | `orchestrator/api/scheduling.py` |
| POST | `/scheduling/{project_id}/schedules/{schedule_id}/toggle` | `orchestrator/api/scheduling.py` |
| POST | `/security-testing/analyze/{run_id}` | `orchestrator/api/security_testing.py` |
| GET | `/security-testing/capabilities` | `orchestrator/api/security_testing.py` |
| GET | `/security-testing/findings` | `orchestrator/api/security_testing.py` |
| GET | `/security-testing/findings/summary` | `orchestrator/api/security_testing.py` |
| PATCH | `/security-testing/findings/{finding_id}/status` | `orchestrator/api/security_testing.py` |
| POST | `/security-testing/generate-spec` | `orchestrator/api/security_testing.py` |
| GET | `/security-testing/jobs/{job_id}` | `orchestrator/api/security_testing.py` |
| GET | `/security-testing/runs` | `orchestrator/api/security_testing.py` |
| GET | `/security-testing/runs/compare` | `orchestrator/api/security_testing.py` |
| GET | `/security-testing/runs/{run_id}` | `orchestrator/api/security_testing.py` |
| GET | `/security-testing/runs/{run_id}/findings` | `orchestrator/api/security_testing.py` |
| POST | `/security-testing/runs/{run_id}/stop` | `orchestrator/api/security_testing.py` |
| POST | `/security-testing/scan/full` | `orchestrator/api/security_testing.py` |
| POST | `/security-testing/scan/nuclei` | `orchestrator/api/security_testing.py` |
| POST | `/security-testing/scan/quick` | `orchestrator/api/security_testing.py` |
| POST | `/security-testing/scan/zap` | `orchestrator/api/security_testing.py` |
| GET | `/security-testing/specs` | `orchestrator/api/security_testing.py` |
| POST | `/security-testing/specs` | `orchestrator/api/security_testing.py` |
| DELETE | `/security-testing/specs/{name}` | `orchestrator/api/security_testing.py` |
| GET | `/security-testing/specs/{name}` | `orchestrator/api/security_testing.py` |
| PUT | `/security-testing/specs/{name}` | `orchestrator/api/security_testing.py` |
| GET | `/security-testing/targets` | `orchestrator/api/security_testing.py` |
| GET | `/settings` | `orchestrator/api/settings.py` |
| POST | `/settings` | `orchestrator/api/settings.py` |
| POST | `/settings/test-connection` | `orchestrator/api/settings.py` |
| GET | `/spec-metadata` | `orchestrator/api/main.py` |
| GET | `/spec-metadata/{spec_name}` | `orchestrator/api/main.py` |
| PUT | `/spec-metadata/{spec_name}` | `orchestrator/api/main.py` |
| GET | `/specs` | `orchestrator/api/main.py` |
| POST | `/specs` | `orchestrator/api/main.py` |
| GET | `/specs/automated` | `orchestrator/api/main.py` |
| POST | `/specs/create-folder` | `orchestrator/api/main.py` |
| DELETE | `/specs/folder/{folder_path}` | `orchestrator/api/main.py` |
| GET | `/specs/folders` | `orchestrator/api/main.py` |
| GET | `/specs/list` | `orchestrator/api/main.py` |
| POST | `/specs/move` | `orchestrator/api/main.py` |
| POST | `/specs/register-folder` | `orchestrator/api/main.py` |
| POST | `/specs/rename` | `orchestrator/api/main.py` |
| POST | `/specs/split` | `orchestrator/api/main.py` |
| DELETE | `/specs/{name}` | `orchestrator/api/main.py` |
| GET | `/specs/{name}` | `orchestrator/api/main.py` |
| PUT | `/specs/{name}` | `orchestrator/api/main.py` |
| GET | `/specs/{name}/generated-code` | `orchestrator/api/main.py` |
| PUT | `/specs/{name}/generated-code` | `orchestrator/api/main.py` |
| GET | `/specs/{name}/info` | `orchestrator/api/main.py` |
| POST | `/stop-all` | `orchestrator/api/main.py` |
| DELETE | `/testrail/{project_id}/config` | `orchestrator/api/testrail.py` |
| GET | `/testrail/{project_id}/config` | `orchestrator/api/testrail.py` |
| POST | `/testrail/{project_id}/config` | `orchestrator/api/testrail.py` |
| GET | `/testrail/{project_id}/mappings` | `orchestrator/api/testrail.py` |
| DELETE | `/testrail/{project_id}/mappings/{mapping_id}` | `orchestrator/api/testrail.py` |
| POST | `/testrail/{project_id}/push-cases` | `orchestrator/api/testrail.py` |
| GET | `/testrail/{project_id}/remote-projects` | `orchestrator/api/testrail.py` |
| GET | `/testrail/{project_id}/remote-suites/{tr_project_id}` | `orchestrator/api/testrail.py` |
| GET | `/testrail/{project_id}/sync-preview/{batch_id}` | `orchestrator/api/testrail.py` |
| POST | `/testrail/{project_id}/sync-results` | `orchestrator/api/testrail.py` |
| POST | `/testrail/{project_id}/test-connection` | `orchestrator/api/testrail.py` |
| GET | `/users` | `orchestrator/api/users.py` |
| POST | `/users` | `orchestrator/api/users.py` |
| DELETE | `/users/{user_id}` | `orchestrator/api/users.py` |
| GET | `/users/{user_id}` | `orchestrator/api/users.py` |
| PUT | `/users/{user_id}` | `orchestrator/api/users.py` |
| GET | `/users/{user_id}/projects` | `orchestrator/api/users.py` |
| DELETE | `/users/{user_id}/projects/{project_id}` | `orchestrator/api/users.py` |
| POST | `/users/{user_id}/projects/{project_id}` | `orchestrator/api/users.py` |
| GET | `/workflows` | `orchestrator/api/workflows.py` |
| GET | `/workflows/admin/step-types` | `orchestrator/api/workflows.py` |
| GET | `/workflows/analytics` | `orchestrator/api/workflows.py` |
| GET | `/workflows/catalog` | `orchestrator/api/workflows.py` |
| GET | `/workflows/definitions` | `orchestrator/api/workflows.py` |
| POST | `/workflows/definitions` | `orchestrator/api/workflows.py` |
| DELETE | `/workflows/definitions/{definition_id}` | `orchestrator/api/workflows.py` |
| GET | `/workflows/definitions/{definition_id}` | `orchestrator/api/workflows.py` |
| PUT | `/workflows/definitions/{definition_id}` | `orchestrator/api/workflows.py` |
| POST | `/workflows/definitions/{definition_id}/duplicate` | `orchestrator/api/workflows.py` |
| GET | `/workflows/definitions/{definition_id}/export` | `orchestrator/api/workflows.py` |
| GET | `/workflows/definitions/{definition_id}/revisions` | `orchestrator/api/workflows.py` |
| GET | `/workflows/definitions/{definition_id}/revisions/{version}` | `orchestrator/api/workflows.py` |
| POST | `/workflows/definitions/{definition_id}/revisions/{version}/rollback` | `orchestrator/api/workflows.py` |
| GET | `/workflows/definitions/{definition_id}/revisions/{version}/rollback-preview` | `orchestrator/api/workflows.py` |
| GET | `/workflows/definitions/{definition_id}/runs` | `orchestrator/api/workflows.py` |
| POST | `/workflows/definitions/{definition_id}/runs` | `orchestrator/api/workflows.py` |
| GET | `/workflows/events` | `orchestrator/api/workflows.py` |
| POST | `/workflows/import` | `orchestrator/api/workflows.py` |
| POST | `/workflows/import/validate` | `orchestrator/api/workflows.py` |
| GET | `/workflows/notifications` | `orchestrator/api/workflows.py` |
| POST | `/workflows/notifications/{notification_id}/read` | `orchestrator/api/workflows.py` |
| GET | `/workflows/runs` | `orchestrator/api/workflows.py` |
| GET | `/workflows/runs/{run_id}` | `orchestrator/api/workflows.py` |
| POST | `/workflows/runs/{run_id}/cancel` | `orchestrator/api/workflows.py` |
| GET | `/workflows/runs/{run_id}/debug` | `orchestrator/api/workflows.py` |
| GET | `/workflows/runs/{run_id}/diagnostics` | `orchestrator/api/workflows.py` |
| POST | `/workflows/runs/{run_id}/pause` | `orchestrator/api/workflows.py` |
| POST | `/workflows/runs/{run_id}/resume` | `orchestrator/api/workflows.py` |
| GET | `/workflows/runs/{run_id}/steps` | `orchestrator/api/workflows.py` |
| POST | `/workflows/runs/{run_id}/steps/{step_id}/retry` | `orchestrator/api/workflows.py` |
| POST | `/workflows/runs/{run_id}/steps/{step_id}/skip` | `orchestrator/api/workflows.py` |
| GET | `/workflows/schedules` | `orchestrator/api/workflows.py` |
| POST | `/workflows/schedules` | `orchestrator/api/workflows.py` |
| DELETE | `/workflows/schedules/{schedule_id}` | `orchestrator/api/workflows.py` |
| PUT | `/workflows/schedules/{schedule_id}` | `orchestrator/api/workflows.py` |
| GET | `/workflows/schedules/{schedule_id}/executions` | `orchestrator/api/workflows.py` |
| POST | `/workflows/schedules/{schedule_id}/run-now` | `orchestrator/api/workflows.py` |
| GET | `/workflows/temporal/health` | `orchestrator/api/workflows.py` |
| POST | `/workflows/validate` | `orchestrator/api/workflows.py` |

## Additional Public API Routes

These routes are included in the generated public-route drift check and are grouped here when they do not yet have a richer narrative section above.

| Method | Path | Source |
|--------|------|--------|
| GET | `/api/prd/generation/{generation_id}/events` | `orchestrator/api/prd.py` |
| GET | `/api/prd/generation/{generation_id}/events/stream` | `orchestrator/api/prd.py` |
| POST | `/api/prd/{prd_project_id}/import-requirements` | `orchestrator/api/prd.py` |
| POST | `/api/agents/runs/{run_id}/report-items/{item_id}/generate-spec` | `orchestrator/api/main.py` |
| POST | `/api/agents/runs/{run_id}/report-requirements/import` | `orchestrator/api/main.py` |
| GET | `/autonomous/{project_id}/missions/{mission_id}/artifacts` | `orchestrator/api/autonomous.py` |
| POST | `/autopilot/recover-orphans` | `orchestrator/api/autopilot.py` |
| GET | `/autopilot/temporal/health` | `orchestrator/api/autopilot.py` |
| GET | `/autopilot/{session_id}/evidence` | `orchestrator/api/autopilot.py` |
| GET | `/autopilot/{session_id}/temporal` | `orchestrator/api/autopilot.py` |
| GET | `/projects/{project_id}/browser-auth-sessions` | `orchestrator/api/browser_auth_sessions.py` |
| POST | `/projects/{project_id}/browser-auth-sessions` | `orchestrator/api/browser_auth_sessions.py` |
| DELETE | `/projects/{project_id}/browser-auth-sessions/{session_id}` | `orchestrator/api/browser_auth_sessions.py` |
| PATCH | `/projects/{project_id}/browser-auth-sessions/{session_id}/default` | `orchestrator/api/browser_auth_sessions.py` |
| POST | `/projects/{project_id}/browser-auth-sessions/{session_id}/refresh` | `orchestrator/api/browser_auth_sessions.py` |
| POST | `/projects/{project_id}/browser-auth-sessions/{session_id}/validate` | `orchestrator/api/browser_auth_sessions.py` |
| GET | `/requirements/generate-spec-jobs/{job_id}` | `orchestrator/api/requirements.py` |
| POST | `/requirements/{req_id}/generate-spec-jobs` | `orchestrator/api/requirements.py` |
| GET | `/settings/runtime-chat` | `orchestrator/api/settings.py` |
| POST | `/settings/test-hermes` | `orchestrator/api/settings.py` |
| GET | `/test-data/datasets` | `orchestrator/api/test_data.py` |
| POST | `/test-data/datasets` | `orchestrator/api/test_data.py` |
| GET | `/test-data/datasets/{dataset_id}` | `orchestrator/api/test_data.py` |
| PUT | `/test-data/datasets/{dataset_id}` | `orchestrator/api/test_data.py` |
| DELETE | `/test-data/datasets/{dataset_id}` | `orchestrator/api/test_data.py` |
| GET | `/test-data/datasets/{dataset_id}/items` | `orchestrator/api/test_data.py` |
| POST | `/test-data/datasets/{dataset_id}/items` | `orchestrator/api/test_data.py` |
| PUT | `/test-data/datasets/{dataset_id}/items/{item_id}` | `orchestrator/api/test_data.py` |
| DELETE | `/test-data/datasets/{dataset_id}/items/{item_id}` | `orchestrator/api/test_data.py` |
| POST | `/test-data/resolve` | `orchestrator/api/test_data.py` |
| POST | `/test-data/resolve/spec` | `orchestrator/api/test_data.py` |

## Related

- [API Overview](api-overview.md)
- [Environment Variables](environment-variables.md)
