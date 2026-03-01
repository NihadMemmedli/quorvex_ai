# How to Set Up TestRail, Jira, and CI/CD Integrations

Connect Quorvex AI with external tools for test case management, issue tracking, and continuous integration pipelines.

## Prerequisites

- Quorvex AI installed and running (`make dev` or `make prod-dev`)
- For TestRail: a TestRail account with API access enabled
- For Jira: a Jira Cloud or Server instance with API token
- For CI/CD: a GitHub or GitLab repository

## Part 1: TestRail Integration

### Step 1: Configure TestRail Credentials

#### Via Dashboard

1. Navigate to **Settings** (`/settings`)
2. Open the **Integrations** tab
3. Under **TestRail**, enter:
   - **Base URL** -- your TestRail instance URL (e.g., `https://yourcompany.testrail.io`)
   - **Email** -- your TestRail login email
   - **API Key** -- generated from TestRail: My Settings > API Keys
4. Click **Test Connection** to verify
5. Click **Save**

#### Via API

```bash
# Save TestRail configuration
curl -X POST http://localhost:8001/testrail/your-project-id/config \
  -H "Content-Type: application/json" \
  -d '{
    "base_url": "https://yourcompany.testrail.io",
    "email": "user@yourcompany.com",
    "api_key": "your-testrail-api-key",
    "project_id": 1,
    "suite_id": 1
  }'

# Test connection
curl -X POST http://localhost:8001/testrail/your-project-id/test-connection
```

The API key is encrypted at rest using the `JWT_SECRET_KEY`.

### Step 2: Select TestRail Project and Suite

```bash
# List available TestRail projects
curl http://localhost:8001/testrail/your-project-id/remote-projects

# List suites in a project
curl http://localhost:8001/testrail/your-project-id/remote-suites/1
```

Set the project and suite IDs in the configuration.

### Step 3: Push Test Cases to TestRail

Sync local specs to TestRail as test cases:

```bash
curl -X POST http://localhost:8001/testrail/your-project-id/push-cases
```

This:
- Creates test cases in TestRail with steps and expected results
- Maintains local-to-TestRail ID mappings for incremental sync
- Only pushes new or modified cases on subsequent syncs

View mappings:

```bash
curl http://localhost:8001/testrail/your-project-id/mappings
```

### Step 4: Sync Regression Results to TestRail

After running a regression batch, push results as a TestRail test run:

```bash
# Preview what will be synced
curl http://localhost:8001/testrail/your-project-id/sync-preview/BATCH_ID

# Push results
curl -X POST http://localhost:8001/testrail/your-project-id/sync-results \
  -H "Content-Type: application/json" \
  -d '{"batch_id": "BATCH_ID"}'
```

Each test run in the batch maps to a TestRail result with pass/fail status.

---

## Part 2: Jira Integration

### Step 1: Configure Jira Credentials

#### Via Dashboard

1. Navigate to **Settings > Integrations**
2. Under **Jira**, enter:
   - **Base URL** -- your Jira instance (e.g., `https://yourcompany.atlassian.net`)
   - **Email** -- your Jira account email
   - **API Token** -- generated from Atlassian: Account Settings > Security > API Tokens
   - **Project Key** -- the Jira project key (e.g., `QA`)
3. Click **Save**

#### Via API

```bash
curl -X POST http://localhost:8001/jira/your-project-id/config \
  -H "Content-Type: application/json" \
  -d '{
    "base_url": "https://yourcompany.atlassian.net",
    "email": "user@yourcompany.com",
    "api_token": "your-jira-api-token",
    "project_key": "QA"
  }'
```

### Step 2: Link Test Failures to Jira Issues

When a test fails, create or link a Jira issue:

1. In the **Runs** page, click on a failed test
2. Click **Create Jira Issue** to file a bug with failure details
3. Or click **Link to Existing** to connect to an existing Jira ticket

The created issue includes:
- Test spec name and failure description
- Error messages and stack traces
- Links back to the Quorvex AI run

---

## Part 3: GitHub Actions Integration

### Step 1: Generate a GitHub Actions Workflow

#### Via Dashboard

1. Navigate to **CI/CD** (`/ci-cd`)
2. Select **GitHub Actions**
3. Configure the workflow:
   - Trigger events (push, pull_request, schedule)
   - Specs to run
   - Browser selection
4. Click **Generate Workflow**
5. Copy the generated YAML

#### Via API

```bash
curl -X POST http://localhost:8001/github/your-project-id/generate-workflow \
  -H "Content-Type: application/json" \
  -d '{
    "trigger": "pull_request",
    "specs": ["spec-1", "spec-2"],
    "browser": "chromium"
  }'
```

### Step 2: Add the Workflow to Your Repository

Save the generated YAML as `.github/workflows/playwright-tests.yml` in your repository.

The workflow:
1. Checks out your code
2. Sets up Node.js and Playwright
3. Runs the specified test specs
4. Uploads test artifacts (traces, screenshots)

### Step 3: Configure GitHub Webhook (Optional)

Set up a webhook to report test results back to Quorvex AI:

```bash
curl -X POST http://localhost:8001/github/your-project-id/webhook-config \
  -H "Content-Type: application/json" \
  -d '{
    "repo_url": "https://github.com/org/repo",
    "webhook_secret": "your-webhook-secret"
  }'
```

---

## Part 4: GitLab CI Integration

### Step 1: Generate a GitLab CI Configuration

#### Via Dashboard

1. Navigate to **CI/CD** (`/ci-cd`)
2. Select **GitLab CI**
3. Configure pipeline settings
4. Click **Generate Configuration**
5. Copy the generated `.gitlab-ci.yml`

#### Via API

```bash
curl -X POST http://localhost:8001/gitlab/your-project-id/generate-config \
  -H "Content-Type: application/json" \
  -d '{
    "specs": ["spec-1", "spec-2"],
    "browser": "chromium"
  }'
```

### Step 2: Add to Your Repository

Save the generated content as `.gitlab-ci.yml` in your repository root.

---

## Verification

Confirm each integration works:

**TestRail:**
1. Connection test returns success
2. Push-cases creates test cases visible in TestRail
3. Sync-results creates a test run in TestRail with correct pass/fail statuses

**Jira:**
1. Configuration saves without errors
2. Creating a Jira issue from a failed run produces a ticket in the correct project

**GitHub/GitLab:**
1. Generated workflow YAML is valid (passes CI lint)
2. Running the workflow in CI executes the specified tests
3. Test artifacts are uploaded and accessible

## Related Guides

- [Regression Batches](./regression-batches.md) -- create batches to sync with TestRail
- [Scheduling](./scheduling.md) -- automate test runs for CI reporting
- [Authentication](./authentication.md) -- secure your Quorvex AI instance
- [Credential Management](./credential-management.md) -- rotate integration API keys
