export interface ScenarioTemplate {
    name: string;
    description: string;
    icon: string;
    vus: string;
    duration: string;
    content: string;
}

export const SCENARIO_TEMPLATES: ScenarioTemplate[] = [
    {
        name: 'Smoke Test',
        description: 'Verify basics under minimal load',
        icon: 'smoke',
        vus: '3',
        duration: '30s',
        content: `# Test: Smoke Test

## Type: Load
## Target URL: https://example.com

## Description
Quick smoke test to verify the system is responsive under minimal load.
Validates that key endpoints return successful responses.

## Endpoints
- GET /
- GET /api/health
- GET /api/status

## Load Profile
- Virtual Users: 3
- Duration: 30s
- Ramp Up: 5s

## Thresholds
- http_req_duration p(95) < 500ms
- http_req_failed rate < 0.01
`,
    },
    {
        name: 'Load Test',
        description: 'Typical expected traffic patterns',
        icon: 'load',
        vus: '30',
        duration: '1m',
        content: `# Test: Load Test

## Type: Load
## Target URL: https://example.com

## Description
Simulate typical expected traffic patterns to validate system
handles normal production load with acceptable response times.

## Endpoints
- GET /
- GET /api/users
- GET /api/products
- POST /api/search with body {"query": "test", "page": 1}

## Load Profile
- Virtual Users: 30
- Duration: 1m
- Ramp Up: 10s

## Thresholds
- http_req_duration p(95) < 500ms
- http_req_duration p(99) < 1500ms
- http_req_failed rate < 0.05
`,
    },
    {
        name: 'Stress Test',
        description: 'Find the degradation point under increasing load',
        icon: 'stress',
        vus: '100-200',
        duration: '2m',
        content: `# Test: Stress Test

## Type: Load
## Target URL: https://example.com

## Description
Progressive ramp-up to discover the system degradation point.
Increases load in stages to identify where performance degrades.

## Endpoints
- GET /
- GET /api/users
- POST /api/login with body {"email": "test@example.com", "password": "pass"}
- GET /api/dashboard
- GET /api/reports

## Load Profile
- Virtual Users: 200
- Duration: 2m
- Ramp Up: 30s
- Stages:
  - 30s ramp to 100 VUs
  - 30s hold at 100 VUs
  - 30s ramp to 200 VUs
  - 30s hold at 200 VUs

## Thresholds
- http_req_duration p(95) < 2000ms
- http_req_failed rate < 0.10
`,
    },
    {
        name: 'Spike Test',
        description: 'Sudden burst of traffic to test resilience',
        icon: 'spike',
        vus: '10-200-10',
        duration: '1m',
        content: `# Test: Spike Test

## Type: Load
## Target URL: https://example.com

## Description
Simulates sudden traffic spikes to test system resilience,
auto-scaling capabilities, and recovery behavior.

## Endpoints
- GET /
- GET /api/products
- POST /api/cart with body {"product_id": 1, "quantity": 1}
- POST /api/checkout with body {"payment_method": "card"}

## Load Profile
- Virtual Users: 200
- Duration: 1m
- Ramp Up: 5s
- Stages:
  - 5s ramp to 10 VUs
  - 15s hold at 10 VUs
  - 5s spike to 200 VUs
  - 20s hold at 200 VUs
  - 5s drop to 10 VUs
  - 10s hold at 10 VUs

## Thresholds
- http_req_duration p(95) < 3000ms
- http_req_failed rate < 0.15
`,
    },
    {
        name: 'Soak Test',
        description: 'Sustained load to detect memory leaks and degradation',
        icon: 'soak',
        vus: '40',
        duration: '5m',
        content: `# Test: Soak Test

## Type: Load
## Target URL: https://example.com

## Description
Extended duration test under sustained moderate load to detect memory leaks,
connection pool exhaustion, and gradual performance degradation.

## Endpoints
- GET /
- GET /api/users
- GET /api/products?page=1&limit=20
- POST /api/search with body {"query": "test"}
- GET /api/notifications

## Load Profile
- Virtual Users: 40
- Duration: 5m
- Ramp Up: 30s

## Thresholds
- http_req_duration p(95) < 1000ms
- http_req_duration p(99) < 2000ms
- http_req_failed rate < 0.02
`,
    },
    {
        name: 'Breakpoint Test',
        description: 'Find the failure point by ramping to extreme load',
        icon: 'breakpoint',
        vus: '10-500',
        duration: '3m',
        content: `# Test: Breakpoint Test

## Type: Load
## Target URL: https://example.com

## Description
Continuously ramp up load to find the system breaking point.
Identifies the maximum capacity before failures cascade.

## Endpoints
- GET /
- GET /api/users
- POST /api/login with body {"email": "test@example.com", "password": "pass"}
- GET /api/dashboard
- POST /api/data with body {"payload": "test-data"}

## Load Profile
- Virtual Users: 500
- Duration: 3m
- Ramp Up: 3m
- Stages:
  - 1m ramp to 100 VUs
  - 1m ramp to 300 VUs
  - 1m ramp to 500 VUs

## Thresholds
- http_req_duration p(95) < 5000ms
- http_req_failed rate < 0.50
`,
    },
];
