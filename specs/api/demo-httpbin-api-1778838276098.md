# Test: HTTPBin Demo API

## Type: API
## Base URL: https://httpbin.org
## Auth: None

## Description
Demo API coverage for stable HTTPBin endpoints. This verifies common request/response behavior without needing user credentials.

## Steps
1. GET /get
2. Verify response status is 200
3. Verify response body has "url" field
4. POST /post with body {"name": "Quorvex Demo", "source": "chatbot"}
5. Verify response status is 200
6. Verify response body.json.name equals "Quorvex Demo"
7. GET /status/204
8. Verify response status is 204
9. GET /status/404
10. Verify response status is 404

## Expected Outcome
- The API accepts GET and POST requests.
- JSON request bodies are echoed correctly.
- Success and error status endpoints return the expected status codes.
