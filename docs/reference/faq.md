# Frequently Asked Questions

## General

### What is Quorvex AI?

Quorvex AI is an AI-powered test automation platform that converts natural language test specifications (written in markdown) into production-ready Playwright tests. It features a three-stage Pipeline (Plan, Generate, Heal) that explores your application with a real browser, writes validated TypeScript test code, and automatically repairs failures.

### What AI providers does Quorvex AI support?

Quorvex AI uses the Anthropic Claude API as its primary AI provider. Supported connection methods:

| Method | `ANTHROPIC_BASE_URL` |
|--------|---------------------|
| Anthropic direct | `https://api.anthropic.com` |
| OpenRouter | `https://openrouter.ai/api` |
| Custom proxy | Any API-compatible endpoint |

### Does Quorvex AI require an internet connection?

Yes. The AI pipeline requires access to the configured AI provider API. Playwright requires network access to the target application under test. The dashboard itself runs locally.

### What is the license?

MIT License. Free to use, modify, and distribute for personal and commercial purposes.

## System Requirements

| Requirement | Minimum |
|-------------|---------|
| Python | 3.10+ |
| Node.js | 18+ |
| Playwright browsers | Installed via `make setup` |
| Database | SQLite (default) or PostgreSQL (production) |
| Docker | Optional (required for production, K6 workers, ZAP) |
| Redis | Optional (distributed queues, rate limiting) |

## Setup & Configuration

### Can I run Quorvex AI without Docker?

Yes. Run `make setup` then `make dev` for local development using Python and Node.js natively. Docker is only required for production deployments, distributed K6 load testing workers, and ZAP security scanning.

### How do I migrate from SQLite to PostgreSQL?

1. Set `DATABASE_URL` in `.env` to a PostgreSQL connection string
2. Run `make db-upgrade`
3. Restart the backend

Existing SQLite data is not automatically migrated.

## Test Generation

### How does the Pipeline work?

| Stage | Description |
|-------|-------------|
| Planner | Reads spec, launches browser, explores target app, produces plan with discovered selectors |
| Generator | Takes plan, uses live browser context, writes Playwright TypeScript code |
| Healer | Runs test; on failure, debugs with Playwright tools, rewrites code (up to 3 attempts, or 20 with `--hybrid`) |

### What happens when a generated test breaks after a UI change?

1. Smart Check detects existing generated code
2. Runs the existing test first
3. On failure, Healer analyzes failure, explores current page state, regenerates broken selectors
4. For stubborn failures, use `--hybrid` mode (up to 20 healing iterations)

### How do I test applications that require authentication?

Use credential placeholders in specs (`{{VARIABLE_NAME}}`), define values in `.env`. Generated code uses `process.env.VARIABLE_NAME`.

## Troubleshooting

| Symptom | Solution |
|---------|----------|
| "ANTHROPIC_AUTH_TOKEN not set" | Check `.env` file, run `make check-env` |
| Generated tests keep timing out | Increase `AGENT_TIMEOUT_SECONDS` or `GENERATOR_TIMEOUT_SECONDS` in `.env` |
| Dashboard won't start | Check ports 8001 (backend) and 3000 (frontend) are available. Run `make logs` for errors. |
| "Account locked" on login | Wait 30 minutes or clear lockout in database |
| "Invalid token" errors | Refresh token expired; re-login required |
| Registration disabled | Set `ALLOW_REGISTRATION=true` in `.env` |
| ZAP not reachable | Start with: `docker compose --profile security up -d zap` |
| Nuclei not found | Install nuclei binary or use Docker security profile |
| `make prod-dev` backend won't start | Check `docker logs` for migration errors |
| "No target URL found in spec" | Spec must contain a URL (e.g., "Navigate to https://...") |
| Test keeps failing after healing | Use `--hybrid` for more healing iterations |
| Exploration stops early | Increase `--max-interactions` (default: 50) |

## Related

- [Environment Variables](environment-variables.md)
- [CLI Reference](cli.md)
