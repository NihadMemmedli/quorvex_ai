<p align="center">
  <h1 align="center">Quorvex AI</h1>
  <p align="center">
    <strong>AI-Powered Test Automation Platform</strong>
  </p>
  <p align="center">
    Write tests in plain English. Get production-ready Playwright code automatically.
  </p>
  <p align="center">
    <a href="https://github.com/NihadMemmedli/quorvex_ai/actions/workflows/ci.yml"><img src="https://github.com/NihadMemmedli/quorvex_ai/actions/workflows/ci.yml/badge.svg" alt="CI"></a>
    <a href="LICENSE"><img src="https://img.shields.io/badge/License-MIT-blue.svg" alt="License: MIT"></a>
    <a href="https://www.python.org/downloads/"><img src="https://img.shields.io/badge/Python-3.10+-3776AB.svg?logo=python&logoColor=white" alt="Python 3.10+"></a>
    <a href="https://nodejs.org/"><img src="https://img.shields.io/badge/Node.js-20+-339933.svg?logo=nodedotjs&logoColor=white" alt="Node.js 20+"></a>
    <a href="https://playwright.dev/"><img src="https://img.shields.io/badge/Playwright-45ba4b.svg?logo=playwright&logoColor=white" alt="Playwright"></a>
    <a href="https://fastapi.tiangolo.com/"><img src="https://img.shields.io/badge/FastAPI-009688.svg?logo=fastapi&logoColor=white" alt="FastAPI"></a>
    <a href="https://nextjs.org/"><img src="https://img.shields.io/badge/Next.js-black.svg?logo=next.js&logoColor=white" alt="Next.js"></a>
    <a href="CONTRIBUTING.md"><img src="https://img.shields.io/badge/PRs-welcome-brightgreen.svg" alt="PRs Welcome"></a>
  </p>
</p>

---

Quorvex AI transforms natural language test specifications into validated, self-healing Playwright tests. Point an AI agent at your application, describe what to test in plain English, and get production-ready TypeScript test code that actually passes. When tests break due to UI changes, the self-healing pipeline automatically detects and fixes selector failures -- no manual maintenance required.

![Dashboard Screenshot](docs/assets/dashboard-screenshot.png)
*Web dashboard for managing specs, monitoring execution trends, and analyzing test results.*

---

## Features

### Core Test Automation
- **Natural Language to Playwright** -- Write test specs in markdown, get validated TypeScript tests
- **Self-Healing Tests** -- Automatic detection and repair of broken selectors and timeouts
- **Visual Regression Testing** -- Pixel-level screenshot comparison with baseline management
- **Template System** -- Reusable spec templates with `@include` directives and selector hints

### AI-Powered Discovery
- **App Exploration** -- Autonomous browser-based discovery of pages, flows, forms, and error states
- **Requirements Generation** -- AI extracts structured requirements from exploration data
- **Requirements Traceability Matrix (RTM)** -- Maps requirements to test specs with coverage scoring
- **Coverage Analysis** -- Identifies untested requirements and suggests new test specs

### Beyond UI Testing
- **API Testing** -- OpenAPI/Swagger import with AI-generated HTTP test suites and self-healing
- **Load Testing** -- K6-based performance testing with AI-generated scripts and distributed execution
- **Security Testing** -- Multi-tier scanning (quick checks, Nuclei, ZAP DAST) with AI-powered remediation
- **Database Testing** -- PostgreSQL schema analysis and data quality checks with AI suggestions
- **LLM Evaluation** -- Test AI providers against structured suites with A/B prompt comparison

### Enterprise Ready
- **Multi-Project Isolation** -- Separate specs, runs, and configurations per project
- **Authentication & RBAC** -- User management with role-based access control
- **CI/CD Integration** -- GitHub Actions and GitLab CI pipeline generation
- **TestRail & Jira** -- Bidirectional sync for test cases and issue tracking
- **Cron Scheduling** -- Automated regression runs with execution history
- **Browser Pool** -- Managed concurrent browser instances with FIFO queuing

---

## How It Works

Quorvex AI uses a multi-stage pipeline where an AI agent actively interacts with your application through a real browser at every step:

```
Markdown Spec --> Plan --> Generate --> Validate --> Heal (if needed)
```

