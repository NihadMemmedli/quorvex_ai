# Environment Variables

Complete reference for all environment variables used by Quorvex AI. Configure in `.env` (local development) or `.env.prod` (production).

## AI / LLM Configuration

| Variable | Default | Required | Description |
|----------|---------|----------|-------------|
| `ANTHROPIC_AUTH_TOKEN` | -- | Yes | Authentication token for the Claude API |
| `ANTHROPIC_BASE_URL` | -- | Yes | API endpoint URL (Anthropic direct, OpenRouter, or custom proxy) |
| `ANTHROPIC_DEFAULT_SONNET_MODEL` | -- | Yes | Model ID (e.g., `claude-sonnet-4-20250514`) |
| `OPENAI_API_KEY` | -- | No | OpenAI API key for memory system embeddings |

## Database

| Variable | Default | Required | Description |
|----------|---------|----------|-------------|
| `DATABASE_URL` | `sqlite:///./test.db` | No | Database connection string. PostgreSQL: `postgresql://user:pass@host:port/db` |
| `POSTGRES_USER` | `playwright` | Prod only | PostgreSQL username (Docker Compose) |
| `POSTGRES_PASSWORD` | -- | Prod only | PostgreSQL password (Docker Compose) |
| `POSTGRES_DB` | `playwright_agent` | Prod only | PostgreSQL database name |

## Authentication

| Variable | Default | Required | Description |
|----------|---------|----------|-------------|
| `JWT_SECRET_KEY` | `dev-secret-key-change-in-production` | Prod only | Secret key for JWT token signing. Generate: `openssl rand -hex 32` |
| `REQUIRE_AUTH` | `false` | No | Enable authentication enforcement |
| `ALLOW_REGISTRATION` | `true` | No | Allow new user registration |
| `REDIS_URL` | -- | No | Redis URL for distributed rate limiting. Format: `redis://host:6379/0` |
| `INITIAL_ADMIN_EMAIL` | -- | No | Email for initial admin user (first startup only) |
| `INITIAL_ADMIN_PASSWORD` | -- | No | Password for initial admin user |

## Playwright / Browser

| Variable | Default | Required | Description |
|----------|---------|----------|-------------|
| `HEADLESS` | `false` (local), `true` (Docker) | No | Run browsers in headless mode |
| `PLAYWRIGHT_HEADLESS` | Same as `HEADLESS` | No | Alternative Playwright-specific headless setting |
| `BASE_URL` | -- | No | Default base URL for Playwright tests |
| `PLAYWRIGHT_WORKERS` | `4` | No | Number of Playwright test runner workers |
| `PLAYWRIGHT_OUTPUT_DIR` | `./test-results` | No | Directory for Playwright test output |

## Browser Resource Pool

| Variable | Default | Required | Description |
|----------|---------|----------|-------------|
| `MAX_BROWSER_INSTANCES` | `5` | No | Hard limit on concurrent browser instances |
| `BROWSER_SLOT_TIMEOUT` | `3600` | No | Maximum seconds to wait for a browser slot |

## Agent Timeouts

| Variable | Default | Required | Description |
|----------|---------|----------|-------------|
| `AGENT_TIMEOUT_SECONDS` | `1800` | No | Default timeout for all agents (30 minutes) |
| `EXPLORATION_TIMEOUT_SECONDS` | `1800` | No | Timeout for the exploration agent |
| `PLANNER_TIMEOUT_SECONDS` | `1800` | No | Timeout for the planner agent |
| `GENERATOR_TIMEOUT_SECONDS` | `1800` | No | Timeout for the generator agent |

## Concurrency Limits

| Variable | Default | Required | Description |
|----------|---------|----------|-------------|
| `MAX_CONCURRENT_AGENTS` | `8` | No | Maximum concurrent AI agent processes |
| `MAX_CONCURRENT_EXPLORATIONS` | `5` | No | Maximum concurrent app explorations |
| `MAX_CONCURRENT_PRD` | `3` | No | Maximum concurrent PRD processing jobs |
| `DEFAULT_PARALLELISM` | `4` | No | Default number of parallel browser workers |
| `PARALLEL_MODE_ENABLED` | `true` | No | Enable parallel test execution |

## Memory System

| Variable | Default | Required | Description |
|----------|---------|----------|-------------|
| `MEMORY_ENABLED` | `true` | No | Enable/disable the memory system |
| `CHROMADB_PERSIST_DIRECTORY` | `./data/chromadb` | No | Directory for ChromaDB vector store data |
| `EMBEDDING_MODEL` | `text-embedding-3-small` | No | OpenAI embedding model for semantic search |
| `EMBEDDING_DIMENSION` | `1536` | No | Embedding vector dimension |
| `MEMORY_RETENTION_DAYS` | `365` | No | Days to retain memory records |
| `MEMORY_COLLECTION_PREFIX` | `test_automation` | No | Prefix for ChromaDB collection names |
| `COVERAGE_ENABLED` | `true` | No | Enable coverage analysis |
| `COVERAGE_THRESHOLD` | `0.8` | No | Target coverage threshold (0.0-1.0) |

## Skill Mode

