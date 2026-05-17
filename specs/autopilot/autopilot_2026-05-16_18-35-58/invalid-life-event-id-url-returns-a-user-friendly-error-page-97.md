# Test: Invalid life-event ID URL returns a user-friendly error page

## Description
Validates graceful error handling when requesting a non-existent life-event ID, ensuring users see an appropriate fallback rather than unhandled errors.

## Prerequisites
- Fresh browser session

## Steps
1. Navigate to https://my.gov.az/life-events/00000000-0000-0000-0000-000000000000
2. Wait for the response to render
3. Verify the page presents a user-friendly error or fallback

## Expected Outcome
- A user-friendly error page is displayed for the invalid life-event ID
- No raw stack traces or internal error details leak to the user
- Response is gracefully handled by the application

## Test Data
- Target URL: https://my.gov.az/entities/17ceab4a-0cff-41b7-a853-7f2c5c55aef9

## Source Evidence
- Source requirement(s): REQ-083
