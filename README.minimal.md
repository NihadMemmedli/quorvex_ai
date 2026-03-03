# Minimal Docker Compose Setup

This is a lightweight version of Quorvex AI that uses **SQLite** instead of PostgreSQL and skips optional services (Redis, MinIO, VNC). It's perfect for quickly trying out the platform or running it on resource-constrained environments.

## What's Included

- ✅ **Backend** (FastAPI + Playwright orchestrator)
- ✅ **Frontend** (Next.js web UI)
- ✅ **SQLite** database (file-based, no separate DB container)

## What's Not Included

- ❌ PostgreSQL (uses SQLite instead)
- ❌ Redis (distributed K6 mode disabled)
- ❌ MinIO (object storage)
- ❌ VNC server

## Quick Start

### 1. Prerequisites

- Docker & Docker Compose v2.x
- `.env` file with your `ANTHROPIC_AUTH_TOKEN`

### 2. Start Services

```bash
docker-compose -f docker-compose.minimal.yml up -d
```

### 3. Access

- **Frontend:** http://localhost:3000
- **Backend API:** http://localhost:8001
- **API Docs:** http://localhost:8001/docs

### 4. Stop Services

```bash
docker-compose -f docker-compose.minimal.yml down
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

## Upgrading to Full Stack

When ready for production or multi-user scenarios, migrate to the full stack:

```bash
# Stop minimal setup
docker-compose -f docker-compose.minimal.yml down

# Start full stack
docker-compose up -d
```

You'll need to migrate data from SQLite to PostgreSQL. See [main README](README.md#database-migration) for migration guides.

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