| Variable | Default | Required | Description |
|----------|---------|----------|-------------|
| `SKILL_DIR` | `.claude/skills/playwright` | No | Directory containing skill script files |
| `SKILL_TIMEOUT` | `30000` | No | Script execution timeout in milliseconds |
| `SLOW_MO` | `0` | No | Slow down skill actions by N milliseconds |

## VNC Live Browser View

| Variable | Default | Required | Description |
|----------|---------|----------|-------------|
| `VNC_ENABLED` | `true` (Docker prod) | No | Enable VNC mode (browser runs headed on virtual display) |
| `DISPLAY` | `:99` | No | Xvfb virtual display number |

When `VNC_ENABLED=true`, parallel browser execution is limited to 1 instance.

## MinIO Object Storage

| Variable | Default | Required | Description |
|----------|---------|----------|-------------|
| `MINIO_ENDPOINT` | `http://minio:9000` | Prod only | MinIO API endpoint |
| `MINIO_ROOT_USER` | `minioadmin` | Prod only | MinIO admin username |
| `MINIO_ROOT_PASSWORD` | -- | Prod only | MinIO admin password. Generate: `openssl rand -hex 16` |
| `MINIO_API_PORT` | `9000` | No | External port for MinIO API |
| `MINIO_CONSOLE_PORT` | `9001` | No | External port for MinIO web console |
| `MINIO_BUCKET` | `playwright-backups` | No | Bucket name for database backups |
| `MINIO_BUCKET_ARTIFACTS` | `playwright-artifacts` | No | Bucket name for archived run artifacts |

## Backup and Archival

| Variable | Default | Required | Description |
|----------|---------|----------|-------------|
| `BACKUP_RETENTION` | `30` | No | Days to keep backups locally |
| `ARCHIVE_RETENTION` | `90` | No | Days to keep archived artifacts in MinIO |
| `ARCHIVE_HOT_DAYS` | `30` | No | Days to keep all artifacts locally (hot tier) |
| `ARCHIVE_TOTAL_DAYS` | `90` | No | Days before artifacts are deleted completely (cold tier) |

## Load Testing

| Variable | Default | Required | Description |
|----------|---------|----------|-------------|
| `K6_MAX_VUS` | `1000` | No | Safety limit on virtual users |
| `K6_MAX_DURATION` | `5m` | No | Max test duration |
| `K6_TIMEOUT_SECONDS` | `3600` | No | Process timeout |

## Security Testing

| Variable | Default | Required | Description |
|----------|---------|----------|-------------|
| `ZAP_HOST` | `localhost` | No | ZAP daemon host |
| `ZAP_PORT` | `8090` | No | ZAP daemon port |
| `ZAP_API_KEY` | -- | No | ZAP API key |
| `ZAP_PROXY_ENABLED` | `false` | No | Enable passive mode (Playwright tests proxy through ZAP) |
| `NUCLEI_TIMEOUT_SECONDS` | `600` | No | Nuclei scan timeout |
| `SECURITY_SCAN_TIMEOUT` | `1800` | No | Overall scan timeout |

## Frontend

| Variable | Default | Required | Description |
|----------|---------|----------|-------------|
| `NEXT_PUBLIC_API_URL` | `http://localhost:8001` | No | Backend API URL for the frontend |
| `ALLOWED_ORIGINS` | `http://localhost:3000` | No | CORS allowed origins (comma-separated) |

## Test Credentials

| Variable | Default | Required | Description |
|----------|---------|----------|-------------|
| `LOGIN_USERNAME` | -- | No | Default test username |
| `LOGIN_PASSWORD` | -- | No | Default test password |
| `LOGIN_EMAIL` | -- | No | Default test email (used for exploration auth) |

Custom application credentials can be added as any `KEY=VALUE` pair in `.env` and referenced in specs as `{{KEY}}`.

## Docker-Specific

| Variable | Default | Required | Description |
|----------|---------|----------|-------------|
| `BROWSER_WORKERS_ENABLED` | `false` | No | Enable isolated browser worker containers |
| `BROWSER_WORKER_REPLICAS` | `4` | No | Number of browser worker container replicas |
| `LOG_LEVEL` | `INFO` | No | Python logging level (`DEBUG`, `INFO`, `WARNING`, `ERROR`) |
| `SPECS_DIR` | `./specs` | No | Host path for specs volume mount |
| `PRDS_DIR` | `./prds` | No | Host path for PRDs volume mount |
| `TESTS_DIR` | `./tests` | No | Host path for tests volume mount |

## Logging

| Variable | Default | Required | Description |
|----------|---------|----------|-------------|
| `LOG_LEVEL` | `INFO` | No | Python logging level |

## Headless Mode Resolution

The `orchestrator/load_env.py` module resolves the headless setting automatically:

| Condition | Result |
|-----------|--------|
| `VNC_ENABLED=true` | Headed (`HEADLESS=false`) |
| Docker without VNC | Headless (`HEADLESS=true`) |
| Local development | Headed (`HEADLESS=false`) |
| Explicit `HEADLESS=...` in env | Uses the explicit value (highest priority) |

## Related

- [CLI Reference](cli.md)
- [API Overview](api-overview.md)
