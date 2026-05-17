# Test: Support page is accessible without authentication

## Description
Validates that anonymous (unauthenticated) users can reach /support and use the FAQ hub, as required by REQ-090.

## Prerequisites
- Fresh browser session

## Steps
1. Open a fresh browser context with no stored authentication
2. Navigate to https://my.gov.az/support
3. Verify the page loads successfully (no redirect to login)
4. Verify the FAQ hub heading and category chips are visible
5. Click an FAQ item and verify it expands

## Expected Outcome
- /support is reachable without authentication
- No login redirect occurs
- FAQ hub is fully interactive for anonymous users

## Test Data
- Target URL: https://my.gov.az/

## Source Evidence
- Source requirement(s): REQ-090, REQ-084
- Source flow(s): Browse Help/FAQ by Category
