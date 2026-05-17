# Test: Power of Attorney Termination service detail page reachable via direct URL

## Description
Validates that the service detail page can be accessed directly via its canonical URL with the AFTOPOA service label, without requiring navigation from the life-event page.

## Prerequisites
- Fresh browser session

## Steps
1. Navigate directly to https://my.gov.az/services/etibranameye-xitam-erizesi?serviceLabel=AFTOPOA
2. Wait for the page to finish loading
3. Verify the page renders content associated with the AFTOPOA service

## Expected Outcome
- The service detail page returns a successful HTTP response
- Page content corresponding to the AFTOPOA service label is rendered
- No error or fallback page is shown

## Test Data
- Target URL: https://my.gov.az/entities/17ceab4a-0cff-41b7-a853-7f2c5c55aef9

## Source Evidence
- Source requirement(s): REQ-081
