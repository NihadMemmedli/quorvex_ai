# Test: Internal routing stability across discovered entity, life-event, and service pages

## Description
Validates that the three key discovered pages (entity, life-event, service) load without 404 or 5xx errors, exercising URL structure consistency across the my.gov.az domain.

## Prerequisites
- Fresh browser session

## Steps
1. Navigate to https://my.gov.az/entities/17ceab4a-0cff-41b7-a853-7f2c5c55aef9 and verify success
2. Navigate to https://my.gov.az/life-events/1b72c5b6-dcc6-415c-81bd-f8e23869b10c and verify success
3. Navigate to https://my.gov.az/services/etibranameye-xitam-erizesi?serviceLabel=AFTOPOA and verify success

## Expected Outcome
- All three URLs return successful (2xx) HTTP responses
- No 404 or 5xx errors are produced for these canonical paths
- URL structures for /entities/, /life-events/, and /services/ remain consistent

## Test Data
- Target URL: https://my.gov.az/entities/17ceab4a-0cff-41b7-a853-7f2c5c55aef9

## Source Evidence
- Source requirement(s): REQ-082
- Source flow(s): Navigate to Power of Attorney Termination Service (synthesized)
