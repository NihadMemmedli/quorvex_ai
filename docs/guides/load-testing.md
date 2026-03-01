# How to Run Load Tests

Run K6-based load tests with AI-generated scripts, distributed execution across worker containers, real-time metrics monitoring, and run comparison.

## Overview

The load testing framework provides:

- **AI script generation** -- converts markdown specs into K6 JavaScript
- **Local and distributed execution** -- run locally or across K6 worker containers
- **Real-time monitoring** -- live metrics including response times, throughput, and error rates
- **Run comparison** -- overlay charts comparing multiple test runs
- **Exclusive locking** -- only one load test runs at a time; browser operations are paused during load tests
- **Safety limits** -- configurable VU caps and duration limits

## Prerequisites

- Quorvex AI installed and running (`make dev` or `make prod-dev`)
- [K6](https://k6.io/docs/get-started/installation/) installed (for local execution)
- Docker (for distributed worker execution)
- A target application/API to load test

## Step-by-Step Usage

### 1. Create a Load Test Spec

Write a markdown specification describing the load test:

```markdown
# Load Test: User API Performance

## Target
https://api.example.com

## Scenario
Simulate 50 concurrent users hitting the user endpoints for 2 minutes.

## Configuration
- Virtual Users: 50
- Duration: 2m
- Ramp-up: 30s

## Endpoints
1. GET /api/users - List users (60% of traffic)
2. GET /api/users/1 - Get single user (30% of traffic)
3. POST /api/users - Create user (10% of traffic)

## Thresholds
- 95th percentile response time < 500ms
- Error rate < 1%
- Requests per second > 100

## Authentication
Bearer token via Authorization header.
Use environment variable {{API_TOKEN}}.
```

Save via the dashboard at `/load-testing` or the API:

```bash
curl -X POST http://localhost:8001/load-testing/specs \
  -H "Content-Type: application/json" \
  -d '{
    "name": "user-api-perf",
    "content": "# Load Test: User API Performance\n...",
    "project_id": "your-project-id"
  }'
```

### 2. Generate the K6 Script

Click **Generate** in the dashboard, or:

```bash
curl -X POST http://localhost:8001/load-testing/specs/user-api-perf/generate \
  -H "Content-Type: application/json" \
  -d '{"project_id": "your-project-id"}'
```

The AI reads your spec and produces a K6 JavaScript file with proper stages, thresholds, and request distribution.

### 3. Run the Load Test

Click **Run** in the dashboard, or:

```bash
curl -X POST http://localhost:8001/load-testing/specs/user-api-perf/run \
  -H "Content-Type: application/json" \
  -d '{"project_id": "your-project-id"}'
```

The system acquires an exclusive lock (pausing all browser operations), then executes K6.

### 4. Monitor in Real-Time

Poll the status endpoint for live metrics:

```bash
curl http://localhost:8001/load-testing/runs/RUN_ID/status
```

The dashboard shows live charts for:
- Response time percentiles (p50, p90, p95, p99)
- Requests per second
- Error rate
- HTTP status code breakdown
- Timeseries data

### 5. Stop a Running Test

```bash
curl -X POST http://localhost:8001/load-testing/runs/RUN_ID/stop
```

### 6. Compare Runs

Compare multiple runs side-by-side:

```bash
curl "http://localhost:8001/load-testing/runs/compare?run_ids=RUN_1,RUN_2"
```

The dashboard provides overlay charts for visual comparison.

## Distributed Execution

For higher load, use K6 worker containers:

```bash
# Start K6 workers
make k6-workers-up

# Scale to more workers
make k6-workers-scale N=3

# Check worker health
make k6-workers-status

# Stop workers
make k6-workers-down
```

When Redis and K6 workers are available, tests automatically use distributed mode. The `k6_queue.py` service distributes work across workers via a Redis task queue.

## Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `K6_MAX_VUS` | `1000` | Safety limit on virtual users |
| `K6_MAX_DURATION` | `5m` | Maximum test duration |
| `K6_TIMEOUT_SECONDS` | `3600` | Process timeout (1 hour) |
| `REDIS_URL` | -- | Required for distributed execution |

## Exclusive Lock System

Only one load test can run at a time. When a load test starts:

1. An exclusive lock is acquired (Redis-based or in-memory)
2. The browser pool is paused -- no UI tests, explorations, or agents can start
3. The lock has a 2-hour TTL as a safety net
4. When the load test completes, the lock is released and browser operations resume

This prevents resource contention between load tests and browser-based operations.

## API Endpoints Reference

| Method | Path | Description |
|--------|------|-------------|
| POST | `/load-testing/specs` | Create load test spec |
| GET | `/load-testing/specs` | List specs |
| GET | `/load-testing/specs/{folder}` | Get spec details |
| PUT | `/load-testing/specs/{folder}` | Update spec |
| DELETE | `/load-testing/specs/{folder}` | Delete spec |
| POST | `/load-testing/specs/{folder}/generate` | Generate K6 script |
| POST | `/load-testing/specs/{folder}/run` | Execute load test |
| GET | `/load-testing/runs` | List runs |
| GET | `/load-testing/runs/{run_id}/status` | Real-time status with metrics |
| POST | `/load-testing/runs/{run_id}/stop` | Cancel running test |
| GET | `/load-testing/runs/compare` | Compare multiple runs |
| GET | `/load-testing/system-limits` | Resource caps and worker status |

## Key Files

| Path | Purpose |
|------|---------|
| `orchestrator/api/load_testing.py` | API endpoints |
| `orchestrator/workflows/load_test_generator.py` | AI K6 script generation |
| `orchestrator/workflows/load_test_runner.py` | K6 execution and metrics parsing |
| `orchestrator/services/load_test_lock.py` | Exclusive lock (pauses browser pool) |
| `orchestrator/services/k6_queue.py` | Redis queue for distributed execution |
| `orchestrator/services/k6_worker.py` | Worker process |

## Troubleshooting

| Problem | Solution |
|---------|----------|
| "Load test lock is held" | Another load test is running. Wait or check for stuck jobs. |
| K6 not found | Install K6: `brew install k6` (macOS) or use Docker workers |
| VU limit exceeded | Increase `K6_MAX_VUS` in `.env` (default: 1000) |
| Duration limit exceeded | Increase `K6_MAX_DURATION` in `.env` (default: 5m) |
| Workers not picking up tasks | Check Redis connectivity and worker health: `make k6-workers-status` |
| Browser tests blocked during load test | Expected behavior -- the exclusive lock pauses browser operations |
| Metrics not updating | Ensure the K6 process is running: check logs via `make prod-logs` |

## Verification

Confirm load testing works:

1. The spec appears in the dashboard Load Testing page
2. K6 script generation produces a valid JavaScript file
3. Running the test shows live metrics (response times, RPS, error rate)
4. After completion, the run appears in history with aggregated results
5. Run comparison shows overlay charts when comparing two or more runs

## Related Guides

- [API Testing](./api-testing.md) -- functional API test generation
- [Security Testing](./security-testing.md) -- security scan your endpoints
- [Scheduling](./scheduling.md) -- automate load tests on a schedule
- [Deployment](./deployment.md) -- scale K6 workers in production