1. **Plan** -- The AI reads your spec and explores the target application to build an execution plan
2. **Generate** -- Using the plan and live browser context, the AI writes Playwright TypeScript code
3. **Validate** -- The generated test is executed against the real application
4. **Heal** -- If validation fails, the AI debugs the failure and fixes the code automatically

The **Smart Check** system skips regeneration when valid code already exists, reuses passing tests, and only heals or regenerates when necessary.

---

## Quick Start

### Prerequisites

| Requirement | Version  | Required | Notes                                |
|-------------|----------|----------|--------------------------------------|
| Python      | 3.10+    | Yes      | Virtual environment recommended      |
| Node.js     | 20+      | Yes      | For Playwright and frontend          |
| Docker      | Latest   | Optional | For PostgreSQL in production mode     |

### Installation

```bash
# 1. Clone the repository
git clone https://github.com/NihadMemmedli/quorvex_ai.git
cd quorvex_ai

# 2. Run automated setup (Python venv, Node deps, Playwright browsers, database)
make setup

# 3. Configure your AI provider credentials
#    Edit .env and set ANTHROPIC_AUTH_TOKEN (see Configuration below)

# 4. Start the web dashboard
make dev

# 5. Open http://localhost:3000
```

### Your First Test

**Option A: Web Dashboard**

1. Open http://localhost:3000
2. Navigate to the Specs page
3. Create a new spec with this content:

```markdown
# Test: Login Form

## Description
Verify user can log in with valid credentials.

## Steps
1. Navigate to https://the-internet.herokuapp.com/login
2. Enter username "tomsmith"
3. Enter password "SuperSecretPassword!"
4. Click "Login"
5. Verify success message is visible

## Expected Outcome
- User sees a success flash message after login
```

4. Click "Run" to execute the pipeline

**Option B: CLI**

```bash
# Activate the virtual environment
source venv/bin/activate

# Run a spec through the native pipeline
python orchestrator/cli.py specs/your-test.md

# Run with hybrid healing for complex scenarios
python orchestrator/cli.py specs/your-test.md --hybrid
```

**Output** is stored in `runs/TIMESTAMP/` (plan, logs, generated code) and the final test goes to `tests/generated/`.

### Running Generated Tests

```bash
# Run all generated tests
npx playwright test

# Run a specific test
npx playwright test tests/generated/your-test.spec.ts
```

---

## Configuration

All configuration is managed through a `.env` file in the project root. Copy the example and edit:

```bash
cp .env.example .env
```

### AI Provider Setup

Quorvex AI requires an Anthropic-compatible API provider. Three options are supported:

#### Option 1: Anthropic Direct (Recommended)

```env
ANTHROPIC_AUTH_TOKEN=sk-ant-your-api-key
ANTHROPIC_BASE_URL=https://api.anthropic.com
ANTHROPIC_DEFAULT_SONNET_MODEL=claude-sonnet-4-20250514
```

