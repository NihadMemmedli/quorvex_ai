# Environment Variables

![Settings dashboard for environment-backed configuration](../assets/ui/settings.png)

<p class="caption">Settings dashboard for environment-backed configuration.</p>


Complete reference for all environment variables used by Quorvex AI. Configure in `.env` (local development) or `.env.prod` (production).

## AI / LLM Configuration

| Variable | Default | Required | Description |
|----------|---------|----------|-------------|
| `QUORVEX_ACTIVE_LLM_PROVIDER` | `zai` | Deploy only | Active deploy-time provider selector. Supported values: `zai`, `openrouter`, `openai`, `anthropic` |
| `ZAI_API_KEY` | -- | Provider-specific | Z.ai GLM API key used when `QUORVEX_ACTIVE_LLM_PROVIDER=zai` |
| `OPENROUTER_API_KEY` | -- | Provider-specific | OpenRouter API key used when `QUORVEX_ACTIVE_LLM_PROVIDER=openrouter` |
| `OPENAI_API_KEY` | -- | Provider-specific | OpenAI API key used for memory embeddings and when `QUORVEX_ACTIVE_LLM_PROVIDER=openai` |
| `ANTHROPIC_API_KEY` | -- | Provider-specific | Anthropic API key used when `QUORVEX_ACTIVE_LLM_PROVIDER=anthropic`; app containers receive Anthropic-compatible aliases from the active runtime key |
| `QUORVEX_LLM_PROVIDER` | `anthropic_compatible` | No | Canonical runtime provider kind for app-owned AI calls |
| `QUORVEX_LLM_BASE_URL` | `https://api.z.ai/api/anthropic` | No | Canonical runtime provider endpoint; mirrored to `ANTHROPIC_BASE_URL` for SDK compatibility |
| `QUORVEX_LLM_API_KEY` | -- | Runtime | Canonical single runtime API key mapped from the active provider key during deployment; legacy Anthropic key names remain supported |
| `QUORVEX_LLM_API_KEYS` | -- | No | Canonical comma-separated runtime key pool for rotation |
| `QUORVEX_LLM_LIGHT_MODEL` | `glm-4.5-air` | No | Cheap deterministic model for classification, repair, summaries, and memory extraction |
| `QUORVEX_LLM_STANDARD_MODEL` | `glm-5-turbo` | No | Default model for synthesis and analysis tasks |
| `QUORVEX_LLM_DEEP_MODEL` | `glm-5.1` | No | Strong model for planning, PRD decomposition, and complex analysis |
| `QUORVEX_LLM_TOOL_DEEP_MODEL` | `glm-5.1` | No | Strong model for browser/tool loops, generation, and healing |
| `QUORVEX_LLM_CHAT_MODEL` | `glm-5-turbo` | No | Assistant chat model resolved by the backend settings API |
| `QUORVEX_EMBEDDING_MODEL` | `text-embedding-3-small` | No | Canonical embedding model for memory and PRD semantic indexing |
| `ANTHROPIC_AUTH_TOKEN` | copied from `QUORVEX_LLM_API_KEY` when configured | No | Legacy Anthropic-compatible SDK token alias |
| `ANTHROPIC_AUTH_TOKENS` | copied from `QUORVEX_LLM_API_KEYS` when configured | No | Legacy comma-separated token pool alias |
| `CLAUDE_CODE_OAUTH_TOKEN` | -- | No | Claude Code OAuth token for Docker/dev setups that authenticate through Claude Code |
| `ANTHROPIC_BASE_URL` | copied from `QUORVEX_LLM_BASE_URL` | No | Legacy SDK endpoint alias |
| `ANTHROPIC_MODEL` | selected runtime tier model | No | Legacy active model alias used by SDK clients |
| `ANTHROPIC_DEFAULT_OPUS_MODEL` | `glm-5.1` | No | Claude Code / Agent SDK Opus alias target |
| `ANTHROPIC_DEFAULT_SONNET_MODEL` | `glm-5-turbo` | No | Claude Code / Agent SDK Sonnet alias target |
| `ANTHROPIC_DEFAULT_HAIKU_MODEL` | `glm-4.5-air` | No | Claude Code / Agent SDK Haiku alias target |
| `ANTHROPIC_CHAT_MODEL` | `glm-5-turbo` | No | Legacy chat model alias |
| `ANTHROPIC_ENABLE_CHAT_THINKING` | `false` | No | Enable provider-specific chat reasoning controls when supported |
| `API_TIMEOUT_MS` | `3000000` | No | Claude Code API timeout used by the Z.ai GLM Coding Plan |
| `OPENAI_BASE_URL` | -- | No | Optional OpenAI-compatible endpoint for embedding/chat clients |
| `OPENAI_CHAT_MODEL` | -- | No | Optional OpenAI chat model override for features that use OpenAI-compatible chat calls |

