# Web Dashboard

Page-by-page reference for all Quorvex AI dashboard pages.

## Starting the Dashboard

```bash
make dev
```

Backend API: `http://localhost:8001` | Frontend: `http://localhost:3000`

## Dashboard Pages

| Page | URL Path | Description |
|------|----------|-------------|
| Dashboard | `/dashboard` | Analytics overview with pass/fail trends, duration charts, flaky tests, error categories, healing rates |
| Specs | `/specs` | Manage test specifications: folder tree, search, filter, create, edit, run, tag |
| Spec Detail | `/specs/{name}` | View spec markdown, metadata, generated code |
| New Spec | `/specs/new` | Create a new spec with markdown editor |
| Runs | `/runs` | List all test executions with status, stage, queue position |
| Run Detail | `/runs/{id}` | Spec content, generated code, test output, plan, artifacts, healing history |
| Regression | `/regression` | Batch test execution: select specs, configure batch, view results |
| Batch Detail | `/regression/batches/{id}` | Individual test results within a batch |
| Exploration | `/exploration` | AI-powered app discovery: start sessions, view flows, API endpoints |
| Requirements | `/requirements` | Manage requirements: CRUD, generate from exploration, category/priority charts |
| RTM | `/rtm` | Requirements Traceability Matrix: coverage status, filtering, export |
| Coverage | `/coverage` | Test coverage gaps, AI-suggested tests, gap prioritization |
| Memory | `/memory` | Selector patterns: browse, search, filter by action type, statistics |
| PRD | `/prd` | PDF upload, feature extraction, spec generation per feature |
| API Testing | `/api-testing` | HTTP/REST API test specs, OpenAPI import, run history |
| Load Testing | `/load-testing` | K6 load test specs, script generation, metrics, run comparison |
| Security Testing | `/security-testing` | Quick/Nuclei/ZAP scans, findings management, AI analysis |
| Database Testing | `/database-testing` | PostgreSQL connections, schema analysis, data quality checks |
| LLM Testing | `/llm-testing` | LLM evaluation: providers, specs, datasets, compare, analytics, prompts, schedules |
| Schedules | `/schedules` | Cron-based job scheduling for automated regression and LLM tests |
| CI/CD | `/ci-cd` | GitHub Actions and GitLab CI pipeline configuration |
| Analytics | `/analytics` | Cross-feature aggregated analytics |
| Templates | `/templates` | Manage reusable template files |
| Projects | `/projects` | Multi-tenant project management: create, switch, edit, delete |
| Settings | `/settings` | LLM config, execution settings, credentials, TestRail integration |
| Assistant | `/assistant` | AI chat interface with platform tool access |
| Login | `/login` | Email/password authentication (when auth is enabled) |
| Register | `/register` | New user registration (when auth and registration are enabled) |

## Admin Pages

Admin pages are available to superusers only.

| Page | URL Path | Description |
|------|----------|-------------|
| User Management | `/admin/users` | List users, manage roles and access |
| Admin Settings | `/admin/settings` | System-wide configuration, VNC settings |

## Dashboard Analytics Cards

| Card | Description |
|------|-------------|
| Total Runs | Number of test executions in the selected period |
| Pass Rate | Percentage of runs that passed |
| Avg Duration | Mean execution time across all runs |
| Flaky Tests | Tests that alternate between pass and fail |
| Slowest | Duration of the slowest individual test |

## Dashboard Charts

| Chart | Type | Description |
|-------|------|-------------|
| Pass/Fail Trends | Bar (daily) | Passed vs. failed runs per day |
| Average Duration | Line | Execution time trend over days |
| Slowest Tests (Top 10) | Ranked list | Longest-running tests |
| Flaky Tests | Table | Tests with inconsistent results and failure rate |
| Top Error Categories | Pie | Failures grouped by error type |
| Healing Success Rate | Bar + trend | Standard vs. Ralph healing success |
| Test Growth | Line | Specs, generated tests, passing tests over time |
| Pass Rate by Hour | Bar | Time-of-day reliability patterns |
| Failure Patterns | Table | Tests that commonly fail together |

## Period Selector

| Option | Range |
|--------|-------|
| 7 days | Last 7 days |
| 30 days | Last 30 days |
| 90 days | Last 90 days |
| 1 year | Last 365 days |

## Run Status Indicators

| Status | Indicator | Description |
|--------|-----------|-------------|
| Queued | Hourglass | Waiting for browser slot |
| Running | Spinner | Currently executing |
| Passed | Green check | Test passed |
| Failed | Red X | Test failed |
| Error | Warning icon | Pipeline error |
| Stopped | Stop icon | Manually cancelled |

## Run Stages

| Stage | Description |
|-------|-------------|
| Planning | AI agent exploring the app and building a plan |
| Generating | AI agent writing Playwright test code |
| Testing | Generated test executing |
| Healing | System attempting to fix failures (shows attempt number) |

## Authentication (When Enabled)

| Setting | Value |
|---------|-------|
| Login lockout | After 5 failed attempts |
| Session tokens | JWT with automatic refresh |
| Registration toggle | `ALLOW_REGISTRATION` env var |
| Auth enforcement | `REQUIRE_AUTH` env var |

## Related

- [API Overview](api-overview.md)
- [Environment Variables](environment-variables.md)
