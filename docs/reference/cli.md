# CLI Reference

Complete reference for the `orchestrator/cli.py` command-line interface.

## Usage

```bash
python orchestrator/cli.py [SPEC] [OPTIONS]
```

Or via Make:

```bash
make run SPEC=specs/your-test.md
```

## Positional Arguments

| Argument | Required | Description |
|----------|----------|-------------|
| `spec` | No | Path to the markdown spec file or PRD PDF (with `--prd`). Not required for `--explore`, `--run-skill`, `--memory-stats`, `--generate-requirements`, or `--generate-rtm`. |

## Pipeline Mode Flags

| Flag | Type | Default | Description |
|------|------|---------|-------------|
| `--prd` | flag | `false` | Treat input file as a PDF PRD to be processed |
| `--standard-pipeline` | flag | `false` | Use classic pipeline (Plan + Operator + Export + Validate) instead of native |
| `--pipeline` | `standard` / `native` | `native` | **DEPRECATED**. Use `--standard-pipeline` instead |
| `--hybrid` | flag | `false` | Use hybrid healing (3 attempts + Ralph up to 17 more) |
| `--skill-mode` | flag | `false` | Use skill-based execution for complex scenarios |
| `--api` | flag | `false` | Force API test generation mode (auto-detected from spec if not set) |

## General Options

| Flag | Type | Default | Description |
|------|------|---------|-------------|
| `--browser` | `chromium` / `firefox` / `webkit` | `chromium` | Browser to run tests on |
| `--project-id` | string | derived from spec folder | Project ID for memory system isolation |
| `--no-memory` | flag | `false` | Disable memory system for this run |
| `--run-dir` | path | `runs/TIMESTAMP/` | Specific directory to store run artifacts |
| `--try-code` | path | -- | Path to existing generated code to try before regenerating |
| `--interactive` / `-i` | flag | `false` | Enable interactive mode (plan review and step confirmation) |
| `--max-iterations` | int | `20` | Maximum healing iterations (used with `--hybrid`) |
| `--memory-stats` | flag | `false` | Show memory system statistics and exit |

## PRD Options

| Flag | Type | Default | Description |
|------|------|---------|-------------|
| `--prd` | flag | `false` | Treat input as PDF PRD |
| `--feature` | string | -- | Specific feature to generate from PRD (Pipeline only) |
| `--split` | flag | `false` | Split PRD spec into individual test specs (one per test case) |
| `--split-output-dir` | path | `<spec-name>-tests/` | Output directory for split specs |

## Exploration Options

| Flag | Type | Default | Description |
|------|------|---------|-------------|
| `--explore` | URL | -- | Start AI-powered exploration of a web application |
| `--exploration-results` | session ID | -- | View results from an exploration session |
| `--strategy` | `goal_directed` / `breadth_first` / `depth_first` | `goal_directed` | Exploration strategy |
| `--max-interactions` | int | `50` | Maximum interactions for exploration |
| `--timeout` | int | `30` | Exploration timeout in minutes |
| `--login-url` | URL | -- | Login URL for authenticated exploration |

## Requirements & RTM Options

| Flag | Type | Default | Description |
|------|------|---------|-------------|
| `--generate-requirements` | flag | `false` | Generate requirements from exploration data |
| `--from-exploration` | session ID | -- | Exploration session ID to generate requirements from |
| `--generate-rtm` | flag | `false` | Generate Requirements Traceability Matrix |
| `--rtm-export` | `markdown` / `csv` / `html` | -- | Export RTM in specified format |
| `--output` / `-o` | path | -- | Output file path (for exports) |

## API Testing Options

| Flag | Type | Default | Description |
|------|------|---------|-------------|
| `--api` | flag | `false` | Force API test generation mode |
| `--generate-api-tests` | flag | `false` | Generate API tests from exploration data (requires `--from-exploration`) |
| `--api-tests` | flag | `false` | Generate API tests from an OpenAPI/Swagger spec file or URL |
| `--generate-edge-cases` | flag | `false` | Auto-generate edge case and security tests for an API spec |

