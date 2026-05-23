# How to Add a Backend Runtime Capability

![Workflow monitor for backend runtime capability development](../assets/ui/workflow.png)

<p class="caption">Workflow monitor for backend runtime capability development.</p>


How to add a backend feature that creates durable state, runs asynchronously, or appears in the dashboard.

## Prerequisites

- You understand the relevant domain model.
- Local backend tests can run.
- You have checked [API Router and Service Map](../reference/api-router-service-map.md).

## Step 1: Choose the Ownership Boundary

Pick one primary owner before writing code.

| Capability shape | Preferred owner |
|------------------|-----------------|
| HTTP-only CRUD for an existing domain | Existing router module |
| New product domain | New router in `orchestrator/api/` |
| Reusable business behavior | New or existing service in `orchestrator/services/` |
| Generated artifact or test pipeline | Workflow module in `orchestrator/workflows/` |
| Durable workflow or pause/resume execution | Custom workflow or Temporal-backed service |
| High-volume or worker-isolated execution | Redis queue and worker pattern |

Do not put reusable business logic directly in a route handler when more than one route, worker, or assistant tool will need it.

## Step 2: Define Persistence

If the capability needs durable status, history, analytics, or recovery, add a model in `orchestrator/api/models_db.py`.

Use an Alembic migration for PostgreSQL-visible schema changes:

```bash
make db-migrate M="add my capability"
make db-upgrade
```

Update `docs/reference/database-schema.md` when the model is public or operationally important.

## Step 3: Add the Router Contract

Add request and response models to the router module. Keep route handlers responsible for:

- auth and project dependencies
- request validation
- service calls
- response shaping
- HTTP error mapping

Register new routers in `orchestrator/api/main.py`.

## Step 4: Add the Service or Workflow

Put domain logic in a service or workflow module.

| Need | Use |
|------|-----|
| Synchronous reusable logic | `orchestrator/services/` |
| AI generation or parsing pipeline | `orchestrator/workflows/` |
| External API client | `orchestrator/services/*_client.py` |
| Long-running job state | service plus persisted job/run model |
| Worker isolation | Redis queue and worker module |
| Durable pause/resume/cancel | Temporal workflow or custom workflow runner |

Services should return structured results and avoid embedding HTTP-specific exceptions unless the service is intentionally API-only.

## Step 5: Expose Status and Recovery

Long-running capabilities should expose:

- a start endpoint that returns a stable ID
- a status endpoint
- terminal states
- cancellation when safe
- persisted error messages
- cleanup or retry behavior when workers can crash

If the capability uses browser capacity, queue capacity, storage, or external providers, include it in the relevant health or observability path.

## Step 6: Connect the Dashboard

When the capability is user-facing:

1. Add or update a page under `web/src/app/(dashboard)/`.
2. Use `apiUrl()` and `fetchWithAuth()`.
3. Use project context for project-scoped data.
4. Add sidebar and command palette entries when the page should be discoverable.
5. Add loading, empty, error, and terminal states.

Use [Adding a Dashboard Feature](adding-dashboard-feature.md) for the frontend details.

## Step 7: Update Documentation

| Change | Documentation |
|--------|---------------|
| New route | `docs/reference/api-endpoints.md` |
| New router or service boundary | `docs/reference/api-router-service-map.md` |
| New model | `docs/reference/database-schema.md` |
| New environment variable | `docs/reference/environment-variables.md` |
| New dashboard page | `docs/reference/web-dashboard.md` |
| New operational behavior | explanation or operations guide |
| New contributor pattern | guide under `docs/guides/` |

## Verification

1. Unit or API tests cover the route/service behavior.
2. Migration applies with `make db-upgrade`.
3. New status and error states are visible in the dashboard or API.
4. Startup and shutdown do not leave orphaned running state.
5. `make docs-check` passes after documentation updates.

## Related

- [Extending the System](extending.md)
- [API Router and Service Map](../reference/api-router-service-map.md)
- [Backend Runtime Lifecycle](../explanation/backend-runtime-lifecycle.md)
- [Queue and Worker Architecture](../explanation/queue-worker-architecture.md)
- [Database Migration Architecture](../explanation/database-migration-architecture.md)
- [Adding a Dashboard Feature](adding-dashboard-feature.md)
