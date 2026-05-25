<p align="center">
  <h1 align="center">Quorvex AI</h1>
  <p align="center">
    <strong>Self-hosted AI testing agents that turn specs into validated Playwright tests.</strong>
  </p>
  <p align="center">
    Generate code you can inspect, commit, and run in CI without runtime AI dependency.
  </p>
  <p align="center">
    <a href="https://github.com/NihadMemmedli/quorvex_ai/stargazers"><img src="https://img.shields.io/github/stars/NihadMemmedli/quorvex_ai?style=social" alt="GitHub Stars"></a>
    <a href="https://github.com/NihadMemmedli/quorvex_ai/network/members"><img src="https://img.shields.io/github/forks/NihadMemmedli/quorvex_ai?style=social" alt="GitHub Forks"></a>
  </p>
  <p align="center">
    <a href="https://github.com/NihadMemmedli/quorvex_ai/actions/workflows/ci.yml"><img src="https://github.com/NihadMemmedli/quorvex_ai/actions/workflows/ci.yml/badge.svg" alt="CI"></a>
    <a href="LICENSE"><img src="https://img.shields.io/badge/License-MIT-blue.svg" alt="License: MIT"></a>
    <a href="https://www.python.org/downloads/"><img src="https://img.shields.io/badge/Python-3.10+-3776AB.svg?logo=python&logoColor=white" alt="Python 3.10+"></a>
    <a href="https://nodejs.org/"><img src="https://img.shields.io/badge/Node.js-20+-339933.svg?logo=nodedotjs&logoColor=white" alt="Node.js 20+"></a>
    <a href="https://playwright.dev/"><img src="https://img.shields.io/badge/Playwright-45ba4b.svg?logo=playwright&logoColor=white" alt="Playwright"></a>
    <a href="https://fastapi.tiangolo.com/"><img src="https://img.shields.io/badge/FastAPI-009688.svg?logo=fastapi&logoColor=white" alt="FastAPI"></a>
    <a href="https://nextjs.org/"><img src="https://img.shields.io/badge/Next.js-black.svg?logo=next.js&logoColor=white" alt="Next.js"></a>
    <a href="https://github.com/NihadMemmedli/quorvex_ai/commits/main"><img src="https://img.shields.io/github/last-commit/NihadMemmedli/quorvex_ai" alt="Last Commit"></a>
    <a href="CONTRIBUTING.md"><img src="https://img.shields.io/badge/PRs-welcome-brightgreen.svg" alt="PRs Welcome"></a>
  </p>
  <p align="center">
    <a href="https://nihadmemmedli.github.io/quorvex_ai/"><strong>Documentation</strong></a> &nbsp;&bull;&nbsp;
    <a href="https://nihadmemmedli.github.io/quorvex_ai/tutorials/getting-started/">Getting Started</a> &nbsp;&bull;&nbsp;
    <a href="https://github.com/NihadMemmedli/quorvex_ai/issues">Issues</a> &nbsp;&bull;&nbsp;
    <a href="CONTRIBUTING.md">Contributing</a>
  </p>
</p>

---

Quorvex AI is for teams that already know Playwright is the right test runtime, but do not want to hand-write every brittle end-to-end flow. Describe a user flow, import a PRD or OpenAPI file, or let an agent explore a real app; Quorvex plans the flow, generates Playwright TypeScript, validates it in a browser, and repairs selector or timing failures when it can.

The output is normal code your team owns: inspect it, commit it, and run it in CI with no runtime AI dependency. Around that core workflow, Quorvex also supports PRD-to-tests, API checks, K6 load tests, security scans, database quality checks, mobile smoke flows, LLM evaluation suites, CI quality gates, and autonomous coverage discovery.

![Quorvex AI product flow](docs/assets/ui/product-flow.gif)
*Plain-English specs become validated test code through planning, browser execution, and healing.*

## Why Star This Repo?

- **AI speed, normal Playwright ownership** -- Generate tests with agents, then keep readable code that runs without AI in every CI job.
- **Self-hosted by design** -- Keep app URLs, credentials, traces, and test data on your infrastructure instead of a vendor runtime.
- **More than UI happy paths** -- Grow from E2E generation into PRD coverage, API, load, security, database, mobile, and LLM testing.

## Start Here

