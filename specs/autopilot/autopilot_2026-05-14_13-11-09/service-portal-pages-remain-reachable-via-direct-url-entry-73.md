# Test: Service portal pages remain reachable via direct URL entry

## Description
Validates REQ-061 — that the multi-page portal supports direct URL access without navigation errors, which is important for deep links and bookmarking.

## Prerequisites
- Fresh browser session

## Steps
1. Open a fresh browser session with no prior navigation
2. Navigate directly to https://my.gov.az/en/serviceCategories/01e3a9be-3f99-41d7-b285-c5238edb4c2f
3. Verify the page loads successfully
4. Navigate directly to https://my.gov.az/en/document-serial-number
5. Verify the page loads successfully

## Expected Outcome
- Both direct-entry URLs return successful page loads
- No 404 or navigation error is displayed
- URL pattern /en/{route} resolves consistently

## Test Data
- Target URL: https://my.gov.az/en/serviceCategories/01e3a9be-3f99-41d7-b285-c5238edb4c2f

## Source Evidence
- Source requirement(s): REQ-061, REQ-055, REQ-056
