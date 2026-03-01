# CI/CD Setup

In this tutorial, you will configure Quorvex AI to run generated Playwright tests automatically in a CI/CD pipeline. You will set up GitHub Actions (with GitLab CI as an alternative), connect it to the dashboard, and see test results flow back.

## Prerequisites

- Quorvex AI installed with at least one generated test (complete [Your First Test in 10 Minutes](./getting-started.md) first)
- A GitHub or GitLab repository where you can push code
- A Personal Access Token for your Git provider

## Overview

The CI/CD integration has two parts:

1. **Workflow file** -- a GitHub Actions or GitLab CI configuration that runs Playwright tests on every push or pull request
2. **Dashboard connection** -- links your CI provider to the Quorvex AI dashboard for triggering runs and tracking results

You can use either part independently. The workflow file works standalone; the dashboard connection adds remote triggering and status tracking.

## Part A: GitHub Actions Workflow

### Step 1: Create the Workflow File

Create a GitHub Actions workflow in your repository:

```bash
mkdir -p .github/workflows
```

Create the workflow file:

```yaml title=".github/workflows/playwright.yml"
name: Playwright Tests

on:
  push:
    branches: [main]
  pull_request:
    branches: [main]

jobs:
  test:
    timeout-minutes: 60
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-node@v4
        with:
          node-version: 20

      - name: Install dependencies
        run: npm ci

      - name: Install Playwright Browsers
        run: npx playwright install --with-deps

      - name: Run Playwright tests
        run: npx playwright test

      - uses: actions/upload-artifact@v4
        if: always()
        with:
          name: playwright-report
          path: playwright-report/
          retention-days: 30
```

This workflow:

- Triggers on pushes to `main` and on pull requests
- Installs Node.js, project dependencies, and Playwright browsers
- Runs all Playwright tests in `tests/generated/`
- Uploads the HTML report as an artifact (available for 30 days)

### Step 2: Commit and Push

Add the workflow file and your generated tests to Git:

```bash
git add .github/workflows/playwright.yml
git add tests/generated/
git add playwright.config.ts
git add package.json package-lock.json
git commit -m "Add Playwright CI workflow and generated tests"
git push origin main
```

### Step 3: Verify the Pipeline

Open your GitHub repository in a browser and navigate to the **Actions** tab. You should see the "Playwright Tests" workflow running.

When it completes:

- **Green check** -- all tests passed
- **Red X** -- one or more tests failed; click the run to see details
- **Artifacts** -- download the `playwright-report` artifact for an HTML report

!!! tip
    Click on the failed test in the Actions log to see the exact error message and stack trace. The Playwright HTML report (in the artifact) provides screenshots and traces for debugging.

### Step 4: Add Environment Variables

If your tests use credential placeholders (e.g., `{{LOGIN_PASSWORD}}`), add them as GitHub repository secrets:

1. Go to your repo **Settings** > **Secrets and variables** > **Actions**.
2. Click **New repository secret**.
3. Add each variable (e.g., `LOGIN_PASSWORD`).

Update the workflow to pass secrets as environment variables:

```yaml title=".github/workflows/playwright.yml"
      - name: Run Playwright tests
        run: npx playwright test
        env:
          LOGIN_PASSWORD: ${{ secrets.LOGIN_PASSWORD }}
          BASE_URL: ${{ vars.BASE_URL }}
```

!!! warning
    Never commit credentials to your repository. Always use GitHub Secrets for sensitive values.

## Part B: GitLab CI (Alternative)

If you use GitLab instead of GitHub, create a `.gitlab-ci.yml` file:

```yaml title=".gitlab-ci.yml"
stages:
  - test

playwright-tests:
  stage: test
  image: mcr.microsoft.com/playwright:v1.49.0-jammy
  script:
    - npm ci
    - npx playwright test
  artifacts:
    when: always
    paths:
      - playwright-report/
    expire_in: 30 days
  rules:
    - if: $CI_PIPELINE_SOURCE == "merge_request_event"
    - if: $CI_COMMIT_BRANCH == "main"
```

