# How to Test Database Quality

PostgreSQL schema analysis and data quality testing with AI-powered check generation, fix suggestions, and an approve/apply workflow.

## Overview

The database testing framework provides:

- **Connection profiles** -- register PostgreSQL databases with encrypted credentials
- **AI schema analysis** -- discover tables, relationships, constraints, and indexes
- **Data quality checks** -- NULL rates, uniqueness, referential integrity, custom SQL
- **AI spec generation** -- auto-generate quality check specs from schema analysis
- **AI fix suggestions** -- get remediation suggestions for failed checks
- **Approve/apply workflow** -- review and apply approved fixes

## Prerequisites

- Quorvex AI installed and running (`make dev` or `make prod-dev`)
- A PostgreSQL database to test (with read access at minimum)
- AI credentials configured in `.env`

## Step-by-Step Usage

### 1. Register a Connection

Navigate to **Database Testing** in the dashboard (`/database-testing`), or use the API:

```bash
curl -X POST http://localhost:8001/database-testing/connections \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Production DB",
    "host": "db.example.com",
    "port": 5432,
    "database": "myapp",
    "username": "readonly_user",
    "password": "secure-password",
    "project_id": "your-project-id"
  }'
```

The password is encrypted at rest. You can register multiple connection profiles.

### 2. Test the Connection

Verify connectivity before running analysis:

```bash
curl -X POST http://localhost:8001/database-testing/connections/CONN_ID/test
```

### 3. Run Schema Analysis

Analyze the database schema:

```bash
curl -X POST http://localhost:8001/database-testing/analyze/CONN_ID \
  -H "Content-Type: application/json" \
  -d '{"project_id": "your-project-id"}'
```

The AI discovers:
- All tables with column types, constraints, and indexes
- Foreign key relationships between tables
- Unique constraints and primary keys
- Table sizes and row counts

This runs as a background job. The results are used to generate quality check specs.

### 4. Write a Data Quality Check Spec

Create a spec manually or let the AI generate one:

**Manual spec:**

```markdown
# Database Quality Check: User Data Integrity

## Connection
Production DB

## Checks

### No NULL emails
- Table: users
- Column: email
- Check: NULL rate = 0%
- Severity: critical

### Unique emails
- Table: users
- Column: email
- Check: uniqueness = 100%
- Severity: critical

### Valid foreign keys
- Table: orders
- Column: user_id
- Check: referential integrity with users.id
- Severity: high

### Recent activity
- Custom SQL: SELECT COUNT(*) FROM users WHERE last_login > NOW() - INTERVAL '90 days'
- Expected: count > 0
- Severity: medium

### No orphaned records
- Table: order_items
- Column: order_id
- Check: referential integrity with orders.id
- Severity: high
```

**AI-generated spec:**

```bash
curl -X POST http://localhost:8001/database-testing/generate-spec \
  -H "Content-Type: application/json" \
  -d '{
    "connection_id": "CONN_ID",
    "project_id": "your-project-id"
  }'
```

The AI analyzes the schema and generates comprehensive quality checks based on the discovered structure.

### 5. Run Quality Checks

Execute checks against the database:

```bash
curl -X POST http://localhost:8001/database-testing/run/CONN_ID \
  -H "Content-Type: application/json" \
  -d '{"project_id": "your-project-id"}'
```

Or run the full pipeline (analyze + generate spec + run checks):

```bash
curl -X POST http://localhost:8001/database-testing/run-full/CONN_ID \
  -H "Content-Type: application/json" \
  -d '{"project_id": "your-project-id"}'
```

### 6. Review Results

View run results and individual check outcomes:

```bash
# List all runs
curl http://localhost:8001/database-testing/runs?project_id=your-project-id

# Project summary
curl http://localhost:8001/database-testing/summary?project_id=your-project-id
```

Each check shows: status (passed/failed/error), actual value, expected value, and severity.

### 7. Get AI Fix Suggestions

For failed checks, request AI-powered fix suggestions:

