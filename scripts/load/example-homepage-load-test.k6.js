import http from 'k6/http';
import { check, sleep, group } from 'k6';
import { Rate, Trend, Counter } from 'k6/metrics';

// Custom metrics
const errorRate = new Rate('errors');
const homepageDuration = new Trend('homepage_duration');
const homepageRequests = new Counter('homepage_requests');

// Load profile: 50 VUs, 2 minutes total, gradual ramp-up
export const options = {
  stages: [
    { duration: '30s', target: 50 },   // Gradual ramp-up to 50 VUs
    { duration: '1m', target: 50 },     // Steady state at 50 VUs
    { duration: '30s', target: 0 },     // Ramp-down to 0
  ],
  thresholds: {
    http_req_duration: ['p(95)<3000'],   // p95 response time < 3 seconds
    http_req_failed: ['rate<0.01'],      // Error rate < 1%
    errors: ['rate<0.01'],               // Custom error rate < 1%
    homepage_duration: ['p(95)<3000'],   // Homepage-specific p95 < 3s
  },
};

const BASE_URL = 'https://pre.wetravel.to';

export default function () {
  // Step 1 & 2: Navigate to Homepage and Verify Page Content
  group('Browse Homepage', function () {
    homepageRequests.add(1);

    const res = http.get(`${BASE_URL}/`, {
      tags: { endpoint: 'homepage' },
    });

    homepageDuration.add(res.timings.duration);

    const passed = check(res, {
      'homepage status is 200': (r) => r.status === 200,
      'homepage response time < 3s': (r) => r.timings.duration < 3000,
      'response contains valid HTML': (r) =>
        r.body &&
        (r.body.includes('<html') || r.body.includes('<!DOCTYPE')),
      'response body is not empty': (r) => r.body && r.body.length > 0,
    });

    errorRate.add(!passed);

    if (!passed) {
      console.warn(
        `Homepage check failed | status=${res.status} duration=${res.timings.duration}ms`
      );
    }
  });

  // Simulate realistic user think time (1-3 seconds)
  sleep(Math.random() * 2 + 1);
}

// Structured JSON summary output
export function handleSummary(data) {
  return {
    'summary.json': JSON.stringify(data, null, 2),
  };
}