## Skill Mode Options

| Flag | Type | Default | Description |
|------|------|---------|-------------|
| `--skill-mode` | flag | `false` | Use skill-based execution from spec |
| `--run-skill` | path | -- | Execute a Playwright skill script directly |
| `--skill-timeout` | int | `30000` | Skill script timeout in milliseconds |
| `--skill-headless` | flag | `false` | Run skill scripts in headless mode |

## Legacy Flags (Hidden)

| Flag | Description |
|------|-------------|
| `--ralph` | Legacy healer flag (suppressed from help) |
| `--native-healer` | Legacy flag (suppressed from help) |
| `--native-generator` | Legacy flag (suppressed from help) |

## Command Examples

### Test Generation

```bash
# Default native pipeline
python orchestrator/cli.py specs/login.md

# Hybrid healing
python orchestrator/cli.py specs/login.md --hybrid

# Limit hybrid iterations
python orchestrator/cli.py specs/login.md --hybrid --max-iterations 10

# Firefox browser
python orchestrator/cli.py specs/login.md --browser firefox

# Legacy standard pipeline
python orchestrator/cli.py specs/login.md --standard-pipeline

# Use existing generated code
python orchestrator/cli.py specs/login.md --try-code tests/generated/login.spec.ts

# Disable memory
python orchestrator/cli.py specs/login.md --no-memory
```

### PRD Processing

```bash
# Process entire PRD
python orchestrator/cli.py requirements.pdf --prd

# Process specific feature
python orchestrator/cli.py requirements.pdf --prd --feature "User Login"

# Split multi-test spec
python orchestrator/cli.py specs/prd-feature.md --split
```

### Exploration

```bash
# Explore application
python orchestrator/cli.py --explore https://app.example.com

# With options
python orchestrator/cli.py --explore https://app.example.com \
  --strategy breadth_first \
  --max-interactions 100 \
  --timeout 60

# Authenticated exploration
python orchestrator/cli.py --explore https://app.example.com \
  --login-url https://app.example.com/login

# View exploration results
python orchestrator/cli.py --exploration-results SESSION_ID
```

### Requirements & RTM

```bash
# Generate requirements from exploration
python orchestrator/cli.py --generate-requirements --from-exploration SESSION_ID

# Generate RTM
python orchestrator/cli.py --generate-rtm --project-id my-project

# Export RTM
python orchestrator/cli.py --rtm-export markdown --output rtm.md
python orchestrator/cli.py --rtm-export csv --output rtm.csv
```

### Skill Execution

```bash
# Generate skill from spec
python orchestrator/cli.py specs/test.md --skill-mode

# Run skill script directly
python orchestrator/cli.py --run-skill /path/to/script.js

# With timeout and headless
python orchestrator/cli.py --run-skill /path/to/script.js \
  --skill-timeout 60000 \
  --skill-headless
```

### Memory

```bash
# Show memory statistics
python orchestrator/cli.py --memory-stats

# Memory stats for specific project
python orchestrator/cli.py --memory-stats --project-id my-project
```

## Exit Codes

| Code | Meaning |
|------|---------|
| 0 | Success |
| 1 | Failure (test failed, error, or invalid arguments) |

## Environment Variables

The CLI loads environment variables from `.env` via `orchestrator/load_env.py`. See [Environment Variables](environment-variables.md) for the full list.

Authentication credentials for exploration are read from:
- `LOGIN_EMAIL` or `LOGIN_USERNAME`
- `LOGIN_PASSWORD`

## Run Artifacts

Each run creates a directory in `runs/TIMESTAMP/` containing:

| File | Description |
|------|-------------|
| `plan.json` | Structured test plan |
| `validation.json` | Pass/fail result |
| `execution.log` | Full execution log |
| `*.spec.ts` | Generated Playwright test |
| `screenshots/` | Test screenshots |
| `traces/` | Playwright trace files |

## Related

- [Spec Format](spec-format.md)
- [Pipeline Modes](pipeline-modes.md)
- [Makefile Reference](makefile.md)
- [Environment Variables](environment-variables.md)
