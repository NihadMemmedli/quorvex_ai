# Test: HTTPBin Demo Load Test

## Type: Load
## Target URL: https://httpbin.org

## Description
Demo load test for presentations and local validation. It exercises public
HTTPBin endpoints with a small staged load profile so the run is safe,
self-contained, and does not require credentials or a local target service.

## Demo Goal
- Confirm the load-testing workflow can discover a spec and matching script.
- Generate representative K6 metrics: response time, throughput, checks, and
  error rate.
- Produce a structured `summary.json` for the existing load-test parser.

## Endpoints
1. GET /get - Basic JSON echo endpoint, 30% of traffic.
2. GET /status/200 - Health-style status endpoint, 20% of traffic.
3. GET /delay/1 - Controlled one-second latency endpoint, 20% of traffic.
4. POST /post with body {"username": "loadtest", "timestamp": "<iso-date>"} - JSON POST echo endpoint, 20% of traffic.
5. GET /headers - Header echo endpoint, 10% of traffic.

## Load Profile
- Virtual Users: 30
- Duration: 50s
- Ramp Up: 10s
- Stages:
  - 10s ramp to 30 VUs
  - 30s hold at 30 VUs
  - 10s ramp down to 0 VUs
- Think Time: 1s between endpoint groups

## Thresholds
- http_req_duration p(95) < 3000ms
- http_req_failed rate < 0.05
- http_reqs rate > 2

## Authentication
No authentication is required.