Sign up at [console.anthropic.com](https://console.anthropic.com) to get an API key.

#### Option 2: OpenRouter (Free Models Available)

[OpenRouter](https://openrouter.ai) provides access to free and paid LLM models through an Anthropic-compatible API.

```env
ANTHROPIC_AUTH_TOKEN=sk-or-v1-your-openrouter-key
ANTHROPIC_BASE_URL=https://openrouter.ai/api
ANTHROPIC_DEFAULT_SONNET_MODEL=meta-llama/llama-3.2-3b-instruct:free
```

Popular free models on OpenRouter:

| Model | Provider | Context | Best For |
|-------|----------|---------|----------|
| `meta-llama/llama-3.2-3b-instruct:free` | Meta | 131k | General tasks |
| `google/gemini-2.0-flash-exp:free` | Google | 1M | Fast responses |
| `qwen/qwen-2.5-7b-instruct:free` | Alibaba | 32k | Coding assistance |

> Free models have rate limits. For production use, consider paid models or Anthropic direct.

#### Option 3: Z.ai

```env
ANTHROPIC_AUTH_TOKEN=your-z-ai-token
ANTHROPIC_BASE_URL=https://api.z.ai/api/anthropic
ANTHROPIC_DEFAULT_SONNET_MODEL=glm-4.7
```

See [Z.ai integration guide](https://docs.z.ai/scenario-example/develop-tools/claude) for setup instructions.

### Optional Configuration

```env
# Memory system embeddings (enables semantic search for selectors)
OPENAI_API_KEY=your-openai-key

# Database (SQLite by default, PostgreSQL for production)
DATABASE_URL=sqlite:///./test.db
# DATABASE_URL=postgresql://user:pass@localhost:5432/quorvex

# Authentication (disabled by default for local development)
JWT_SECRET_KEY=your-secret-key
REQUIRE_AUTH=false

# Browser pool
MAX_BROWSER_INSTANCES=5
BROWSER_SLOT_TIMEOUT=3600

# Agent timeouts (seconds)
AGENT_TIMEOUT_SECONDS=1800
```

For the complete list of environment variables, see the [Environment Variables Guide](docs/guides/environment-variables.md).

---

## Running Modes

### Development Mode (Recommended for getting started)

```bash
make dev
```

- Uses SQLite by default (no Docker needed)
- Hot-reload enabled for backend and frontend
- Backend API on http://localhost:8001, frontend on http://localhost:3000

### Production Mode (Docker)

```bash
make prod-dev
```

- Runs all services in Docker containers
- Uses PostgreSQL database with Alembic migrations
- Recommended for team environments

### CLI Mode (No dashboard)

```bash
source venv/bin/activate
python orchestrator/cli.py specs/your-test.md
```

- Direct command-line execution, no database required
- Artifacts stored in `runs/TIMESTAMP/`
- Useful for CI/CD pipelines

---

## Pipeline Modes

### Native Pipeline (Default)

The recommended pipeline. AI agents use a real browser at every stage for maximum reliability.

```bash
python orchestrator/cli.py specs/your-test.md
```

### Hybrid Mode

Native pipeline with extended healing. If the native healer (3 attempts) fails, escalates to up to 17 additional healing iterations.

```bash
python orchestrator/cli.py specs/your-test.md --hybrid
```

### PRD Pipeline

Convert a PDF product requirements document into test specs and then into tests.

```bash
python orchestrator/cli.py your-prd.pdf --prd
python orchestrator/cli.py your-prd.pdf --prd --feature "User Login"
```

### AI Exploration

Autonomously discover pages, user flows, API endpoints, and form behaviors.

```bash
python orchestrator/workflows/app_explorer.py --url https://example.com --max-interactions 50
```

---

## Secure Credential Handling

Quorvex AI never hardcodes secrets in generated tests.

1. Define secrets in `.env`:
   ```env
   LOGIN_PASSWORD=SuperSecretPassword!
   ```

2. Use placeholders in your spec:
   ```markdown
   1. Enter password "{{LOGIN_PASSWORD}}"
   ```

3. Generated code uses `process.env.LOGIN_PASSWORD` at runtime. Secrets are scrubbed from all logs and traces.

---

## Test Specification Format

Specs are markdown files in the `specs/` directory:

```markdown
# Test: Checkout Flow

## Description
Verify a user can complete the checkout process.

## Steps
1. Navigate to https://example.com/shop
2. Click the "Add to Cart" button
3. Navigate to the cart page
4. Click "Proceed to Checkout"
5. Enter shipping information
6. Verify the order confirmation appears

## Expected Outcome
- Order confirmation page is displayed with order number
```

### Template Includes

Reuse common flows across specs:

```markdown
## Steps
1. @include "templates/login.md"
2. Navigate to the dashboard
3. Verify the welcome message is visible
```

### Visual Regression

Add visual verification steps for pixel-level comparison:

```markdown
## Steps
1. Navigate to https://example.com
2. Verify visual layout
```

First run captures a baseline. Subsequent runs compare against it, highlighting pixel differences.

---

## Available Commands

```bash
make setup            # One-time setup (venv, deps, browsers, database)
make dev              # Start development server (backend + frontend)
make prod-dev         # Start production mode with Docker
make run SPEC=...     # Run a specific test spec
make test             # Run all Python tests
make lint             # Run linters (ruff + next lint)
make format           # Auto-format Python code
make check-env        # Validate environment configuration
make clean            # Remove run artifacts
make logs             # Tail backend and frontend logs
make stop             # Stop all running services

# Production
make prod-restart     # Restart backend (picks up code changes)
make prod-logs        # Tail production logs
make prod-status      # Show status of all services
make backup           # Database-only backup
make backup-full      # Full backup (DB + specs + tests + PRDs)
make health-check     # Hit all health endpoints

# Database migrations (PostgreSQL)
make db-migrate M="description"   # Generate new migration
make db-upgrade                   # Run pending migrations

# Load testing
make k6-workers-up                # Start K6 worker containers
make k6-workers-scale N=3         # Scale workers
make k6-workers-down              # Stop workers
```

---

## Architecture

```
quorvex_ai/
├── orchestrator/           # Python backend
│   ├── api/                # FastAPI endpoints (REST API)
│   ├── workflows/          # Pipeline stages (planner, generator, healer)
│   ├── services/           # Browser pool, scheduler, storage, queues
│   ├── memory/             # Vector store, graph store, exploration store
│   └── cli.py              # CLI entry point
├── web/                    # Next.js frontend (App Router)
│   └── src/app/(dashboard)/  # All dashboard pages
├── specs/                  # Input: markdown test specifications
├── tests/generated/        # Output: Playwright TypeScript tests
├── runs/                   # Execution artifacts (plans, logs, reports)
├── docs/                   # Documentation
└── docker/                 # Docker configurations
```

**Tech stack**: Python 3.10 + FastAPI (backend), Next.js 16 + React 19 + Tailwind CSS v4 (frontend), Playwright (browser automation + test runner), PostgreSQL or SQLite (database), Redis (optional, for queues and distributed execution), MinIO (optional, S3-compatible artifact storage).

---

## Documentation

Full documentation is available at **[nihadmemmedli.github.io/quorvex_ai](https://nihadmemmedli.github.io/quorvex_ai/)**.

To browse docs locally:

```bash
pip install -r requirements-docs.txt
mkdocs serve
# Open http://127.0.0.1:8000
```

| Section | Contents |
|---------|----------|
| [Documentation Hub](docs/README.md) | Start here -- overview and navigation |
| [Architecture](docs/architecture/) | System overview, pipeline flows, database schema |
| [API Reference](docs/api-reference/) | Complete endpoint catalog, conventions, error handling |
| [Guides](docs/guides/) | Getting started, deployment, environment variables, extending |
| [User Guide](docs/user-guide/) | Writing specs, dashboard walkthrough, pipeline selection |
| [Troubleshooting](docs/troubleshooting.md) | Expanded diagnostics and solutions |

---

## Troubleshooting

| Symptom | Solution |
|---------|----------|
| "ANTHROPIC_AUTH_TOKEN not set" | Check `.env` file, run `make check-env` |
| "Database connection refused" | Run `docker-compose up -d db` or use SQLite (default) |
| Generated test selector fails | Self-healer auto-fixes; use `--hybrid` for complex cases |
| "No target URL found in spec" | Spec must contain a URL (e.g., "Navigate to https://...") |
| Test timeout on complex pages | Use `--hybrid` or increase exploration depth |
| "Module not found" errors | Re-run `make setup` to reinstall dependencies |

For more diagnostics, see [docs/troubleshooting.md](docs/troubleshooting.md).

---

## Contributing

We welcome contributions of all kinds. See [CONTRIBUTING.md](CONTRIBUTING.md) for development setup, architecture overview, code style, and the pull request process.

Please read our [Code of Conduct](CODE_OF_CONDUCT.md) before participating.

---

## Security

To report a vulnerability, please see [SECURITY.md](SECURITY.md). Do **not** open a public issue for security concerns.

---

## Community

- [GitHub Issues](https://github.com/NihadMemmedli/quorvex_ai/issues) -- Bug reports and feature requests
- [GitHub Discussions](https://github.com/NihadMemmedli/quorvex_ai/discussions) -- Questions, ideas, and showcase
- [Contributing Guide](CONTRIBUTING.md) -- How to get involved
- [Changelog](CHANGELOG.md) -- Release history

---

## License

This project is licensed under the MIT License. See [LICENSE](LICENSE) for details.

Copyright 2026 Quorvex AI Contributors.