## Database

| Variable | Default | Required | Description |
|----------|---------|----------|-------------|
| `DATABASE_URL` | `sqlite:///.../orchestrator/data/playwright_agent.db` | No | Database connection string. PostgreSQL: `postgresql://user:pass@host:port/db` |
| `POSTGRES_USER` | `playwright` | Prod only | PostgreSQL username (Docker Compose) |
| `POSTGRES_PASSWORD` | -- | Prod only | PostgreSQL password (Docker Compose) |
| `POSTGRES_DB` | `playwright_agent` | Prod only | PostgreSQL database name |

## Authentication

| Variable | Default | Required | Description |
|----------|---------|----------|-------------|
| `JWT_SECRET_KEY` | -- | Yes | Secret key for JWT token signing. Generate: `openssl rand -hex 32`. Some local commands set a temporary development value, but the API process requires this variable. |
| `REQUIRE_AUTH` | `false` | No | Enable authentication enforcement |
| `ALLOW_REGISTRATION` | `true` | No | Allow new user registration |
| `REDIS_URL` | -- | No | Redis URL for distributed rate limiting. Format: `redis://host:6379/0` |
| `INITIAL_ADMIN_EMAIL` | -- | No | Email for initial admin user (first startup only) |
| `INITIAL_ADMIN_PASSWORD` | -- | No | Password for initial admin user |

!!! warning
    `.env.prod.example` includes development defaults for local evaluation. Change `JWT_SECRET_KEY`, `POSTGRES_PASSWORD`, `MINIO_ROOT_PASSWORD`, and initial admin credentials before exposing a production deployment.

## Playwright / Browser

| Variable | Default | Required | Description |
|----------|---------|----------|-------------|
| `HEADLESS` | `false` (local), `true` (Docker) | No | Run browsers in headless mode |
| `PLAYWRIGHT_HEADLESS` | Same as `HEADLESS` | No | Alternative Playwright-specific headless setting |
| `BASE_URL` | -- | No | Default base URL for Playwright tests |
| `PLAYWRIGHT_WORKERS` | `4` | No | Number of Playwright test runner workers |
| `PLAYWRIGHT_OUTPUT_DIR` | `./test-results` | No | Directory for Playwright test output |

## Appium / Mobile

| Variable | Default | Required | Description |
|----------|---------|----------|-------------|
| `APPIUM_MCP_ENABLED` | `false` | No | Enable Appium MCP mobile testing features |
| `APPIUM_SERVER_URL` | `http://127.0.0.1:4723` | Mobile runs | Appium server URL |
| `APPIUM_CAPABILITIES_CONFIG` | -- | No | Path to Appium capabilities JSON |
| `APPIUM_SCREENSHOTS_DIR` | `runs/appium-screenshots` | No | Screenshot output directory for Appium runs |
| `APPIUM_REMOTE_SERVER_URL_ALLOW_REGEX` | `^https?://` | No | Allowed remote Appium server URL pattern for Appium MCP |
| `APPIUM_HOME` | Appium default | No | Appium extension home used for installed drivers |
| `MOBILE_TESTS_DIR` | `tests/mobile` | No | Output directory for generated mobile tests |
| `IOS_UDID` | auto-detected | No | Connected iPhone UDID override |
| `IOS_TEAM_ID` | -- | iOS real devices | Apple Developer Team ID for WebDriverAgent signing |
| `IOS_BUNDLE_ID_PREFIX` | -- | iOS real devices | Bundle prefix used for WebDriverAgent signing |

