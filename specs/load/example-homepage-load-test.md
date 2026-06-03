# Load Test: WeTravel Pre-production Homepage Browsing

## Objective
Simulate 50 concurrent users browsing the WeTravel pre-production homepage to measure response times, throughput, and error rates under load.

## Target
- **URL:** https://pre.wetravel.to/

## Load Profile
- **Virtual Users:** 50
- **Duration:** 2 minutes (2m)
- **Ramp-up:** Gradual (default)

## Scenario: Browse Homepage

### Step 1: Navigate to Homepage
- Send GET request to https://pre.wetravel.to/
- Assert response status is 200
- Measure page load time

### Step 2: Verify Page Content
- Assert response body contains valid HTML structure
- Measure total response time

## Success Criteria
- Response time (p95) < 3 seconds
- Error rate < 1%
- Throughput > 10 requests/second
