import http from 'k6/http';
import { check, sleep, group } from 'k6';
import { Rate, Trend, Counter } from 'k6/metrics';

// Custom metrics for tracking specific behaviors
const errorRate = new Rate('errors');
const getDelayDuration = new Trend('get_delay_duration');
const postRequestDuration = new Trend('post_request_duration');
const successfulGets = new Counter('successful_gets');
const successfulPosts = new Counter('successful_posts');

// Load test configuration with stages and thresholds
export const options = {
  stages: [
    { duration: '10s', target: 30 },   // Ramp up: gradually increase from 0 to 30 VUs over 10s
    { duration: '30s', target: 30 },   // Steady state: sustain 30 VUs for 30s (simulating 1000 total VUs conceptually)
    { duration: '10s', target: 0 },    // Ramp down: gradually decrease to 0 VUs
  ],
  thresholds: {
    // 95th percentile response time must be under 3000ms
    http_req_duration: ['p(95)<3000'],
    // Error rate must be below 5%
    http_req_failed: ['rate<0.05'],
    // Throughput must be greater than 2 requests per second
    http_reqs: ['rate>2'],
  },
};

// Base URL for the HTTPBin API
const BASE_URL = 'https://httpbin.org';

export default function () {
  // Generate a timestamp for this iteration
  const timestamp = new Date().toISOString();

  group('GET Basic Request', function () {
    const res = http.get(`${BASE_URL}/get`);

    check(res, {
      'status is 200': (r) => r.status === 200,
      'response body is not empty': (r) => r.body.length > 0,
      'response time < 3000ms': (r) => r.timings.duration < 3000,
    });

    // Track successful GET requests
    if (res.status === 200) {
      successfulGets.add(1);
    }

    // Track error rate
    errorRate.add(res.status !== 200);
  });

  sleep(1); // Think time between requests

  group('GET Health Check', function () {
    const res = http.get(`${BASE_URL}/status/200`);

    check(res, {
      'status is 200': (r) => r.status === 200,
    });

    errorRate.add(res.status !== 200);
  });

  sleep(1);

  group('GET Delayed Response', function () {
    const startTime = Date.now();
    const res = http.get(`${BASE_URL}/delay/1`);
    const endTime = Date.now();

    check(res, {
      'status is 200': (r) => r.status === 200,
      'response body is not empty': (r) => r.body.length > 0,
      'response time accounts for delay': (r) => r.timings.duration >= 1000,
    });

    // Track the duration of the delayed endpoint
    getDelayDuration.add(endTime - startTime);
    errorRate.add(res.status !== 200);
  });

  sleep(1);

  group('POST Request with JSON', function () {
    const payload = JSON.stringify({
      username: 'loadtest',
      timestamp: timestamp,
    });

    const params = {
      headers: {
        'Content-Type': 'application/json',
      },
    };

    const startTime = Date.now();
    const res = http.post(`${BASE_URL}/post`, payload, params);
    const endTime = Date.now();

    check(res, {
      'status is 200': (r) => r.status === 200,
      'response body is not empty': (r) => r.body.length > 0,
      'response contains username': (r) => r.body.includes('loadtest'),
      'response contains timestamp': (r) => r.body.includes('timestamp'),
    });

    // Track successful POST requests and duration
    if (res.status === 200) {
      successfulPosts.add(1);
    }
    postRequestDuration.add(endTime - startTime);
    errorRate.add(res.status !== 200);
  });

  sleep(1);

  group('GET Headers', function () {
    const res = http.get(`${BASE_URL}/headers`);

    check(res, {
      'status is 200': (r) => r.status === 200,
      'response body is not empty': (r) => r.body.length > 0,
      'response contains headers': (r) => r.body.includes('User-Agent') || r.body.includes('host'),
    });

    errorRate.add(res.status !== 200);
  });

  sleep(1); // Think time before next iteration
}

// Summary handler for structured JSON output
export function handleSummary(data) {
  return {
    'summary.json': JSON.stringify(data, null, 2),
    stdout: JSON.stringify(data, null, 2),
  };
}
