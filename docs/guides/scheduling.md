# How to Schedule Automated Test Runs

Set up cron-based schedules for recurring test execution, with execution history tracking and monitoring.

## Prerequisites

- Quorvex AI installed and running (`make dev` or `make prod-dev`)
- At least one test spec or regression batch configured
- PostgreSQL database (schedules are persisted via SQLAlchemy job store)

## Step 1: Create a Schedule

### Via Dashboard

1. Navigate to **Schedules** in the dashboard (`/schedules`)
2. Click **New Schedule**
3. Configure the schedule:
   - **Name** -- descriptive name (e.g., "Nightly Regression")
   - **Cron Expression** -- when to run (e.g., `0 2 * * *` for 2 AM daily)
   - **Specs** -- select which specs or batches to run
   - **Project** -- the project context
4. Click **Create**

### Via API

```bash
curl -X POST http://localhost:8001/scheduling/your-project-id/schedules \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Nightly Regression",
    "cron_expression": "0 2 * * *",
    "spec_ids": ["spec-1", "spec-2"],
    "enabled": true
  }'
```

## Step 2: Validate the Cron Expression

Before creating a schedule, verify your cron expression:

```bash
curl -X POST http://localhost:8001/scheduling/validate-cron \
  -H "Content-Type: application/json" \
  -d '{"expression": "0 2 * * *"}'
```

Common cron expressions:

| Expression | Schedule |
|-----------|----------|
| `0 2 * * *` | Daily at 2:00 AM |
| `0 9 * * 1-5` | Weekdays at 9:00 AM |
| `0 */6 * * *` | Every 6 hours |
| `0 0 * * 0` | Weekly on Sunday at midnight |
| `0 0 1 * *` | Monthly on the 1st at midnight |

## Step 3: Preview Upcoming Runs

Check when the next executions will occur:

```bash
curl http://localhost:8001/scheduling/your-project-id/schedules/SCHEDULE_ID/next-runs
```

This returns the next 5 scheduled execution times.

## Step 4: Monitor Execution History

### Via Dashboard

1. Navigate to **Schedules**
2. Click on a schedule to view its execution history
3. Each execution shows: start time, end time, status, and linked batch/run results

### Via API

```bash
curl http://localhost:8001/scheduling/your-project-id/schedules/SCHEDULE_ID/executions
```

## Step 5: Enable or Disable a Schedule

Toggle a schedule without deleting it:

### Via Dashboard

Click the **Enable/Disable** toggle on the schedule card.

### Via API

```bash
curl -X POST http://localhost:8001/scheduling/your-project-id/schedules/SCHEDULE_ID/toggle
```

## Step 6: Trigger an Immediate Run

Run a schedule now without waiting for the next cron trigger:

```bash
curl -X POST http://localhost:8001/scheduling/your-project-id/schedules/SCHEDULE_ID/run-now
```

This creates an execution immediately while keeping the regular schedule intact.

## Step 7: Update or Delete a Schedule

```bash
# Update
curl -X PUT http://localhost:8001/scheduling/your-project-id/schedules/SCHEDULE_ID \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Updated Nightly Regression",
    "cron_expression": "0 3 * * *"
  }'

# Delete
curl -X DELETE http://localhost:8001/scheduling/your-project-id/schedules/SCHEDULE_ID
```

## Scheduler Architecture

The scheduling system uses APScheduler with:

- **SQLAlchemy job store** -- jobs persist across backend restarts
- **Job coalescing** -- missed runs merge into one (if the server was down)
- **Max 1 instance** -- prevents overlapping executions of the same schedule
- **5-minute misfire grace time** -- jobs that missed their window by less than 5 minutes still execute

!!! note
    LLM testing has its own scheduling system within the LLM Testing module. See [LLM Testing](./llm-testing.md) for LLM-specific schedules.

## Verification

Confirm scheduling works:

1. Schedule appears in the dashboard with the correct cron expression
2. Next-runs preview shows expected dates
3. Manual "Run Now" creates an execution entry
4. After the scheduled time passes, a new execution appears in history
5. Check backend logs for scheduler activity:
   ```bash
   make prod-logs | grep -i scheduler
   ```

## Related Guides

- [Regression Batches](./regression-batches.md) -- create batches to schedule
- [LLM Testing](./llm-testing.md) -- LLM-specific scheduled runs
- [Integrations](./integrations.md) -- sync scheduled results to TestRail
- [Troubleshooting](./troubleshooting.md) -- diagnose scheduler issues
