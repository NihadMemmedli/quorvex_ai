# Your First Test in 10 Minutes

In this tutorial, you will install Quorvex AI, write a test spec in plain English, run it through the AI pipeline, and see a fully generated, passing Playwright test.

## Prerequisites

=== "Docker (Recommended)"

    | Tool | Minimum Version | Check Command |
    |------|----------------|---------------|
    | Docker | 20+ | `docker --version` |
    | Docker Compose | 2.x | `docker compose version` |
    | Git | 2.x | `git --version` |

=== "Local"

    | Tool | Minimum Version | Check Command |
    |------|----------------|---------------|
    | Python | 3.10+ | `python3 --version` |
    | Node.js | 20+ | `node -v` |
    | npm | (any) | `npm -v` |
    | Git | 2.x | `git --version` |

## Step 1: Clone the Repository

Open a terminal and clone the project:

```bash
git clone https://github.com/NihadMemmedli/quorvex_ai.git
cd quorvex_ai
```

You should see the project structure:

```
quorvex_ai/
  orchestrator/     # Python backend
  web/              # Next.js frontend
  specs/            # Test specifications
  tests/generated/  # Output: generated Playwright tests
  Makefile          # All project commands
  ...
```

## Step 2: Install and Start

=== "Docker (Recommended)"

    Copy the production environment file and fill in your API credentials:

    ```bash
    cp .env.prod.example .env.prod
    ```

    Edit `.env.prod` and set the required AI credentials (see [Step 3](#step-3-configure-your-api-key) below), then start all services:

    ```bash
    make prod-dev
    ```

    This starts:

    - **Backend API** on `http://localhost:8001` (auto-reload enabled)
    - **Frontend dashboard** on `http://localhost:3000`
    - **PostgreSQL** database
    - **Redis** for job queuing and rate limiting
    - **MinIO** object storage (console at `http://localhost:9001`)
    - **VNC** browser view at `http://localhost:6080`

    Your local `./orchestrator` and `./web/src` directories are mounted, so code changes apply automatically.

    !!! tip
        Run `make prod-status` to verify all services are healthy.

=== "Local"

    Run the setup script to install all dependencies, create a virtual environment, download Playwright browsers, and prepare the directory structure:

    ```bash
    make setup
    ```

    Expected output (abbreviated):

    ```
    [1/7] Checking prerequisites...
      + Python 3.12
      + Node.js v20.11.0
      + npm 10.2.4
    [2/7] Setting up environment configuration...
    [3/7] Setting up Python virtual environment...
    [4/7] Installing Python dependencies...
    [5/7] Installing root Node.js dependencies...
    [6/7] Installing Playwright browsers...
    [7/7] Setting up Web Dashboard...
    Setup Complete!
    ```

    !!! warning
        If you see errors about missing prerequisites, install the required tools before continuing. On macOS, use `brew install python node`. On Ubuntu, use `apt install python3 nodejs npm`.

    Start the dashboard (optional):

    ```bash
    make dev
    ```

## Step 3: Configure Your API Key

Quorvex AI uses an AI model to generate tests. Open the environment file for your setup path and add your API credentials:

=== "Docker"

    ```bash title=".env.prod"
    # Required: AI/LLM configuration
    ANTHROPIC_AUTH_TOKEN=your-api-token-here
    ANTHROPIC_BASE_URL=https://api.anthropic.com
    ANTHROPIC_DEFAULT_SONNET_MODEL=claude-sonnet-4-20250514
    ```

    After editing `.env.prod`, restart the backend to pick up the change:

    ```bash
    make prod-restart
    ```

=== "Local"

    ```bash title=".env"
    # Required: AI/LLM configuration
    ANTHROPIC_AUTH_TOKEN=your-api-token-here
    ANTHROPIC_BASE_URL=https://api.anthropic.com
    ANTHROPIC_DEFAULT_SONNET_MODEL=claude-sonnet-4-20250514
    ```

Replace `your-api-token-here` with your actual API token.

Validate your configuration:

```bash
make check-env
```

Expected output:

```
Checking environment configuration...

  + .env file exists
  + ANTHROPIC_AUTH_TOKEN is configured
  + ANTHROPIC_BASE_URL: https://api.anthropic.com
  + Model: claude-sonnet-4-20250514
  - OPENAI_API_KEY not set (memory system limited)

  + Python virtual environment exists
  + Frontend dependencies installed
```

## Step 4: Write a Test Spec

A test spec is a markdown file that describes what to test in plain English. Create your first spec:

```bash
cat > specs/my-first-test.md << 'EOF'
# Test: Hello World Check

## Description
Verify that the dynamic loading example on the-internet.herokuapp.com works correctly.

## Steps
1. Navigate to https://the-internet.herokuapp.com/dynamic_loading/1
2. Click the "Start" button
3. Wait for the loading to complete
4. Verify the text "Hello World!" is visible

## Expected Outcome
- The "Hello World!" message is displayed after loading completes
EOF
```

!!! tip
    Every spec needs a URL in the steps (e.g., "Navigate to https://..."). This tells the AI which page to test. See [Writing Specs](../guides/writing-specs.md) for the full format reference.

The spec format has three required sections:

| Section | Purpose |
|---------|---------|
| `# Test: ...` | The test name, used for the output filename |
| `## Steps` | Numbered list of actions in plain English |
| `## Expected Outcome` | What success looks like |

## Step 5: Run the Pipeline

Run your spec through the AI pipeline:

```bash
make run SPEC=specs/my-first-test.md
```

Or use the CLI directly (local setup only):

```bash
source venv/bin/activate
python orchestrator/cli.py specs/my-first-test.md
```

The pipeline has three stages:

1. **Planning** -- the AI reads your spec and creates a structured test plan (target URL, steps, assertions).
2. **Generation** -- the AI opens a real browser, explores the target page, and writes Playwright test code.
3. **Healing** -- if the generated test fails, the AI debugs it using browser tools (up to 3 attempts).

You should see the pipeline progress through all three stages and finish with `Status: passed`. The generated test file is saved to `tests/generated/hello-world-check.spec.ts`.

!!! note
    The first run takes longer because the AI needs to explore the page. Subsequent runs of the same spec are faster thanks to the Smart Check feature, which reuses existing generated code.

## Step 6: Inspect the Generated Test

Open the generated test file to see what the AI produced:

```bash
cat tests/generated/hello-world-check.spec.ts
```

You should see a complete Playwright test similar to:

```typescript title="tests/generated/hello-world-check.spec.ts"
import { test, expect } from '@playwright/test';

test('Hello World Check', async ({ page }) => {
  // Step 1: Navigate to the dynamic loading page
  await page.goto('https://the-internet.herokuapp.com/dynamic_loading/1');

  // Step 2: Click the Start button
  await page.getByRole('button', { name: 'Start' }).click();

  // Step 3-4: Wait for and verify "Hello World!" text
  await expect(page.getByText('Hello World!')).toBeVisible({ timeout: 30000 });
});
```

Notice that the AI:

- Used resilient selectors (`getByRole`, `getByText`) instead of brittle CSS selectors
- Added an appropriate timeout for the dynamic loading
- Mapped your English steps to real Playwright API calls

## Step 7: Run the Test Directly

You can re-run the generated test anytime without going through the pipeline:

```bash
npx playwright test tests/generated/hello-world-check.spec.ts
```

Expected output:

```
Running 1 test using 1 worker

  PASSED  hello-world-check.spec.ts (3.8s)

  1 passed (4.1s)
```

Add `--headed` to watch the browser execute the test visually.

## Step 8: Review Pipeline Artifacts

Every pipeline run produces artifacts in the `runs/` directory:

```bash
ls runs/2026-03-01_10-00-00/
```

```
plan.json           # Structured test plan from Stage 1
export.json         # Generated code metadata from Stage 2
spec.md             # Copy of your spec
status.txt          # Final result: "passed" or "error"
```

Inspect `plan.json` to see the AI's interpretation of your spec -- it contains the target URL, test name, and structured steps.

## Step 9: Try a Second Test

Now write a slightly more complex spec:

```bash
cat > specs/form-validation-test.md << 'EOF'
# Test: Form Authentication

## Description
Test the login form on the-internet.herokuapp.com with valid credentials.

## Steps
1. Navigate to https://the-internet.herokuapp.com/login
2. Enter "tomsmith" into the Username field
3. Enter "SuperSecretPassword!" into the Password field
4. Click the "Login" button
5. Verify the page displays "You logged into a secure area!"

## Expected Outcome
- The user is redirected to the secure area after login
- A success message is displayed
EOF
```

Run it:

```bash
make run SPEC=specs/form-validation-test.md
```

This test exercises form filling and navigation, demonstrating that the AI handles multi-step interactions.

## Step 10: Run All Generated Tests

After generating multiple tests, run them all at once:

```bash
npx playwright test
```

This runs every `.spec.ts` file in the `tests/generated/` directory.

## Managing Services (Docker)

If you used the Docker setup, these commands help you manage the environment:

| Command | Description |
|---------|-------------|
| `make prod-dev` | Start with local code mounting (dev mode) |
| `make prod-up` | Start production services |
| `make prod-restart` | Restart backend (picks up code changes) |
| `make prod-logs` | Tail all service logs |
| `make prod-status` | Show status of all services |
| `make prod-down` | Stop all services |
| `make prod-build` | Rebuild Docker images |

## What You Learned

In this tutorial, you:

- Installed Quorvex AI using Docker (`make prod-dev`) or locally (`make setup`)
- Configured API credentials in `.env.prod` (Docker) or `.env` (local)
- Wrote a test spec in plain English markdown
- Ran the Pipeline to generate a Playwright test
- Inspected the generated test code and pipeline artifacts
- Ran the generated test directly with Playwright
- Created a second test to see multi-step interactions

## Next Steps

- [Dashboard Walkthrough](./dashboard-walkthrough.md) -- manage specs and runs through the web UI
- [Your First API Test](./first-api-test.md) -- generate HTTP API tests without a browser
- [App Exploration and Requirements](./first-exploration.md) -- let AI discover your app automatically
- [Writing Specs](../guides/writing-specs.md) -- full spec format reference with templates and credentials
- [Environment Variables](../reference/environment-variables.md) -- configure timeouts, browsers, and more
