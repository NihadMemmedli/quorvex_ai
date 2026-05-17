# Test: Invalid entity ID URL returns a user-friendly error page

## Description
Validates graceful error handling when requesting a non-existent entity ID, ensuring the system does not expose stack traces or raw server errors.

## Prerequisites
- Fresh browser session

## Steps
1. Navigate to https://my.gov.az/entities/00000000-0000-0000-0000-000000000000
2. Wait for the response to render
3. Verify a user-friendly error or fallback page is shown

## Expected Outcome
- The page displays a user-friendly error or fallback (e.g., 404 page)
- No raw stack traces or server error details are exposed
- The HTTP response is handled gracefully (not a 5xx with unhandled exception)

## Test Data
- Target URL: https://my.gov.az/entities/17ceab4a-0cff-41b7-a853-7f2c5c55aef9

## Source Evidence
- Source requirement(s): REQ-083
