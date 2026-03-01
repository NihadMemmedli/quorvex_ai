# Dashboard Walkthrough

In this tutorial, you will start the Quorvex AI web dashboard, navigate its main sections, and learn how each page fits into the test management workflow.

## Prerequisites

- Quorvex AI installed and configured (complete [Your First Test in 10 Minutes](./getting-started.md) first)
- At least one test spec created and run (the getting-started tutorial covers this)

## Step 1: Start the Dashboard

Launch the services:

=== "Docker (Recommended)"

    ```bash
    make prod-dev
    ```

    This starts all services in Docker containers with your local code mounted:

    | Service | URL | Purpose |
    |---------|-----|---------|
    | Frontend | `http://localhost:3000` | Next.js dashboard |
    | Backend API | `http://localhost:8001` | FastAPI server |
    | API Docs | `http://localhost:8001/docs` | Swagger UI |
    | PostgreSQL | (internal) | Database |
    | Redis | (internal) | Job queue and rate limiting |
    | MinIO Console | `http://localhost:9001` | Object storage |
    | VNC View | `http://localhost:6080` | Live browser view |

=== "Local"

    ```bash
    make dev
    ```

    This starts the backend (port 8001) and frontend (port 3000) natively. Starts PostgreSQL via Docker if available, falls back to SQLite.

Open `http://localhost:3000` in your browser.

!!! tip
    Running with Docker? Use `make prod-logs` to tail service logs and `make prod-status` to check that all containers are healthy. For local mode, use `make logs` instead.

## Step 2: The Sidebar Navigation

The left sidebar organizes the dashboard into sections:

| Section | Page | Purpose |
|---------|------|---------|
| **Testing** | Specs | Create and manage test specifications |
| | Runs | View test execution history and details |
| | Regression | Batch execution of multiple tests |
| | Templates | Reusable spec fragments |
| **Discovery** | Exploration | AI-powered app discovery sessions |
| | Requirements | Structured requirements from exploration |
| | RTM | Requirements Traceability Matrix |
| | Coverage | Test coverage analysis and gap detection |
| **Specialized** | API Testing | HTTP/REST API test management |
| | Load Testing | K6-based performance testing |
| | Security Testing | Vulnerability scanning and triage |
| | Database Testing | PostgreSQL schema and data quality checks |
| | LLM Testing | AI model evaluation platform |
| **Operations** | Dashboard | Analytics and reporting overview |
| | Schedules | Cron-based automated test runs |
| | CI/CD | GitHub Actions and GitLab CI integration |
| | Analytics | Cross-feature trends and insights |
| **System** | Memory | Stored selector patterns from past runs |
| | PRD | PDF requirements document processing |
| | Settings | Project configuration and credentials |
| | Assistant | AI chat interface with tool access |

The **project selector** at the top of the sidebar lets you switch between projects. All pages filter data to the currently selected project.

## Step 3: Specs Page

Click **Specs** in the sidebar. This is where you manage test specifications.

**What you see:**

- A folder tree showing all specs organized by directory
- Each spec shows its type badge (`standard`, `api`, `template`), test count, and whether it has been automated
- A **search bar** at the top to find specs by name
- A **New Spec** button to create specs directly in the browser

**Try it:**

1. Click on a spec name to open its detail view.
2. The detail view shows the markdown content, metadata, and the generated Playwright code (if the spec has been run).
3. Click the **play button** next to a spec to start a test run.

!!! tip
    You can edit specs directly in the browser using the built-in Monaco editor. Changes are saved to disk automatically.

## Step 4: Runs Page

Click **Runs** in the sidebar. This page shows every test execution.

**What you see:**

- A list of runs with status indicators: queued (hourglass), running (spinner), passed (green check), failed (red X), error (warning)
- Each row shows the test name, timestamp, browser, and pipeline stage
- A **queue status bar** at the top shows active and queued runs
- Running tests display their current stage: planning, generating, testing, or healing

**Try it:**

1. Click on a completed run to see its detail page.
2. The detail page shows four tabs:
   - **Spec** -- the original markdown specification
   - **Code** -- the generated Playwright test
   - **Output** -- stdout/stderr from the test execution
   - **Plan** -- the structured test plan (JSON)