Commit and push:

```bash
git add .gitlab-ci.yml
git commit -m "Add GitLab CI Playwright pipeline"
git push origin main
```

Add environment variables in GitLab under **Settings** > **CI/CD** > **Variables**.

## Part C: Connect CI to the Dashboard

The dashboard can trigger CI pipelines and track their status without leaving the Quorvex AI interface.

### Step 1: Start the Dashboard

```bash
make dev
```

!!! tip
    Docker users should run `make prod-dev` instead of `make dev`.

### Step 2: Open CI/CD Settings

1. Open `http://localhost:3000` and navigate to **CI/CD** in the sidebar.
2. Choose your provider tab: **GitHub** or **GitLab**.

### Step 3: Configure GitHub Connection

Fill in the configuration form:

| Field | Value | Description |
|-------|-------|-------------|
| **Owner** | Your GitHub username or org | e.g., `my-org` |
| **Repository** | Your repo name | e.g., `my-test-project` |
| **Token** | Personal Access Token | Needs `repo` and `workflow` scopes |
| **Default Workflow** | `playwright.yml` | The workflow filename |
| **Default Branch** | `main` | Branch to trigger runs on |

Click **Save**, then **Test Connection** to verify.

Expected output:

```
Connection successful
User: your-github-username
```

!!! note
    Generate a GitHub Personal Access Token at `https://github.com/settings/tokens`. Select **Fine-grained tokens** with `Actions: Read and write` and `Contents: Read` permissions for the target repository.

### Step 4: Configure GitLab Connection (Alternative)

| Field | Value | Description |
|-------|-------|-------------|
| **Base URL** | `https://gitlab.com` | Your GitLab instance URL |
| **Access Token** | Personal Access Token | Needs `api` scope |
| **Project ID** | Your GitLab project ID | Found in project settings |
| **Default Branch** | `main` | Branch to trigger pipelines on |

### Step 5: Trigger a Pipeline from the Dashboard

On the **CI/CD** page, click **Trigger Pipeline**. The dashboard sends a `workflow_dispatch` event to GitHub (or a pipeline trigger to GitLab).

The triggered pipeline appears in the **Pipeline Runs** list with real-time status updates:

| Status | Meaning |
|--------|---------|
| `pending` | Queued, waiting for a runner |
| `running` | Pipeline is executing |
| `success` | All jobs passed |
| `failed` | One or more jobs failed |

Click a pipeline run to see its details, including a link to the full CI/CD log on GitHub/GitLab.

### Step 6: Set Up Webhooks (Optional)

For real-time status updates without polling, configure a webhook:

**GitHub:**

1. Go to your repo **Settings** > **Webhooks**.
2. Set the Payload URL to `http://your-server:8001/github/webhook/github`.
3. Set Content type to `application/json`.
4. Choose "Workflow runs" as the event.
5. Add a webhook secret and enter the same secret in the dashboard CI/CD settings.

**GitLab:**

1. Go to your project **Settings** > **Webhooks**.
2. Set the URL to `http://your-server:8001/gitlab/webhook/gitlab`.
3. Select "Pipeline events" as the trigger.
4. Add a secret token and enter the same token in the dashboard settings.

!!! warning
    Webhooks require your Quorvex AI server to be accessible from the internet. For local development, use a tunnel service or rely on the dashboard's polling for status updates.

## What You Learned

In this tutorial, you:

- Created a GitHub Actions workflow to run Playwright tests on every push
- Added environment variables for test credentials as repository secrets
- Learned the GitLab CI alternative configuration
- Connected your CI provider to the Quorvex AI dashboard
- Triggered a CI pipeline from the dashboard and tracked its status
- Configured webhooks for real-time pipeline status updates

## Next Steps

- [Dashboard Walkthrough](./dashboard-walkthrough.md) -- explore other dashboard features
- [Regression Testing Guide](../guides/regression-batches.md) -- batch execution and reporting
- [Schedule Automated Runs](../guides/scheduling.md) -- cron-based test execution
- [Environment Variables](../reference/environment-variables.md) -- full configuration reference
