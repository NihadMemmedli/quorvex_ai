import http from 'k6/http';
import { check, group, sleep } from 'k6';
import { Counter, Rate, Trend } from 'k6/metrics';

const errorRate = new Rate('errors');
const delayedResponseDuration = new Trend('delayed_response_duration');
const postEchoDuration = new Trend('post_echo_duration');
const successfulReads = new Counter('successful_reads');
const successfulWrites = new Counter('successful_writes');

export const options = {
  stages: [
    { duration: '10s', target: 30 },
    { duration: '30s', target: 30 },
    { duration: '10s', target: 0 },
  ],
  thresholds: {
    http_req_duration: ['p(95)<3000'],
    http_req_failed: ['rate<0.05'],
    http_reqs: ['rate>2'],
  },
};

const BASE_URL = 'https://httpbin.org';

function recordResult(response, successCounter) {
  const ok = response.status >= 200 && response.status < 400;
  errorRate.add(!ok);

  if (ok && successCounter) {
    successCounter.add(1);
  }
}

export default function () {
  const timestamp = new Date().toISOString();

  group('GET /get basic JSON echo', function () {
    const res = http.get(`${BASE_URL}/get`);

    check(res, {
      'GET /get returns 200': (r) => r.status === 200,
      'GET /get returns JSON body': (r) => r.headers['Content-Type']?.includes('application/json'),
      'GET /get response time under 3000ms': (r) => r.timings.duration < 3000,
    });

    recordResult(res, successfulReads);
  });

  sleep(1);

  group('GET /status/200 health-style check', function () {
    const res = http.get(`${BASE_URL}/status/200`);

    check(res, {
      'GET /status/200 returns 200': (r) => r.status === 200,
    });

    recordResult(res, successfulReads);
  });

  sleep(1);

  group('GET /delay/1 controlled latency', function () {
    const startedAt = Date.now();
    const res = http.get(`${BASE_URL}/delay/1`);
    delayedResponseDuration.add(Date.now() - startedAt);

    check(res, {
      'GET /delay/1 returns 200': (r) => r.status === 200,
      'GET /delay/1 includes expected delay': (r) => r.timings.duration >= 1000,
      'GET /delay/1 response time under 3000ms': (r) => r.timings.duration < 3000,
    });

    recordResult(res, successfulReads);
  });

  sleep(1);

  group('POST /post JSON echo', function () {
    const payload = JSON.stringify({
      username: 'loadtest',
      timestamp,
    });
    const params = {
      headers: {
        'Content-Type': 'application/json',
      },
    };

    const startedAt = Date.now();
    const res = http.post(`${BASE_URL}/post`, payload, params);
    postEchoDuration.add(Date.now() - startedAt);

    check(res, {
      'POST /post returns 200': (r) => r.status === 200,
      'POST /post echoes username': (r) => r.body.includes('loadtest'),
      'POST /post echoes timestamp field': (r) => r.body.includes('timestamp'),
    });

    recordResult(res, successfulWrites);
  });

  sleep(1);

  group('GET /headers header echo', function () {
    const res = http.get(`${BASE_URL}/headers`);

    check(res, {
      'GET /headers returns 200': (r) => r.status === 200,
      'GET /headers returns header payload': (r) => r.body.includes('headers'),
    });

    recordResult(res, successfulReads);
  });

  sleep(1);
}

export function handleSummary(data) {
  return {
    'summary.json': JSON.stringify(data, null, 2),
    stdout: JSON.stringify(data, null, 2),
  };
}
