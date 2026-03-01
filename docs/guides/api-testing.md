# How to Test REST APIs

Test HTTP/REST APIs without browser automation. Import OpenAPI specs or write test specs manually, then let AI generate and heal Playwright-based API tests.

## Overview

The API testing framework provides:

- **OpenAPI/Swagger import** -- parse specs into structured API test definitions
- **AI-powered test generation** -- generates Playwright API test code from specs
- **Self-healing** -- automatically fixes failing tests without browser tools
- **Background execution** -- run tests as background jobs with status tracking
- **Run history** -- database-backed results with detailed logs

Unlike UI testing, API tests use Playwright's HTTP request capabilities (not a browser). No Playwright MCP server or browser instance is needed.

## Prerequisites

- Quorvex AI installed and running (`make dev` or `make prod-dev`)
- An API endpoint to test (or an OpenAPI/Swagger spec file)
- AI credentials configured in `.env`

## Step-by-Step Usage

### 1. Import an OpenAPI Spec

If you have an OpenAPI/Swagger specification:

1. Navigate to **API Testing** in the web dashboard (`/api-testing`)
2. Click **Import OpenAPI**
3. Upload your `openapi.json` or `openapi.yaml` file
4. The system parses endpoints, request/response schemas, and authentication requirements
5. API test specs are generated and stored in `specs/api/`

Via the API:

```bash
curl -X POST http://localhost:8001/api-testing/import-openapi \
  -H "Content-Type: multipart/form-data" \
  -F "file=@openapi.json" \
  -F "project_id=your-project-id"
```

### 2. Write an API Test Spec Manually

Create a markdown file describing the API tests:

```markdown
# API Test: User Management

## Base URL
https://api.example.com/v1

## Authentication
Bearer token via Authorization header.
Use environment variable {{API_TOKEN}}.

## Tests

### GET /users
- Send GET request to /users
- Verify response status is 200
- Verify response contains an array of user objects
- Each user should have id, email, and name fields

### POST /users
- Send POST request to /users with body:
  - name: "Test User"
  - email: "test@example.com"
- Verify response status is 201
- Verify response contains the created user with an id

### GET /users/{id}
- Send GET request to /users/1
- Verify response status is 200
- Verify response contains user details

### DELETE /users/{id}
- Send DELETE request to /users/1
- Verify response status is 204
```

Save this via the dashboard or the API:

```bash
curl -X POST http://localhost:8001/api-testing/specs \
  -H "Content-Type: application/json" \
  -d '{
    "name": "user-management",
    "content": "# API Test: User Management\n...",
    "project_id": "your-project-id"
  }'
```

### 3. Run the API Test

From the dashboard, click the **Run** button on any API spec. The system:

1. AI reads the spec and generates Playwright API test code (`native_api_generator.py`)
2. Tests execute via Playwright (HTTP requests, no browser)
3. If tests fail, `native_api_healer.py` analyzes failures and fixes the code
4. Results are stored in the database

Via the API:

```bash
curl -X POST http://localhost:8001/api-testing/specs/user-management/run \
  -H "Content-Type: application/json" \
  -d '{"project_id": "your-project-id"}'
```

### 4. View Results

Check run history in the dashboard or via API:

```bash
# List all runs
curl http://localhost:8001/api-testing/runs?project_id=your-project-id

# Get specific run details
curl http://localhost:8001/api-testing/runs/RUN_ID
```

## Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `AGENT_TIMEOUT_SECONDS` | `1800` | Timeout for API test generation/healing agents |
| `BASE_URL` | -- | Default base URL for API tests |

Store API credentials in `.env` and reference them in specs:

```bash
# .env
API_TOKEN=your-bearer-token
API_KEY=your-api-key
```

Reference in spec: `Use environment variable {{API_TOKEN}}`

## API Endpoints Reference

| Method | Path | Description |
|--------|------|-------------|
| POST | `/api-testing/specs` | Create API test spec |
| GET | `/api-testing/specs` | List API test specs |
| GET | `/api-testing/specs/{folder}` | Get spec details |
| PUT | `/api-testing/specs/{folder}` | Update spec |
| DELETE | `/api-testing/specs/{folder}` | Delete spec |
| POST | `/api-testing/import-openapi` | Import OpenAPI/Swagger spec |
| POST | `/api-testing/specs/{folder}/run` | Run API test (background job) |
| GET | `/api-testing/runs` | List run history |
| GET | `/api-testing/runs/{run_id}` | Get run details with logs |

## Key Differences from UI Testing

| Aspect | UI Testing | API Testing |
|--------|-----------|-------------|
| Browser | Required (Chromium/Firefox) | Not needed |
| Playwright MCP | Used for exploration | Not used |
| Specs location | `specs/` | `specs/api/` |
| Healer | Uses browser debug tools | Pure code analysis |
| Speed | Minutes per test | Seconds per test |

## Key Files

| Path | Purpose |
|------|---------|
| `orchestrator/api/api_testing.py` | API endpoints |
| `orchestrator/workflows/native_api_generator.py` | AI test generation |
| `orchestrator/workflows/native_api_healer.py` | AI test healing |
| `orchestrator/workflows/openapi_processor.py` | OpenAPI spec parsing |

## Troubleshooting

| Problem | Solution |
|---------|----------|
| Import fails on large OpenAPI spec | Split into smaller specs or use `--feature` flag |
| Generated test uses wrong base URL | Ensure base URL is specified in the spec or `BASE_URL` env var |
| Authentication errors in tests | Verify credential placeholders (`{{VAR}}`) match `.env` keys |
| Timeout during generation | Increase `AGENT_TIMEOUT_SECONDS` in `.env` |
| Test healing loops | Check that the API endpoint is actually reachable from the server |

## Verification

Confirm API testing works end-to-end:

1. The spec is visible in the dashboard API Testing page or via `GET /api-testing/specs`
2. A run completes with status `passed` or `failed` (not `error`)
3. Run details include generated test code and execution logs
4. Running the generated test directly passes:
   ```bash
   npx playwright test tests/generated/api-*.spec.ts
   ```

## Related Guides

- [Writing Specs](./writing-specs.md) -- general spec format
- [Load Testing](./load-testing.md) -- performance test your APIs
- [Security Testing](./security-testing.md) -- scan API endpoints for vulnerabilities
- [Credential Management](./credential-management.md) -- manage API tokens securely