## Browser Resource Pool

| Variable | Default | Required | Description |
|----------|---------|----------|-------------|
| `MAX_BROWSER_INSTANCES` | `5` | No | Environment default for the global browser pool hard cap; the persisted Settings `parallelism` value becomes the runtime source of truth after DB initialization |
| `BROWSER_SLOT_TIMEOUT` | `3600` | No | Maximum seconds to wait for a browser slot |

## Agent Timeouts

| Variable | Default | Required | Description |
|----------|---------|----------|-------------|
| `AGENT_TIMEOUT_SECONDS` | `1800` | No | Default timeout for all agents (30 minutes) |
| `EXPLORATION_TIMEOUT_SECONDS` | `1800` | No | Timeout for the exploration agent |
| `PRD_TIMEOUT_SECONDS` | `600` | No | Timeout for PRD processing jobs |
| `PLANNER_TIMEOUT_SECONDS` | `1800` | No | Timeout for the planner agent |
| `GENERATOR_TIMEOUT_SECONDS` | `1800` | No | Timeout for the generator agent |

## Agent Runtimes

| Variable | Default | Required | Description |
|----------|---------|----------|-------------|
| `QUORVEX_AGENT_RUNTIME` | `claude_sdk` | No | Default runtime for agent runs. Supported value: `claude_sdk` |
| `QUORVEX_ASSISTANT_RUNTIME` | `QUORVEX_AGENT_RUNTIME` | No | Optional dashboard assistant runtime override. Supported values: `claude_sdk`, `openai` |
| `AGENT_COST_LOG` | -- | No | Optional JSONL path for appending agent usage and cost records during native pipeline runs |

Settings can manage backend agent runtime and dashboard assistant runtime separately. Backend agent runtime controls autonomous missions and custom agents. Assistant runtime controls dashboard chat routing.

## Autonomous Validation and Queue Recovery

| Variable | Default | Required | Description |
|----------|---------|----------|-------------|
| `AGENT_QUEUE_STALE_OWNERLESS_MINUTES` | internal default | No | Minutes before queued agent work without an owner is treated as stale and eligible for recovery |
| `AUTONOMOUS_VALIDATION_BASE_URL` | proposal target URL, then local web app | No | Base URL used when validating autonomous test proposals |
| `AUTONOMOUS_VALIDATION_DEV_SERVER_COMMAND` | `npm --prefix web run dev -- --hostname <host> --port <port>` | No | Command used to start a local validation server when the autonomous validator targets localhost and the app is not already reachable |
| `AUTONOMOUS_VALIDATION_SERVER_READY_SECONDS` | `45` | No | Seconds to wait for the autonomous validation dev server to become reachable |

## Concurrency Limits

| Variable | Default | Required | Description |
|----------|---------|----------|-------------|
| `MAX_CONCURRENT_AGENTS` | `8` | No | Local agent work scheduling hint; browser launches are still capped by the global browser pool |
| `MAX_CONCURRENT_EXPLORATIONS` | `5` | No | Local exploration scheduling hint; browser launches are still capped by the global browser pool |
| `MAX_CONCURRENT_PRD` | `3` | No | Local PRD scheduling hint; browser launches are still capped by the global browser pool |
| `DEFAULT_PARALLELISM` | `4` | No | Legacy initial execution setting used when DB settings do not exist |
| `PARALLEL_MODE_ENABLED` | `true` | No | Legacy test-run parallel-mode default; it does not replace the browser pool cap |