3. If the test was healed, a **Healing History** section shows each attempt.

## Step 5: Regression Page

Click **Regression** in the sidebar. This page enables batch test execution.

**What you see:**

- A list of all specs that have generated test code (automated specs)
- Checkboxes to select tests for a batch run
- A **Run Selected** button to start the batch
- A **Recent Batches** section showing past batch runs with pass/fail counts

**Try it:**

1. Select two or more specs using the checkboxes.
2. Enter a batch name (e.g., "Smoke Test Batch").
3. Click **Run Selected**.
4. Watch the batch progress in the Recent Batches section.
5. When complete, click the batch to see individual test results.

!!! tip
    Batch results can be exported as HTML, JSON, or CSV from the batch detail page. Use this for generating reports.

## Step 6: Exploration Page

Click **Exploration** in the sidebar. This manages AI-powered app discovery.

**What you see:**

- A **New Exploration** button to start a discovery session
- A list of past exploration sessions with their status, page count, and flow count
- Two tabs: **Sessions** (exploration history) and **Agent Runs** (background AI processing)

**Try it:**

1. Click **New Exploration**.
2. Enter a URL (e.g., `https://the-internet.herokuapp.com`).
3. Choose a strategy (breadth-first is a good default).
4. Set max interactions to `20` for a quick exploration.
5. Click **Start** and watch the live action log.

See the [App Exploration and Requirements](./first-exploration.md) tutorial for the full exploration-to-RTM workflow.

## Step 7: Dashboard (Analytics)

Click **Dashboard** in the sidebar. This is the reporting overview.

**What you see:**

- **Summary cards** at the top: Total Runs, Pass Rate, Avg Duration, Flaky Tests, Slowest Test
- **Charts** below:
  - Pass/Fail trends over time (bar chart)
  - Average duration trend (line chart)
  - Slowest tests (ranked list)
  - Flaky tests (tests with inconsistent results)
  - Top error categories (pie chart)
  - Healing success rate
  - Test growth over time

Use the **period selector** (7 days, 30 days, 90 days, 1 year) to adjust the time range.

!!! note
    Analytics data builds up over time as you run more tests. With only a few runs, the charts may look sparse. Run your specs regularly to see meaningful trends.

## Step 8: Settings Page

Click **Settings** in the sidebar. This configures the current project.

**Key sections:**

### LLM Configuration
Set the AI provider, API key, base URL, and model. These settings apply to the current project only.

### Execution Settings
- **Parallelism** -- max concurrent test runs (default: 5)
- **Memory enabled** -- toggle the selector pattern memory system

### Credentials
Manage per-project environment variables used by tests. Values are encrypted at rest. For example, add `LOGIN_PASSWORD` here and reference it as `{{LOGIN_PASSWORD}}` in your specs.

### Integrations
Configure TestRail, GitHub, GitLab, and Jira connections for the current project.

## Step 9: AI Assistant

Click **Assistant** in the sidebar (or the floating chat bubble on any page).

The AI assistant can:

- Answer questions about your test suite
- Help write specs
- Explain test failures
- Suggest improvements

Type a message and the assistant responds with context about your project.

## Step 10: Stop the Dashboard

When you are done, stop the services:

=== "Docker"

    ```bash
    make prod-down
    ```

=== "Local"

    ```bash
    make stop
    ```

## What You Learned

In this tutorial, you:

- Started the Quorvex AI dashboard using Docker (`make prod-dev`) with PostgreSQL, Redis, MinIO, and VNC running as services -- or locally with `make dev`
- Navigated the sidebar to understand the page structure
- Explored the Specs page for managing test specifications
- Viewed test execution history on the Runs page
- Started a batch regression run
- Initiated an AI exploration session
- Reviewed analytics on the Dashboard page
- Configured project settings and credentials
- Stopped services with `make prod-down` (Docker) or `make stop` (local)

## Next Steps

- [Your First API Test](./first-api-test.md) -- generate HTTP API tests from the dashboard
- [App Exploration and Requirements](./first-exploration.md) -- full exploration-to-RTM walkthrough
- [CI/CD Setup](./ci-cd-setup.md) -- automate test runs with GitHub Actions or GitLab CI
- [Web Dashboard Reference](../reference/web-dashboard.md) -- detailed reference for every page
