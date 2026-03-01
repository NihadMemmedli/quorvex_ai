# Contributing to Quorvex AI

Thank you for your interest in contributing to Quorvex AI! Whether you're fixing a typo, reporting a bug, adding a feature, or improving documentation, your help is welcome and appreciated.

This guide will help you get started.

---

## Table of Contents

- [Code of Conduct](#code-of-conduct)
- [How to Contribute](#how-to-contribute)
- [Development Setup](#development-setup)
- [Architecture Overview](#architecture-overview)
- [Code Style](#code-style)
- [Testing](#testing)
- [Pull Request Process](#pull-request-process)
- [First-Time Contributors](#first-time-contributors)
- [CI Notes](#ci-notes)
- [Getting Help](#getting-help)

---

## Code of Conduct

This project follows the [Contributor Covenant Code of Conduct](CODE_OF_CONDUCT.md). By participating, you agree to uphold a welcoming, inclusive, and respectful environment.

---

## How to Contribute

### Reporting Bugs

If you find a bug, please [open an issue](https://github.com/NihadMemmedli/quorvex_ai/issues/new) with:

- A clear, descriptive title
- Steps to reproduce the problem
- Expected vs. actual behavior
- Your environment (OS, Python version, Node.js version, browser)
- Relevant log output or screenshots

### Suggesting Features

Feature ideas are welcome. Open an issue with the **feature request** label and describe:

- The problem your feature would solve
- How you envision it working
- Whether you'd be interested in implementing it

### Types of Contributions

| Type | Description |
|------|-------------|
| **Bug fixes** | Fix reported issues or flaky tests |
| **Features** | New capabilities, pipeline improvements, dashboard pages |
| **Documentation** | Improve guides, add examples, fix typos |
| **Test specs** | Contribute example markdown specs for common testing scenarios |
| **Integrations** | Add support for new CI providers, test management tools, or LLM providers |
| **Performance** | Optimize pipeline stages, reduce resource usage |

---

## Development Setup

### 1. Fork and Clone

```bash
# Fork the repository on GitHub, then:
git clone https://github.com/YOUR_USERNAME/quorvex_ai.git
cd quorvex_ai
```

### 2. Run Setup

```bash
make setup
```

This creates a Python virtual environment, installs all Python and Node.js dependencies, installs Playwright browsers, and initializes the database.

### 3. Configure Environment

```bash
cp .env.example .env
```

Edit `.env` and set your AI provider credentials at minimum:

```env
ANTHROPIC_AUTH_TOKEN=your-api-key
ANTHROPIC_BASE_URL=https://api.anthropic.com
ANTHROPIC_DEFAULT_SONNET_MODEL=claude-sonnet-4-20250514
```

### 4. Start Development Servers

```bash
make dev
```

This starts:
- **Backend API** at http://localhost:8001 (FastAPI with hot-reload)
- **Frontend** at http://localhost:3000 (Next.js with hot-reload)

### 5. Verify Setup

```bash
make check-env    # Validate environment configuration
make test         # Run Python test suite
make lint         # Check code style
```

---

## Architecture Overview

Quorvex AI has a dual-interface architecture:

```
CLI (orchestrator/cli.py)          Web Dashboard (web/)
         |                                |
         v                                v
   Python Backend (orchestrator/)
         |
    +---------+-----------+-----------+
    |         |           |           |
  Planner  Generator   Healer     Explorer
    |         |           |           |
    v         v           v           v
          Playwright (browser automation)
```

### Key Directories

| Directory | Purpose |
|-----------|---------|
| `orchestrator/api/` | FastAPI REST endpoints |
| `orchestrator/workflows/` | Pipeline stages (planner, generator, healer, explorer) |
| `orchestrator/services/` | Browser pool, scheduler, storage, queues |
| `orchestrator/memory/` | Vector store, graph store for exploration data |
| `orchestrator/utils/` | Shared utilities (agent runner, JSON parsing) |
| `web/src/app/(dashboard)/` | Next.js frontend pages |
| `specs/` | Markdown test specifications |
| `tests/generated/` | Output Playwright tests |

### Pipeline Architecture

The **Native Pipeline** is the default and recommended pipeline:

1. **NativePlanner** -- Reads the spec, explores the target app, creates an execution plan
2. **NativeGenerator** -- Uses the plan and browser context to write Playwright TypeScript
3. **NativeHealer** -- If validation fails, debugs and fixes the generated code (up to 3 attempts)

Each stage runs as a **separate subprocess** to isolate SDK cleanup issues. The main orchestrator (`cli.py`) spawns stages via `run_command()`.

The **Standard Pipeline** (`--standard-pipeline`) is the legacy text-only approach and is not recommended for new development.

---

## Code Style

### Python

Python code is enforced by [ruff](https://docs.astral.sh/ruff/). Configuration is in `orchestrator/pyproject.toml`.

- **Line length**: 120 characters
- **Quotes**: Double quotes
- **Imports**: Sorted by isort (via ruff)
- **Target**: Python 3.10
- **Ignored rules**: `B008` (FastAPI `Depends()` in function defaults is intentional)

Run the formatter and linter:

```bash
make format   # Auto-format Python code
make lint     # Check for style violations
```

### Frontend (TypeScript/React)

Frontend code follows Next.js default linting:

```bash
cd web && npm run lint
```

### General Guidelines

- Use `logging.getLogger(__name__)` instead of `print()` in all backend code
- Load AI credentials via `orchestrator/load_env.py` -- call `setup_claude_env()` before using the Agent SDK
- Use `orchestrator/utils/json_utils.py:extract_json_from_markdown()` for parsing AI output
- Prefer role-based Playwright selectors (`getByRole`, `getByLabel`) over CSS selectors

---

## Testing

### Running Tests

```bash
# All Python tests
make test

# Specific test file
cd orchestrator && python -m pytest tests/test_09_memory_system.py -v

# All tests with verbose output
cd orchestrator && python -m pytest tests/ -v

# Skip integration tests (no API keys needed)
cd orchestrator && python -m pytest tests/ -v -m "not integration"
```

Pytest configuration is in `orchestrator/pytest.ini` with `asyncio_mode = auto`.

### Running Linters

```bash
make lint      # ruff check (Python) + next lint (frontend)
make format    # ruff format (Python)
```

### Testing Your Changes

Before submitting a PR, verify:

1. **Linting passes**: `make lint`
2. **Tests pass**: `make test`
3. **The dashboard loads**: `make dev` and open http://localhost:3000
4. **If you changed a pipeline stage**: Run a test spec end-to-end:
   ```bash
   python orchestrator/cli.py specs/your-test.md
   ```

---

## Pull Request Process

### 1. Create a Branch

```bash
git checkout -b feature/your-feature-name
# or
git checkout -b fix/brief-bug-description
```

Branch naming conventions:
- `feature/` -- New functionality
- `fix/` -- Bug fixes
- `docs/` -- Documentation changes
- `refactor/` -- Code restructuring without behavior changes

### 2. Make Focused Changes

- Keep PRs focused on a single concern
- Avoid mixing unrelated changes in one PR
- If you discover a separate issue while working, open a new issue for it

### 3. Write Clear Commit Messages

```
feat: Add API endpoint for bulk test execution

Adds POST /api/bulk-run endpoint that accepts multiple spec IDs
and queues them for parallel execution through the browser pool.
```

Follow [Conventional Commits](https://www.conventionalcommits.org/) format:
- `feat:` -- New feature
- `fix:` -- Bug fix
- `docs:` -- Documentation only
- `refactor:` -- Code change that neither fixes a bug nor adds a feature
- `test:` -- Adding or updating tests
- `chore:` -- Build process, dependency updates, tooling

### 4. Open the Pull Request

- Push your branch and open a PR against `main`
- Fill out the PR template with a description of your changes
- Link related issues (e.g., "Fixes #42")
- Ensure CI checks pass

### 5. Code Review

- A maintainer will review your PR
- Address feedback by pushing additional commits (do not force-push during review)
- Once approved, a maintainer will merge your PR

---

## First-Time Contributors

New to the project? Look for issues labeled:

- **`good first issue`** -- Small, well-defined tasks suitable for newcomers
- **`help wanted`** -- Issues where maintainers welcome community contributions
- **`documentation`** -- Improvements to guides, README, or inline docs

Good starting points:

1. **Add a test spec** -- Write a new markdown spec in `specs/` for a common testing scenario
2. **Improve error messages** -- Find a confusing error and make it more descriptive
3. **Add a troubleshooting entry** -- Document a problem you encountered and its solution
4. **Fix a typo** -- Documentation improvements are always welcome

---

## CI Notes

The CI pipeline runs on every pull request:

- **Linting**: `ruff check` (Python) and `next lint` (frontend)
- **Unit tests**: `pytest tests/ -v`
- **Build check**: Frontend build verification

### External Contributors

Some CI jobs (smoke tests, end-to-end pipeline tests) require API credentials that are not available to forks. These jobs are **automatically skipped** for external contributors. This is expected -- a maintainer will run the full test suite after reviewing your changes.

If a CI check fails on something unrelated to your changes, note it in your PR and a maintainer will investigate.

---

## Getting Help

- **Questions**: Open a [GitHub Discussion](https://github.com/NihadMemmedli/quorvex_ai/discussions)
- **Bug reports**: Open a [GitHub Issue](https://github.com/NihadMemmedli/quorvex_ai/issues)
- **Architecture questions**: Check [docs/architecture/](docs/architecture/) for system design details
- **API reference**: See [docs/api-reference/](docs/api-reference/) for endpoint documentation

Thank you for contributing to Quorvex AI!