## Memory System

| Variable | Default | Required | Description |
|----------|---------|----------|-------------|
| `MEMORY_ENABLED` | `true` | No | Enable/disable the memory system |
| `MEMORY_PROJECT_ID` | -- | No | Project ID passed to pipeline subprocesses for memory isolation |
| `CHROMADB_HOST` | `localhost` | No | ChromaDB host when using a networked Chroma deployment |
| `CHROMADB_PORT` | `8000` | No | ChromaDB port when using a networked Chroma deployment |
| `CHROMADB_PERSIST_DIRECTORY` | `./data/chromadb` | No | Directory for ChromaDB vector store data |
| `EMBEDDING_MODEL` | `text-embedding-3-small` | No | OpenAI embedding model for semantic search |
| `EMBEDDING_DIMENSION` | `1536` | No | Embedding vector dimension |
| `MEMORY_RETENTION_DAYS` | `365` | No | Days to retain memory records |
| `MEMORY_COLLECTION_PREFIX` | `test_automation` | No | Prefix for ChromaDB collection names |
| `MEMORY_CONSOLIDATION_LLM` | `false` | No | Enable optional LLM extraction for agent memory consolidation |
| `MEMORY_CONSOLIDATION_MODEL` | `OPENAI_MODEL_ID` or `gpt-4o-mini` | No | Model used when LLM memory consolidation is enabled |
| `MEMORY_SELECTOR_WRITEBACK` | `true` | No | Enable best-effort writeback of selector repair decisions into project memory |
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
| `VNC_PUBLIC_WS_URL` | `ws://localhost:6080/websockify` in VNC runtime | Company VNC deployments | Browser-facing noVNC WebSocket URL, for example `wss://quorvex.example.com/websockify` |
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
| `K6_WORKER_ID` | generated UUID suffix | No | Identifier used by K6 worker containers |

## Security Testing

| Variable | Default | Required | Description |
|----------|---------|----------|-------------|
| `ZAP_HOST` | `localhost` | No | ZAP daemon host |
| `ZAP_PORT` | `8090` | No | ZAP daemon port |
| `ZAP_API_KEY` | -- | No | ZAP API key |
| `ZAP_PROXY_ENABLED` | `false` | No | Enable passive mode (Playwright tests proxy through ZAP) |
| `NUCLEI_TIMEOUT_SECONDS` | `600` | No | Nuclei scan timeout |
| `SECURITY_SCAN_TIMEOUT` | `1800` | No | Overall scan timeout |

## Temporal / Durable Runs

| Variable | Default | Required | Description |
|----------|---------|----------|-------------|
| `TEMPORAL_ADDRESS` | configured in app settings | Durable missions, workflows, and agent runs | Temporal frontend address |
| `TEMPORAL_NAMESPACE` | configured in app settings | No | Temporal namespace for durable workflows |
| `TEMPORAL_TASK_QUEUE` | configured in app settings | No | Task queue consumed by the autonomous mission worker |
| `TEMPORAL_WORKFLOW_TASK_QUEUE` | `quorvex-custom-workflows` | No | Task queue consumed by the custom workflow worker for custom workflows, standalone agent runs, and domain jobs |
| `TEMPORAL_UI_URL` | -- | No | Internal or external Temporal UI URL used by backend status surfaces |

Temporal-backed missions, custom workflows, standalone agent runs, and domain jobs support durable long-running execution. If Temporal is not reachable, these APIs report that durable orchestration is unavailable instead of silently falling back to non-durable execution.

## Frontend

