# Test: Entity detail page loads successfully at entry URL

## Description
Validates that the primary entry point entity detail page renders successfully and returns a healthy HTTP response, serving as the starting point for exploring related life-events and services.

## Prerequisites
- Fresh browser session

## Steps
1. Navigate to https://my.gov.az/entities/17ceab4a-0cff-41b7-a853-7f2c5c55aef9
2. Wait for the page to finish loading
3. Verify the page renders without errors

## Expected Outcome
- The entity detail page responds with a successful HTTP status (2xx)
- The page renders main content without console errors
- No raw stack traces or unhandled exceptions are visible

## Test Data
- Target URL: https://my.gov.az/entities/17ceab4a-0cff-41b7-a853-7f2c5c55aef9

## Source Evidence
- Source requirement(s): REQ-078