| Path | Best for | Link |
|---|---|---|
| Star and follow | Track the open-source self-hosted Playwright agent platform | [Star Quorvex AI](https://github.com/NihadMemmedli/quorvex_ai/stargazers) |
| Watch the demo | Understand the workflow in under a minute | [Demo GIF](docs/assets/ui/product-flow.gif) |
| Try the fastest path | Run the lightweight SQLite stack and generate your first Playwright test | [Minimal README](README.minimal.md) |
| Choose a setup | Pick minimal Docker, full Docker, local dev, production, workers, or Kubernetes | [Setup Options](docs/guides/setup-options.md) |
| Run the full stack | Use the dashboard, queues, storage, and integrations locally | [Getting Started](https://nihadmemmedli.github.io/quorvex_ai/tutorials/getting-started/) |

### Why Quorvex AI?

- **Built for Playwright teams** -- Quorvex does the slow work of planning, browser exploration, generation, validation, and repair, while your team keeps standard Playwright code.
- **Generate once, run forever** -- AI helps create and heal tests, but passing generated tests run natively in CI without burning model tokens on every run.
- **Turn product context into coverage** -- Start from markdown specs, PRDs, OpenAPI files, or autonomous app exploration and preserve traceability back to requirements.
- **Own the platform surface** -- Run the dashboard, workers, queues, browser pool, storage, schedules, credentials, and integrations in your own environment.

![Quorvex AI dashboard overview](docs/assets/ui/dashboard-overview.png)
*Web dashboard for managing specs, monitoring execution trends, and analyzing test results.*

## Product Screenshots

| Dashboard | API testing | Workflow monitor |
|---|---|---|
| ![Dashboard overview](docs/assets/ui/dashboard-overview.png) | ![API testing dashboard](docs/assets/ui/api-testing.png) | ![Workflow monitor](docs/assets/ui/workflow.png) |

| AutoPilot | Test runs | Settings |
|---|---|---|
| ![AutoPilot dashboard](docs/assets/ui/autopilot.png) | ![Test runs dashboard](docs/assets/ui/runs.png) | ![Settings dashboard](docs/assets/ui/settings.png) |

---

## Input to Output

Quorvex starts with a markdown spec like this:

```markdown
# Test: Login Form Validation

## Steps
1. Navigate to https://the-internet.herokuapp.com/login
2. Enter "tomsmith" into the Username field
3. Enter "SuperSecretPassword!" into the Password field
4. Click the "Login" button
5. Verify the page displays "Secure Area" heading
6. Click the "Logout" button
7. Verify the user is redirected back to the login page
```

It produces maintainable Playwright code:

```ts
import { test, expect } from '@playwright/test';

test('logs in with valid credentials and logs out', async ({ page }) => {
  await page.goto('https://the-internet.herokuapp.com/login');
  await expect(page.getByRole('heading', { name: 'Login Page' })).toBeVisible();
  await page.getByLabel('Username').fill('tomsmith');
  await page.getByLabel('Password').fill('SuperSecretPassword!');
  await page.getByRole('button', { name: 'Login' }).click();
  await expect(page.getByRole('heading', { name: 'Secure Area' })).toBeVisible();
  await page.getByRole('link', { name: 'Logout' }).click();
  await expect(page.getByRole('heading', { name: 'Login Page' })).toBeVisible();
});
```

This is not just prompt-to-code. Quorvex plans against the target app, uses live browser context during generation, runs the generated test, and only hands you code after validation or healing attempts.

See the full example spec and generated output in [`demo/`](demo/).

---

## Try It Instantly

No local setup required -- open a fully configured development environment in your browser:

[![Open in Gitpod](https://gitpod.io/button/open-in-gitpod.svg)](https://gitpod.io/#https://github.com/NihadMemmedli/quorvex_ai)
[![Open in GitHub Codespaces](https://github.com/codespaces/badge.svg)](https://codespaces.new/NihadMemmedli/quorvex_ai?quickstart=1)

---

## How Quorvex AI Compares

| Capability | Quorvex AI | Shortest | Octomind | testRigor | Playwright Test Agents |
|---|---|---|---|---|---|
| Natural-language authoring | ✅ Specs, PRDs, chat, exploration | ✅ | ✅ Prompt/discovery | ✅ Plain English | ✅ Agent prompts |
| Standard Playwright code | ✅ Owned repo code | Runtime-oriented Playwright | ✅ Portable Playwright | ❌ Proprietary no-code runtime | ✅ Generated tests |
| Generate once, run natively | ✅ | ❌ AI used during execution | ✅ Cloud/local execution | Managed platform runtime | ✅ |
| Self-healing / repair | ✅ Native, hybrid, standard | Not advertised | ✅ Source-level healing | ✅ AI maintenance | ✅ Healer agent |
| Web QA dashboard | ✅ Full platform | Not advertised | ✅ Hosted QA dashboard | ✅ Hosted QA dashboard | ❌ Editor/agent workflow |
| Requirements, RTM, coverage | ✅ Built in | Not advertised | Not advertised | Not advertised | Plan/spec files only |
| PRD to tests | ✅ Upload + feature workspace | Not advertised | Not advertised | Not advertised | PRD context for agents |
| Autonomous missions | ✅ Scheduled/approval-gated | Not advertised | Not advertised | Not advertised | Agent loop, not platform missions |
| API testing | ✅ OpenAPI import + API specs | ✅ Natural-language API tests | Not advertised as API testing | ✅ API commands | Via code/MCP |
| Load testing | ✅ K6 workers/results | Not advertised | Not advertised | Not advertised | Via custom code |
| Security testing | ✅ ZAP + Nuclei | Not advertised | Not advertised | Not advertised | Via custom code |
| Database testing | ✅ Connections, schema checks | Via callback code | Not advertised | ✅ Database query support | Via custom code |
| LLM evaluation | ✅ Providers, datasets, comparisons | Not advertised | Not advertised | Not advertised | Via custom code |
| CI/CD and PR advisor | ✅ GitHub/GitLab + quality gates | ✅ CI headless runs | ✅ CI/CD | ✅ CI integrations | ✅ In repo workflows |
| Test management integrations | ✅ TestRail + Jira | Not advertised | TestRail on higher tiers | Integrations advertised | Via custom code |
| Self-hosted / private deployment | ✅ Full stack | ✅ Package/repo | Hosted SaaS + private workers | Hosted SaaS | ✅ Local repo agents |
| Open source / license | ✅ MIT | ✅ MIT | ❌ Commercial | ❌ Commercial | ✅ Playwright |

> **Generate once, run forever** -- Unlike runtime-first AI runners, Quorvex AI outputs stable Playwright code. Subsequent runs execute natively with zero AI cost.
>
> Comparison notes are based on public product documentation and repositories checked on May 23, 2026. "Not advertised" means the capability was not clearly documented as a first-class product feature, not that it is impossible to build with custom code.

[Detailed comparisons](docs/comparisons/index.md) | [Why we built this](docs/comparisons/why-we-built-this.md)

---

## Features

| Area | What Quorvex AI supports |
|---|---|
| Test generation | Plain-English specs to Playwright, native validation, Smart Check reuse, hybrid healing, visual regression, reusable `@include` templates |
| AutoPilot & agents | App discovery, live browser state, generated task artifacts, custom agent definitions, persistent autonomous missions, recurring or long-running operation, approval gates |
| Requirements & coverage | PRD upload, feature extraction, requirements generation, duplicate detection, RTM, coverage gaps, suggested tests |
| Specialized testing | OpenAPI/API testing, K6 load testing, quick/Nuclei/ZAP security scans, database quality checks, LLM evaluation, Appium mobile smoke flows |
| Quality intelligence | Regression batches, flaky test detection, pass-rate trends, failure classification, analytics, generated reports |
| Integrations | GitHub Actions, GitLab CI, PR advisor, quality gates, workflow PRs, TestRail sync, Jira issue creation |
| Operations | Project isolation, RBAC, encrypted credentials, schedules, browser pools, Redis queues, MinIO storage, backup, archival, Docker/Swarm/Kubernetes assets |

---

## How It Works

Quorvex AI uses a multi-stage pipeline where an AI agent actively interacts with your application through a real browser at every step:

```mermaid
graph LR
    A["📝 Markdown Spec"] --> B["🔍 Plan"]
    B --> C["⚡ Generate"]
    C --> D["✅ Validate"]
    D --> E{"Pass?"}
    E -->|Yes| F["🎉 Done"]
    E -->|No| G["🔧 Heal"]
    G --> D
```

1. **Plan** -- The AI reads your spec and explores the target application to build an execution plan
2. **Generate** -- Using the plan and live browser context, the AI writes Playwright TypeScript code
3. **Validate** -- The generated test is executed against the real application
4. **Heal** -- If validation fails, the AI debugs the failure and fixes the code automatically

The **Smart Check** system skips regeneration when valid code already exists, reuses passing tests, and only heals or regenerates when necessary.

---

## Quick Start

### Which Setup Should You Use?

| Setup | Best for | Database | Command |
|---|---|---|---|
| Minimal Docker | Fast first trial on smaller machines | SQLite | `docker compose -f docker-compose.minimal.yml up -d` |
| Full Docker dev | Complete self-hosted evaluation with dashboard, queues, storage, VNC, and security scanning | PostgreSQL | `make prod-dev` |
| Local native | Contributors and backend/frontend development | PostgreSQL if Docker is running, otherwise SQLite | `make setup && make dev` |
| Production | Hardened single-host deployment | PostgreSQL | `make prod-up` |

### Prerequisites

| Requirement | Version  | Notes                                |
|-------------|----------|--------------------------------------|
| Docker      | 20+      | Required for recommended setup       |
| Docker Compose | 2.x   | Included with Docker Desktop         |
| Git         | 2.x      | For cloning the repository           |

### Installation

```bash
# 1. Clone the repository
git clone https://github.com/NihadMemmedli/quorvex_ai.git
cd quorvex_ai

# 2. Configure your AI provider credentials
cp .env.prod.example .env.prod
# Edit .env.prod and set ANTHROPIC_AUTH_TOKEN (see Configuration below)

# Optional: confirm local and production env files are readable
make check-env

# 3. Start all services (backend, frontend, PostgreSQL, Redis, MinIO, VNC)
make prod-dev

# 4. Open http://localhost:3000
```

> **Local setup without Docker?** Run `make setup` then `make dev`. See the [Getting Started tutorial](https://nihadmemmedli.github.io/quorvex_ai/tutorials/getting-started/) for both paths.

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

Configuration depends on your running mode:

```bash
# Docker mode (recommended)
cp .env.prod.example .env.prod

# Local mode
cp .env.example .env
```

### AI Provider Setup

Quorvex AI requires an Anthropic-compatible API provider. Three options are supported:

#### Option 1: Z.ai GLM Coding Plan (Recommended Default)

```env
ANTHROPIC_AUTH_TOKEN=your-z-ai-token
ANTHROPIC_BASE_URL=https://api.z.ai/api/anthropic
ANTHROPIC_MODEL=glm-5.1
ANTHROPIC_DEFAULT_OPUS_MODEL=glm-5.1
ANTHROPIC_DEFAULT_SONNET_MODEL=glm-5-turbo
ANTHROPIC_DEFAULT_HAIKU_MODEL=glm-4.5-air
ANTHROPIC_CHAT_MODEL=glm-5-turbo
API_TIMEOUT_MS=3000000
```

Create a key in the [Z.ai API Keys](https://docs.z.ai/devpack/tool/claude) flow. Claude Code and the Claude Agent SDK still use Anthropic-compatible environment variable names.

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

> Free models have rate limits. For production use, consider paid models or Z.ai/Anthropic direct.

#### Option 3: Anthropic Direct

```env
ANTHROPIC_AUTH_TOKEN=sk-ant-your-api-key
ANTHROPIC_BASE_URL=https://api.anthropic.com
ANTHROPIC_DEFAULT_SONNET_MODEL=claude-sonnet-4-20250514
```

Sign up at [console.anthropic.com](https://console.anthropic.com) to get an API key.

### Optional Configuration

```env
# Memory system embeddings (enables semantic search for selectors)
OPENAI_API_KEY=your-openai-key

# Database (SQLite by default, PostgreSQL for production)
DATABASE_URL=sqlite:///./orchestrator/data/playwright_agent.db
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

For the complete list of environment variables, see the [Environment Variables Reference](docs/reference/environment-variables.md).

---

## Running Modes

### Docker Mode (Recommended)

```bash
cp .env.prod.example .env.prod
# Edit .env.prod, then validate it
make check-env
make prod-dev
```

- All services in Docker containers (backend, frontend, PostgreSQL, Redis, MinIO, VNC)
- Local `./orchestrator` and `./web/src` mounted for hot-reload
- Backend API on http://localhost:8001, frontend on http://localhost:3000, API docs on http://localhost:8001/docs
- VNC browser view on http://localhost:6080 and MinIO console on http://localhost:9001

### Local Mode

```bash
make setup   # One-time: Python venv, Node deps, Playwright browsers
# Edit .env, then validate it
make check-env
make dev     # Start backend + frontend natively
```

- Starts PostgreSQL via Docker if available, falls back to SQLite
- Hot-reload enabled for backend and frontend

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
# Docker mode (recommended)
make prod-dev         # Start all services with local code mounting
make prod-restart     # Restart backend (picks up code changes)
make prod-logs        # Tail production logs
make prod-status      # Show status of all services
make prod-down        # Stop all services
make prod-build       # Rebuild Docker images

# Local mode
make setup            # One-time setup (venv, deps, browsers, database)
make dev              # Start backend + frontend natively
make stop             # Stop local services

# Common
make run SPEC=...     # Run a specific test spec
make check-env        # Validate environment configuration
make test             # Run all Python tests
make lint             # Run linters (ruff + next lint)
make format           # Auto-format Python code
make clean            # Remove run artifacts

# Production operations
make backup           # Database-only backup
make backup-full      # Full backup (DB + specs + tests + PRDs)
make health-check     # Hit all health endpoints
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

| Section | Contents |
|---------|----------|
| [Tutorials](https://nihadmemmedli.github.io/quorvex_ai/tutorials/) | Step-by-step guides: first test, API testing, exploration, dashboard |
| [How-to Guides](https://nihadmemmedli.github.io/quorvex_ai/guides/) | Task-oriented: specs, deployment, integrations, security, load testing |
| [Reference](https://nihadmemmedli.github.io/quorvex_ai/reference/) | CLI, API endpoints, environment variables, database schema |
| [Explanation](https://nihadmemmedli.github.io/quorvex_ai/explanation/) | Architecture, pipeline design, memory system, browser pool |

To browse docs locally:

```bash
pip install -r requirements-docs.txt
mkdocs serve
# Open http://127.0.0.1:8000
```

---

## Troubleshooting

| Symptom | Solution |
|---------|----------|
| "ANTHROPIC_AUTH_TOKEN not set" | Check `.env` file, run `make check-env` |
| "Database connection refused" | Run `docker compose up -d db` or use SQLite (default) |
| Generated test selector fails | Self-healer auto-fixes; use `--hybrid` for complex cases |
| "No target URL found in spec" | Spec must contain a URL (e.g., "Navigate to https://...") |
| Test timeout on complex pages | Use `--hybrid` or increase exploration depth |
| "Module not found" errors | Re-run `make setup` to reinstall dependencies |

For more diagnostics, see the [Troubleshooting Guide](docs/guides/troubleshooting.md).

---

## Contributing

We welcome contributions of all kinds. See [CONTRIBUTING.md](CONTRIBUTING.md) for development setup, architecture overview, code style, and the pull request process.

New to the project? Check out the [Good First Issues](docs/community/good-first-issues.md) list for curated tasks suitable for newcomers.

Please read our [Code of Conduct](CODE_OF_CONDUCT.md) before participating.

---

## Security

To report a vulnerability, please see [SECURITY.md](SECURITY.md). Do **not** open a public issue for security concerns.

---

## Community

- [GitHub Issues](https://github.com/NihadMemmedli/quorvex_ai/issues) -- Bug reports and feature requests
- [GitHub Discussions](https://github.com/NihadMemmedli/quorvex_ai/discussions) -- Questions, ideas, and showcase
- [Contributing Guide](CONTRIBUTING.md) -- How to get involved
- [Good First Issues](docs/community/good-first-issues.md) -- Curated tasks for new contributors
- [Roadmap](docs/community/roadmap.md) -- Current and planned features
- [Changelog](CHANGELOG.md) -- Release history

### Contributors

<a href="https://github.com/NihadMemmedli/quorvex_ai/graphs/contributors">
  <img src="https://contrib.rocks/image?repo=NihadMemmedli/quorvex_ai" alt="Contributors" />
</a>

---

## Star History

[![Star History Chart](https://api.star-history.com/svg?repos=NihadMemmedli/quorvex_ai&type=Date)](https://star-history.com/#NihadMemmedli/quorvex_ai&Date)

---

If you find Quorvex AI useful, please consider giving it a ⭐ on GitHub — it helps others discover the project!

---

## License

This project is licensed under the MIT License. See [LICENSE](LICENSE) for details.

Copyright 2026 Quorvex AI Contributors.