| Variable | Default | Required | Description |
|----------|---------|----------|-------------|
| `NEXT_PUBLIC_API_URL` | `http://localhost:8001` locally, blank in company deployment | No | Browser API URL override. Leave blank behind company nginx so browser requests use same-origin `/backend-proxy`. |
| `QUORVEX_PUBLIC_API_URL` | -- | Docker prod | Public backend URL passed through production Compose to `NEXT_PUBLIC_API_URL`; leave blank for same-origin company nginx deployments |
| `INTERNAL_API_URL` | -- | No | Server-side backend URL used by Next.js routes and the backend proxy |
| `NEXT_PUBLIC_TEMPORAL_UI_URL` | -- | No | Public Temporal UI URL displayed by frontend features |
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

## Runtime and Advanced Internals

These variables are read by source code paths but are usually set by Docker Compose, CI, queue workers, or advanced integrations rather than by first-time local users.

| Variable | Default | Required | Description |
|----------|---------|----------|-------------|
| `AGENTIC_STABILITY_RERUNS` | feature default | No | Number of stability reruns used by selected agentic validation paths |
| `AGENT_TIMEOUT_MINUTES` | feature default | No | Minute-based timeout accepted by legacy agent paths |
| `AGENT_WORKER_ID` | generated | No | Identifier for an agent worker process |
| `API_TOKEN` | -- | No | Generic API token accepted by selected automation scripts |
| `APPIUM_HOST` | Appium default | No | Appium host override for mobile tooling |
| `APPIUM_LOG_LEVEL` | Appium default | No | Appium server log-level override |
| `APPIUM_MCP_ON_CLIENT_DISCONNECT` | Appium default | No | Appium MCP disconnect behavior |
| `APPIUM_PATH` | Appium default | No | Appium executable path override |
| `APPIUM_PORT` | Appium default | No | Appium port override |
| `APPIUM_PROTOCOL` | Appium default | No | Appium protocol override |
| `APP_BASE_URL` | -- | No | Frontend/application base URL fallback for generated links |
| `APP_LOGIN_EMAIL` | -- | No | App login email used by selected generated or scripted flows |
| `APP_LOGIN_PASSWORD` | -- | No | App login password used by selected generated or scripted flows |
| `ASSISTANT_ACTION_SECRET` | -- | No | Secret used to authenticate assistant action requests |
| `AUTH_SECRET` | -- | No | Auth secret fallback for assistant/server-side routes |
| `AUTH_SESSIONS_DIR` | `/app/data/auth_sessions` | No | Directory for persisted browser auth sessions |
| `AUTONOMOUS_API_BASE_URL` | backend base URL | No | API URL used by autonomous mission activities when calling back into the backend |
| `BACKUP_DIR` | backup script default | No | Local backup directory override |
| `BROWSER_POOL_TYPE` | `in_memory` | No | Browser pool implementation selector |
| `CLAUDE_CONFIG_DIR` | Claude SDK default | No | Claude configuration directory override for native generator paths |
| `DOCKER_CONTAINER` | -- | No | Marks execution inside a Docker container for environment defaults |
| `ENVIRONMENT` | `development` | No | Runtime environment name |
| `EXPLORATION_TIMEOUT_MINUTES` | feature default | No | Minute-based timeout accepted by legacy exploration paths |
| `FRONTEND_URL` | -- | No | Frontend URL fallback for generated links |
| `GITHUB_EVENT_NAME` | GitHub Actions | No | GitHub event name used by CI-aware tooling |
| `HEALER_ATTEMPT_TIMEOUT_SECONDS` | feature default | No | Timeout for a single healing attempt |
| `HEALER_TIMEOUT_SECONDS` | feature default | No | Overall healing timeout |
| `K6_GENERATOR_TIMEOUT_SECONDS` | feature default | No | K6 generation timeout |
| `MAX_RUN_AGE_MINUTES` | `120` | No | Age after which stale running jobs can be recovered |
| `MEMORY_GRAPH_LLM` | `false` | No | Enable optional LLM extraction for memory graph relationships |
| `MEMORY_GRAPH_LLM_MIN_IMPORTANCE` | feature default | No | Minimum importance threshold for LLM graph extraction |
| `MEMORY_GRAPH_LLM_MODEL` | provider default | No | Model used for optional memory graph extraction |
| `MOBILE_PLATFORM` | feature default | No | Mobile target platform for mobile generation paths |
| `MOBILE_TARGET_URL` | `https://example.com` | No | Default mobile target URL |
| `NEXTAUTH_SECRET` | -- | No | NextAuth-compatible secret fallback for assistant routes |
| `OPENAI_MODEL` | provider default | No | OpenAI model fallback used by selected frontend AI routes |
| `PLAYWRIGHT_AGENT_API_URL` | `http://localhost:8001` | No | Backend URL used by progress reporters and subprocesses |
| `PLAYWRIGHT_MCP_ARGS` | `--browser chromium` | No | Arguments for the Playwright MCP server |
| `PLAYWRIGHT_MCP_COMMAND` | -- | No | Command override for the Playwright MCP server |
| `PLAYWRIGHT_MCP_MIN_VERSION` | `0.0.76` | No | Minimum Playwright MCP package version |
| `PLAYWRIGHT_MCP_PACKAGE` | derived | No | Package spec for Playwright MCP |
| `PRD_TIMEOUT_MINUTES` | feature default | No | Minute-based timeout accepted by legacy PRD paths |
| `PROJECT_ID` | `default` | No | Project scope passed into subprocesses |
| `PR_NUMBER` | CI context | No | Pull request number used by PR advisor tooling |
| `QUORVEX_API_TOKEN` | -- | No | API token used by external Quorvex automation |
| `QUORVEX_API_URL` | -- | No | API URL used by external Quorvex automation |
| `QUORVEX_PROJECT_ID` | -- | No | Project ID used by external Quorvex automation |
| `RECORDER_BROWSER_URL` | -- | No | Browser endpoint used by recording features |
| `RUNS_DIR` | `/app/runs` | No | Run artifact directory override |
| `SUBSET_MANIFEST` | -- | No | CI test subset manifest path |
| `SUBSET_MODE` | -- | No | CI test subset selection mode |
| `USE_AGENT_QUEUE` | `false` | No | Opt into legacy Redis-backed agent queue dispatch instead of direct Temporal activity execution |
| `USE_DIRECT_CLI` | `false` | No | Force direct CLI execution instead of SDK path in selected agents |
| `USE_K6_QUEUE` | `true` | No | Enable Redis-backed K6 queue dispatch |
| `VNC_PUBLIC_URL` | -- | No | Public VNC URL shown in dashboard contexts |
| `WEB_BASE_URL` | -- | No | Web base URL fallback for generated links |
| `WORKER_ID` | generated | No | Generic queue worker identifier |

