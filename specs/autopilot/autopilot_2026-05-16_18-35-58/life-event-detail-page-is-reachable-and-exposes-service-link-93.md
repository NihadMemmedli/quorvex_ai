# Test: Life-event detail page is reachable and exposes service links

## Description
Validates that the life-event detail page loads correctly and exposes navigable links to related services, including the Power of Attorney Termination service.

## Prerequisites
- Fresh browser session

## Steps
1. Navigate to https://my.gov.az/life-events/1b72c5b6-dcc6-415c-81bd-f8e23869b10c
2. Wait for the page to finish loading
3. Verify the link labeled 'Etibarnaməyə xitam ərizəsi' is visible

## Expected Outcome
- The life-event detail page returns a successful HTTP response
- The link 'Etibarnaməyə xitam ərizəsi' is rendered and clickable
- The page exposes other navigable links to related services

## Test Data
- Target URL: https://my.gov.az/entities/17ceab4a-0cff-41b7-a853-7f2c5c55aef9

## Source Evidence
- Source requirement(s): REQ-079
- Source flow(s): Navigate to Power of Attorney Termination Service (synthesized)
