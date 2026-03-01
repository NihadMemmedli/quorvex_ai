# How to Contribute to Quorvex AI

Set up a development environment, follow code style conventions, run tests, and submit pull requests.

## Prerequisites

- Git, Python 3.10+, Node.js 18+, npm 9+
- A GitHub account with a fork of the repository
- Docker (optional, for PostgreSQL and production testing)

## Step 1: Fork and Clone

```bash
# Fork the repository on GitHub, then:
git clone https://github.com/YOUR_USERNAME/quorvex_ai.git
cd quorvex_ai
```

## Step 2: Set Up the Development Environment

```bash
make setup
```

This creates a Python virtual environment, installs all dependencies, installs Playwright browsers, and initializes the database.

Configure AI credentials in `.env`:

```bash
cp .env.example .env
# Edit .env with your ANTHROPIC_AUTH_TOKEN
```

## Step 3: Start Development Servers

```bash
make dev
```

- **Backend API**: http://localhost:8001 (FastAPI with hot-reload)
- **Frontend**: http://localhost:3000 (Next.js with hot-reload)

Verify:

```bash
make check-env    # Validate configuration
make test         # Run Python tests
make lint         # Check code style
```

## Step 4: Create a Feature Branch

```bash
git checkout -b feature/your-feature-name
# or
git checkout -b fix/brief-bug-description
```

Branch naming conventions:
- `feature/` -- new functionality
- `fix/` -- bug fixes
- `docs/` -- documentation changes
- `refactor/` -- code restructuring

## Step 5: Follow Code Style

### Python

Enforced by [ruff](https://docs.astral.sh/ruff/) (config in `orchestrator/pyproject.toml`):

- Line length: 120 characters
- Double quotes
- Imports sorted by isort
- Target: Python 3.10

```bash
make format   # Auto-format
make lint     # Check violations
```

### General Guidelines

- Use `logging.getLogger(__name__)` instead of `print()` in backend code
- Load AI credentials via `setup_claude_env()` before using the Agent SDK
- Use `extract_json_from_markdown()` for parsing AI output
- Prefer role-based Playwright selectors (`getByRole`, `getByLabel`) over CSS selectors

### Frontend

Next.js default linting:

```bash
cd web && npm run lint
```

## Step 6: Run Tests Before Submitting

```bash
# All Python tests
make test

# Specific test file
cd orchestrator && python -m pytest tests/test_09_memory_system.py -v

# Lint check
make lint
```

If you changed a pipeline stage, run end-to-end:

```bash
python orchestrator/cli.py specs/your-test.md
```

## Step 7: Write Clear Commit Messages

Follow [Conventional Commits](https://www.conventionalcommits.org/):

```
feat: Add API endpoint for bulk test execution
fix: Prevent crash when spec has no URL
docs: Add load testing guide
refactor: Extract selector parsing into utility
test: Add browser pool unit tests
chore: Update ruff to 0.5.0
```

## Step 8: Open a Pull Request

1. Push your branch to your fork
2. Open a PR against `main` on the upstream repository
3. Fill out the PR description with what changed and why
4. Link related issues (e.g., "Fixes #42")
5. Ensure CI checks pass

!!! note
    Some CI jobs (smoke tests, end-to-end pipeline tests) require API credentials unavailable to forks. These are **automatically skipped** for external contributors. A maintainer will run the full suite after review.

## Step 9: Address Review Feedback

- Push additional commits to address feedback (do not force-push during review)
- Once approved, a maintainer merges the PR

## Types of Contributions

| Type | Description |
|------|-------------|
| Bug fixes | Fix reported issues or flaky tests |
| Features | New capabilities, pipeline improvements, dashboard pages |
| Documentation | Improve guides, add examples, fix typos |
| Test specs | Example markdown specs for common scenarios |
| Integrations | Support for new CI providers, test tools, or LLM providers |
| Performance | Optimize pipeline stages, reduce resource usage |

## First-Time Contributors

Look for issues labeled:

- `good first issue` -- small, well-defined tasks
- `help wanted` -- maintainers welcome contributions
- `documentation` -- documentation improvements

Good starting points:

1. Write a new test spec in `specs/`
2. Improve an error message
3. Add a troubleshooting entry
4. Fix a typo in documentation

## Verification

Before submitting your PR:

1. `make lint` passes without errors
2. `make test` passes all tests
3. `make dev` starts and the dashboard loads
4. If you changed a pipeline stage, run a test spec end-to-end
5. Your commit messages follow conventional commits format

## Related Guides

- [Extending](./extending.md) -- add new features to the codebase
- [Getting Started](../tutorials/getting-started.md) -- development setup
- [Pipeline Modes](./pipeline-modes.md) -- understand the architecture
- [Troubleshooting](./troubleshooting.md) -- fix common dev issues