## Additional Runtime Variables

These variables are used by specialized workflows, browser-auth helpers, generated test-data bindings, and CI/runtime adapters.

| Variable | Default | Required | Description |
|----------|---------|----------|-------------|
| `AGENT_BROWSER_SLOT_TIMEOUT_SECONDS` | feature default | No | Browser slot wait timeout for agent-run subprocesses |
| `AGENT_WORKER_DISABLE_LIVE_BROWSER` | `false` | No | Disable live-browser session attachment in agent workers |
| `API_KEY` | -- | No | Generic API key placeholder accepted by generated specs and test data |
| `API_PASS` | -- | No | Generic API password placeholder accepted by generated specs and test data |
| `API_USER` | -- | No | Generic API username placeholder accepted by generated specs and test data |
| `BROWSER_AUTH_LOGIN_URL` | -- | No | Login URL used by browser auth session capture |
| `BROWSER_AUTH_OUTPUT_PATH` | -- | No | Output path for captured browser storage state |
| `BROWSER_AUTH_PASSWORD` | -- | No | Password used by browser auth session capture |
| `BROWSER_AUTH_PASSWORD_SELECTOR` | -- | No | Password field selector used by browser auth session capture |
| `BROWSER_AUTH_SESSIONS_DIR` | app data default | No | Directory for browser auth session artifacts |
| `BROWSER_AUTH_SUBMIT_SELECTOR` | -- | No | Submit selector used by browser auth session capture |
| `BROWSER_AUTH_SUCCESS_URL_PATTERN` | -- | No | Success URL pattern used to confirm browser auth capture |
| `BROWSER_AUTH_USERNAME` | -- | No | Username used by browser auth session capture |
| `BROWSER_AUTH_USERNAME_CONTINUE_SELECTOR` | -- | No | Optional selector for username-first login flows |
| `BROWSER_AUTH_USERNAME_SELECTOR` | -- | No | Username field selector used by browser auth session capture |
| `BROWSER_HOST_INTERNAL` | -- | No | Internal browser host used by containerized browser workers |
| `BROWSER_SLOT_PARENT_OWNER_TYPE` | -- | No | Parent owner type metadata for browser slot leases |
| `BROWSER_SLOT_PARENT_RUN_ID` | -- | No | Parent run metadata for browser slot leases |
| `NO_PROXY` | -- | No | Proxy bypass list inherited by subprocesses |
| `OPENAPI_IMPORT_CODEGEN_CONCURRENCY` | feature default | No | Concurrent code-generation workers for OpenAPI import |
| `OPENAPI_IMPORT_EXECUTION_CONCURRENCY` | feature default | No | Concurrent execution workers for OpenAPI import |
| `OPENAPI_IMPORT_EXECUTION_TIMEOUT` | feature default | No | Execution timeout for OpenAPI import checks |
| `PLANNER_MAX_ATTEMPTS` | `5` | No | Maximum native planner attempts; values above 5 are capped |
| `PLANNER_REPAIR_TIMEOUT_SECONDS` | feature default | No | Timeout for planner repair passes |
| `PLAYWRIGHT_BROWSERS_PATH` | Playwright default | No | Browser binary path used by Playwright |
| `PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH` | auto-detected | No | Chromium executable override |
| `PLAYWRIGHT_MCP_EXECUTABLE_PATH` | auto-detected | No | Playwright MCP executable override |
| `PLAYWRIGHT_WEB_HOST` | `0.0.0.0` | No | Host used by Playwright-managed web server |
| `PRD_QUEUE_STALE_GRACE_SECONDS` | feature default | No | Grace period before PRD queue items are considered stale |
| `QUORVEX_BROWSER_AUTH_CONTEXT` | -- | No | Browser auth context ID/path passed to generated runs |
| `QUORVEX_EMBEDDING_API_KEY` | -- | No | Embedding API key override |
| `QUORVEX_EMBEDDING_BASE_URL` | -- | No | Embedding API base URL override |
| `QUORVEX_OPENAI_MODEL` | provider default | No | OpenAI-compatible model override used by selected integrations |
| `QUORVEX_RUN_MODEL_TIER` | `standard` | No | Model tier selected for a run |
| `QUORVEX_SETTINGS_ENV_FILE` | app default | No | Settings env file path used for runtime provider persistence |
| `QUORVEX_TEST_DATA_REFS` | -- | No | Serialized test-data references passed to run subprocesses |
| `QUORVEX_TEST_DB_PATH` | -- | No | SQLite test database path override |
| `TEMPORAL_CORS_ORIGINS` | -- | No | CORS origins for Temporal-facing services |
| `TESTDATA_` | -- | No | Prefix for resolved test-data values exposed to subprocesses |
| `TESTDATA_WETRAVEL_AUTH_VALID_USER_PASSWORD` | -- | Demo only | Seeded WeTravel demo password test data |
| `TESTDATA_WETRAVEL_AUTH_VALID_USER_USERNAME` | -- | Demo only | Seeded WeTravel demo username test data |
| `TEST_RUN_STARTUP_IMPORT_RETRIES` | feature default | No | Import retry count for test-run subprocess startup |

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
