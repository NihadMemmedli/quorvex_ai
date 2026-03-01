# API Overview

REST API conventions for Quorvex AI. For the full endpoint catalog, see [API Endpoints](api-endpoints.md).

## Base URL

```
http://localhost:8001
```

## Interactive Documentation

| URL | Format |
|-----|--------|
| `http://localhost:8001/docs` | Swagger UI |
| `http://localhost:8001/redoc` | ReDoc |
| `http://localhost:8001/openapi.json` | OpenAPI JSON |

## Authentication

Authentication is optional by default (`REQUIRE_AUTH=false`). When enabled, the API uses JWT bearer tokens.

### Token Flow

1. `POST /auth/register` (if `ALLOW_REGISTRATION=true`)
2. `POST /auth/login` returns access token + refresh token
3. Include `Authorization: Bearer <access_token>` on requests
4. `POST /auth/refresh` with refresh token to get new access token

### Token Lifetimes

| Token | TTL | Notes |
|-------|-----|-------|
| Access token | 15 minutes | Short-lived, stateless JWT |
| Refresh token | 7 days | Single-use with rotation; reuse revokes all sessions |

### Token Payload

| Field | Description |
|-------|-------------|
| `sub` | User ID |
| `exp` | Expiration timestamp |
| `type` | `access` or `refresh` |
| `jti` | Unique token ID |

Algorithm: HS256. Secret: `JWT_SECRET_KEY` environment variable.

### Password Requirements

Minimum 8 characters, at least one uppercase letter, one lowercase letter, one digit, and one special character.

### Account Lockout

5 consecutive failed login attempts locks the account for 30 minutes.

### User Roles

| Role | Capabilities |
|------|-------------|
| `owner` | Full project control including deletion |
| `admin` | Manage members, run tests, edit specs |
| `editor` | Run tests, edit specs |
| `viewer` | Read-only access |

Superusers have full access to all projects and `/users` admin endpoints.

## Request Format

Content type: `application/json` (file uploads use `multipart/form-data`).

### Common Query Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `project_id` | string | `null` | Filter by project. `"default"` includes legacy data. |
| `limit` | int | varies | Page size for paginated endpoints |
| `offset` | int | 0 | Items to skip for pagination |

### Path Parameters

Spec names and folder paths use FastAPI `{name:path}` syntax, allowing slashes: `GET /specs/folder/subfolder/my-test.md`

## Response Format

### Success

Single resource:
```json
{"id": "...", "status": "passed"}
```

Paginated list:
```json
{"items": [...], "total": 142, "limit": 20, "offset": 0, "has_more": true}
```

### Error Codes

| Code | Meaning |
|------|---------|
| 200 | Success |
| 201 | Created |
| 400 | Bad request |
| 404 | Resource not found |
| 409 | Conflict (duplicate resource) |
| 413 | Payload too large (file uploads > 5 MB) |
| 422 | Validation error |
| 429 | Rate limit exceeded |
| 500 | Internal server error |
| 504 | Gateway timeout |

### Error Response Shape

```json
{"detail": "Spec not found"}
```

Validation errors (422):
```json
{"detail": [{"loc": ["body", "field"], "msg": "field required", "type": "value_error.missing"}]}
```

## Rate Limiting

Backend: [slowapi](https://github.com/laurentS/slowapi) with Redis (production) or in-memory (development).

### Global Default

1000 requests per hour per IP address (or per authenticated user ID).

### Per-Endpoint Limits

| Endpoint | Limit |
|----------|-------|
| `POST /auth/login` | 10/minute |
| `POST /auth/register` | 3/minute |
| `POST /auth/refresh` | 30/minute |
| `POST /projects` | 10/minute |
| `POST /runs` | 30/minute |
| `POST /runs/bulk` | 5/minute |
| `POST /exploration/start` | 5/minute |
| `POST /exploration/{id}/stop` | 10/minute |

### Rate Limit Key

Authenticated user ID when available, otherwise client IP address.

## Pagination

| Endpoint | Default Limit | Max Limit |
|----------|---------------|-----------|
| `GET /runs` | 20 | 100 |
| `GET /specs` | 50 | 200 |
| `GET /specs/automated` | 50 | 100 |
| `GET /regression/batches` | 20 | 100 |

## Server-Sent Events

| Endpoint | Description |
|----------|-------------|
| `GET /runs/{id}/log/stream` | Streams execution log lines |
| `GET /api/prd/{project_id}/generation/{id}/log/stream` | Streams PRD generation logs |

Stream terminates on: terminal status, 10 minutes inactivity, or server error.

## File Upload Constraints

| Constraint | Value |
|------------|-------|
| Max file size | 5 MB |
| Allowed MIME types | `text/csv`, `application/csv`, `text/markdown`, `text/plain` |

## CORS

Configured via `ALLOWED_ORIGINS` environment variable (comma-separated). Default: `http://localhost:3000`.

## Request Logging

Every request receives an `X-Request-ID` header (UUID) for traceability.

## Router Organization

| Router | Prefix | Source File |
|--------|--------|-------------|
| Auth | `/auth` | `auth.py` |
| Users | `/users` | `users.py` |
| Projects | `/projects` | `projects.py` |
| Exploration | `/exploration` | `exploration.py` |
| Requirements | `/requirements` | `requirements.py` |
| RTM | `/rtm` | `rtm.py` |
| Regression | `/regression` | `regression.py` |
| Scheduling | `/scheduling` | `scheduling.py` |
| API Testing | `/api-testing` | `api_testing.py` |
| Load Testing | `/load-testing` | `load_testing.py` |
| Security Testing | `/security-testing` | `security_testing.py` |
| Database Testing | `/database-testing` | `database_testing.py` |
| LLM Testing | `/llm-testing` | `llm_testing.py` |
| Memory | `/api/memory` | `memory.py` |
| PRD | `/api/prd` | `prd.py` |
| Health | `/health` | `health.py` |
| TestRail | `/testrail` | `testrail.py` |
| GitHub CI | `/github` | `github_ci.py` |
| GitLab CI | `/gitlab` | `gitlab_ci.py` |
| Jira | `/jira` | `jira.py` |
| Analytics | `/analytics` | `analytics.py` |
| Chat | `/chat` | `chat.py` |
| Dashboard | *(none)* | `dashboard.py` |
| Settings | *(none)* | `settings.py` |
| Core (specs, runs, etc.) | *(none)* | `main.py` |

## Related

- [API Endpoints](api-endpoints.md)
- [Environment Variables](environment-variables.md)
