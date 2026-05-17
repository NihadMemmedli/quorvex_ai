# Test: Service detail page enforces serviceLabel query parameter context

## Description
Validates that omitting the serviceLabel query parameter from the service detail URL is handled correctly, either by loading default content or by presenting a clear fallback.

## Prerequisites
- Fresh browser session

## Steps
1. Navigate to https://my.gov.az/services/etibranameye-xitam-erizesi (without serviceLabel)
2. Wait for the page to render
3. Observe whether the page loads, redirects, or shows a fallback

## Expected Outcome
- The page either renders successfully or shows a user-friendly fallback
- No raw stack traces or unhandled exceptions are displayed
- Behavior is consistent and graceful

## Test Data
- Target URL: https://my.gov.az/entities/17ceab4a-0cff-41b7-a853-7f2c5c55aef9

## Source Evidence
- Source requirement(s): REQ-080, REQ-081