```bash
curl -X POST http://localhost:8001/database-testing/suggest/RUN_ID \
  -H "Content-Type: application/json" \
  -d '{"project_id": "your-project-id"}'
```

The AI analyzes each failure and suggests:
- SQL remediation queries
- Schema changes (add constraints, indexes)
- Data cleanup scripts
- Process improvements

### 8. Approve and Apply Suggestions

Review suggestions and approve the ones you want to apply:

```bash
curl -X POST http://localhost:8001/database-testing/runs/RUN_ID/approve-suggestions \
  -H "Content-Type: application/json" \
  -d '{
    "approved_suggestion_ids": ["SUGGESTION_1", "SUGGESTION_2"],
    "project_id": "your-project-id"
  }'
```

Only approved suggestions are executed against the database.

## Configuration

No special environment variables are needed beyond the standard AI credentials in `.env`. Database connections are configured per-profile.

Best practices for connection profiles:
- Use a **read-only user** for analysis and quality checks
- Use a user with **write access** only when applying fix suggestions
- Store different profiles for different environments (dev, staging, production)

## API Endpoints Reference

| Method | Path | Description |
|--------|------|-------------|
| POST | `/database-testing/connections` | Create connection profile |
| GET | `/database-testing/connections` | List connections |
| PUT | `/database-testing/connections/{id}` | Update connection |
| DELETE | `/database-testing/connections/{id}` | Delete connection |
| POST | `/database-testing/connections/{id}/test` | Test connection |
| POST | `/database-testing/analyze/{conn_id}` | Schema analysis (background) |
| POST | `/database-testing/run/{conn_id}` | Run quality checks |
| POST | `/database-testing/run-full/{conn_id}` | Full pipeline |
| POST | `/database-testing/suggest/{run_id}` | AI fix suggestions |
| POST | `/database-testing/runs/{run_id}/approve-suggestions` | Apply approved fixes |
| POST | `/database-testing/generate-spec` | AI spec from schema |
| GET | `/database-testing/runs` | Run history |
| GET | `/database-testing/summary` | Project summary |

## Key Files

| Path | Purpose |
|------|---------|
| `orchestrator/api/database_testing.py` | All endpoints |
| `orchestrator/api/models_db.py` | `DbConnection`, `DbTestRun`, `DbTestCheck` models |
| `web/src/app/(dashboard)/database-testing/page.tsx` | Frontend |

## Example Workflow

```
1. Register connection  -->  2. Analyze schema  -->  3. Generate spec
                                                          |
4. Review results  <--  5. Run quality checks  <---------/
       |
6. Get AI suggestions  -->  7. Approve fixes  -->  8. Apply and re-run
```

## Troubleshooting

| Problem | Solution |
|---------|----------|
| Connection test fails | Check host, port, database name, and credentials. Verify network access. |
| Schema analysis timeout | Large databases may take longer. Check `AGENT_TIMEOUT_SECONDS` in `.env`. |
| "Permission denied" on table | The database user needs SELECT permission on the tables being analyzed. |
| Fix suggestions fail to apply | The database user needs appropriate write permissions (ALTER, INSERT, UPDATE). |
| NULL check shows unexpected results | Verify the column name is correct and the table is not empty. |
| AI generates irrelevant checks | Provide more context in the spec or use manual specs for specific tables. |
| Connection password not saved | Check that `JWT_SECRET_KEY` is set in `.env` (used for encryption). |

## Verification

Confirm database testing works:

1. Connection test passes for the registered profile
2. Schema analysis discovers tables, columns, and relationships
3. Quality checks run and return pass/fail results with actual values
4. AI suggestions provide actionable SQL remediation
5. Approved suggestions apply without errors

## Related Guides

- [Credential Management](./credential-management.md) -- secure database connection credentials
- [Scheduling](./scheduling.md) -- automate quality checks on a schedule
- [Troubleshooting](./troubleshooting.md) -- database connection issues
- [Extending](./extending.md) -- add custom check types
