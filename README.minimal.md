# Fast Trial: Minimal Docker Compose Setup

This is the fastest way to try Quorvex AI from the GitHub repo. It runs the dashboard and backend with **SQLite** instead of PostgreSQL and skips optional services such as Redis, MinIO, and VNC.

![Quorvex dashboard overview](docs/assets/ui/dashboard-overview.png)

*The minimal stack opens the same Quorvex dashboard UI with fewer infrastructure services.*

Use this path when you want to evaluate the core workflow quickly:

1. Start the lightweight stack.
2. Open the dashboard.
3. Write or paste a plain-English test spec.
4. Generate a validated Playwright test you can inspect and run.

For production, team usage, queues, object storage, browser viewing, and security scanning, use the full stack in the main [README](README.md).

## What's Included

- ✅ **Backend** (FastAPI + Playwright orchestrator)
- ✅ **Frontend** (Next.js web UI)
- ✅ **SQLite** database (file-based, no separate DB container)
- ✅ **Core spec-to-Playwright workflow**

## What's Not Included

- ❌ PostgreSQL (uses SQLite instead)
- ❌ Redis (distributed K6 mode disabled)
- ❌ MinIO (object storage)
- ❌ VNC server

## Quick Start

The only required product credential is an Anthropic-compatible API key. Quorvex uses Anthropic-style environment variables even when the provider is Z.ai, OpenRouter, or another compatible endpoint.

### 1. Prerequisites

- Docker & Docker Compose v2.x
- `.env` file with your `ANTHROPIC_AUTH_TOKEN`

Create the file from the local example if you do not already have one:

```bash
cp .env.example .env
# Edit .env and set ANTHROPIC_AUTH_TOKEN
make check-env
```

### 2. Start Services

```bash
docker compose -f docker-compose.minimal.yml up -d
```

### 3. Access

- **Frontend:** http://localhost:3000
- **Backend API:** http://localhost:8001
- **API Docs:** http://localhost:8001/docs

Open the frontend, create a spec, and run it through the pipeline. Generated tests are normal Playwright files that can be inspected, committed, and run outside Quorvex.

### 4. Stop Services

```bash
docker compose -f docker-compose.minimal.yml down
```

## Data Persistence

SQLite database is stored at `./data/quorvex.db` (persists across restarts).

To reset the database:
```bash
rm -f ./data/quorvex.db
```

## Resource Usage

This minimal setup uses significantly less resources:

- **RAM:** ~3GB (vs ~8GB for full stack)
- **CPU:** ~3 cores (vs ~6+ cores for full stack)
- **Disk:** Minimal (no PostgreSQL data volume)

## Limitations

- No distributed K6 load testing (requires Redis)
- No persistent object storage (no MinIO)
- SQLite has concurrency limits (fine for single-user testing)
- No VNC browser console for watching remote browser sessions

## Upgrading to Full Stack

When ready for production or multi-user scenarios, migrate to the full stack:

```bash
# Stop minimal setup
docker compose -f docker-compose.minimal.yml down

# Configure and start the full Docker stack
cp .env.prod.example .env.prod
make prod-dev
```

You'll need to migrate data from SQLite to PostgreSQL. See the [deployment guide](docs/guides/deployment.md) and [on-premises deployment guide](docs/guides/company-deployment.md) for full-stack database and migration operations.

## Troubleshooting

| Issue | Solution |
|-------|----------|
| Port conflicts | Change `8001:8001` and `3000:3000` in the YAML |
| SQLite locked | Stop all containers and restart |
| Memory limit | Reduce `memory` limits in the YAML |

## Configuration

Edit `.env` to configure:

- API keys (`ANTHROPIC_AUTH_TOKEN`, `OPENAI_API_KEY`)
- Default model (`ANTHROPIC_DEFAULT_SONNET_MODEL`)
- Memory system (`MEMORY_ENABLED=false` by default in minimal mode)

---

**Tip:** Use this minimal setup for local development, demos, or learning. For production use cases with multiple concurrent users, switch to the full `docker-compose.yml` stack.
