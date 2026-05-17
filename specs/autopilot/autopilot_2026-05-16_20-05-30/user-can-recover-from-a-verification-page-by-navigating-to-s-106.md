# Test: User can recover from a verification page by navigating to /support

## Description
Validates the cross-page navigation path from the document serial number verification page to the Help & Support hub, including that the FAQ hub loads cleanly without leftover error state.

## Prerequisites
- Fresh browser session

## Steps
1. Navigate to https://my.gov.az/document-serial-number
2. Verify the page loads without server errors
3. Navigate to https://my.gov.az/support
4. Verify the Help & Support FAQ hub loads with the 'Kömək və dəstək' heading
5. Verify all 6 category chips are visible
6. Verify no error message from the previous page is shown

## Expected Outcome
- /document-serial-number returns a successful response (not a server error)
- Navigation to /support succeeds as a standard page transition
- /support displays the FAQ hub with all 6 categories
- No residual error state is carried over from the verification page

## Test Data
- Target URL: https://my.gov.az/

## Source Evidence
- Source requirement(s): REQ-088, REQ-089, REQ-090
- Source flow(s): Recover from Document Serial Number Verification Error (synthesized)
