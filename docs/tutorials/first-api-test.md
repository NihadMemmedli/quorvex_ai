# Your First API Test

In this tutorial, you will create an API test spec, import it into Quorvex AI, generate Playwright-based HTTP tests, and run them -- all without a browser.

## Prerequisites

- Quorvex AI installed and configured (complete [Your First Test in 10 Minutes](./getting-started.md) first)
- The dashboard running (`make dev` or `make prod-dev` for Docker)

!!! note
    API tests use Playwright's HTTP request library, not browser automation. No Playwright MCP server or browser instance is needed.

## Step 1: Start the Dashboard

Launch the backend API and frontend:

```bash
make dev
```

Open `http://localhost:3000` in your browser. You should see the Quorvex AI dashboard.

!!! tip
    If you are using Docker, run `make prod-dev` instead. This starts the full production stack (backend, frontend, PostgreSQL) with local code mounting so changes auto-reload.

## Step 2: Navigate to API Testing

Click **API Testing** in the left sidebar. The API Testing page has two tabs:

| Tab | Purpose |
|-----|---------|
| **Specs** | Manage API test specifications |
| **Runs** | View execution history and logs |

## Step 3: Create an API Test Spec

Click **New Spec** to create a test manually. Enter the following:

- **Name**: `jsonplaceholder-posts`
- **Folder**: `api` (or leave as default)

In the spec editor, paste this content:

```markdown title="specs/api/jsonplaceholder-posts/spec.md"
# API Test: JSONPlaceholder Posts

## Description
Validate the JSONPlaceholder REST API for the /posts resource.

## Base URL
https://jsonplaceholder.typicode.com

## Tests

### GET /posts
- Send a GET request to /posts
- Verify the response status is 200
- Verify the response body is a JSON array
- Verify the array contains 100 items

### GET /posts/1
- Send a GET request to /posts/1
- Verify the response status is 200
- Verify the response body contains "userId", "id", "title", "body"
- Verify "id" equals 1

### POST /posts
- Send a POST request to /posts with body:
  - title: "Test Post"
  - body: "This is a test"
  - userId: 1
- Verify the response status is 201
- Verify the response body contains "id"

### PUT /posts/1
- Send a PUT request to /posts/1 with body:
  - id: 1
  - title: "Updated Title"
  - body: "Updated body"
  - userId: 1
- Verify the response status is 200
- Verify the response body "title" equals "Updated Title"

### DELETE /posts/1
- Send a DELETE request to /posts/1
- Verify the response status is 200
```

Click **Save**.

!!! tip
    API specs follow the same markdown format as UI specs, but use HTTP verbs (GET, POST, PUT, DELETE) instead of browser actions (click, navigate, fill).

## Step 4: Import an OpenAPI Spec (Alternative)

If you have an OpenAPI/Swagger specification, you can import it instead of writing specs manually.

Click the **Import OpenAPI** button on the API Testing page. You can either:

- **Paste a URL** to an OpenAPI JSON/YAML file
- **Upload a file** from your computer

The importer parses the OpenAPI spec and creates individual API test specs for each endpoint.

!!! note
    OpenAPI import creates one spec per endpoint group (e.g., all `/posts` operations become one spec). You can edit the generated specs to add custom assertions.

## Step 5: Generate Tests

On the API Testing page, find your `jsonplaceholder-posts` spec and click the **Run** button (play icon).

The system starts a background job that:

1. Reads your API spec
2. Generates Playwright API test code using AI
3. Executes the generated tests
4. Self-heals if any test fails (up to 3 attempts)

You can monitor progress in the **Runs** tab. The status shows:

| Status | Meaning |
|--------|---------|
| `queued` | Waiting to start |
| `running` | AI is generating or executing tests |
| `passed` | All tests passed |
| `failed` | One or more tests failed after healing attempts |
| `error` | Pipeline error (check logs) |

## Step 6: Review the Results

Once the run completes, click on it in the **Runs** tab to see the details:

- **Generated Code** -- the Playwright API test that was produced
- **Test Output** -- stdout/stderr from the test execution
- **Status** -- pass/fail for each test case

The generated test looks similar to:

```typescript title="tests/generated/jsonplaceholder-posts.spec.ts"
import { test, expect } from '@playwright/test';

test.describe('JSONPlaceholder Posts API', () => {
  const baseURL = 'https://jsonplaceholder.typicode.com';

  test('GET /posts returns all posts', async ({ request }) => {
    const response = await request.get(`${baseURL}/posts`);
    expect(response.status()).toBe(200);
    const posts = await response.json();
    expect(Array.isArray(posts)).toBeTruthy();
    expect(posts.length).toBe(100);
  });

  test('GET /posts/1 returns a single post', async ({ request }) => {
    const response = await request.get(`${baseURL}/posts/1`);
    expect(response.status()).toBe(200);
    const post = await response.json();
    expect(post).toHaveProperty('userId');
    expect(post).toHaveProperty('id');
    expect(post).toHaveProperty('title');
    expect(post).toHaveProperty('body');
    expect(post.id).toBe(1);
  });

  test('POST /posts creates a new post', async ({ request }) => {
    const response = await request.post(`${baseURL}/posts`, {
      data: { title: 'Test Post', body: 'This is a test', userId: 1 }
    });
    expect(response.status()).toBe(201);
    const post = await response.json();
    expect(post).toHaveProperty('id');
  });

  // ... PUT and DELETE tests
});
```

## Step 7: Run API Tests from the CLI

You can also run API tests from the command line:

```bash
source venv/bin/activate
python orchestrator/cli.py specs/api/jsonplaceholder-posts/spec.md
```

Or run the generated test directly with Playwright:

```bash
npx playwright test tests/generated/jsonplaceholder-posts.spec.ts
```

Expected output:

```
Running 5 tests using 1 worker

  PASSED  GET /posts returns all posts (1.2s)
  PASSED  GET /posts/1 returns a single post (0.8s)
  PASSED  POST /posts creates a new post (0.9s)
  PASSED  PUT /posts/1 updates a post (0.7s)
  PASSED  DELETE /posts/1 deletes a post (0.6s)

  5 passed (4.5s)
```

## What You Learned

In this tutorial, you:

- Created an API test spec in markdown describing HTTP endpoints and assertions
- Used the dashboard to manage API test specs
- Learned the alternative OpenAPI import workflow
- Generated and ran Playwright API tests without a browser
- Reviewed test results in the dashboard and on the command line

## Next Steps

- [App Exploration and Requirements](./first-exploration.md) -- let AI discover your app and generate requirements
- [API Testing Guide](../guides/api-testing.md) -- authentication, headers, chained requests, and more
- [CI/CD Setup](./ci-cd-setup.md) -- run API tests automatically in your CI pipeline
