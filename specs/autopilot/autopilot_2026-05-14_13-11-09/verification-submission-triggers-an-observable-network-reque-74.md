# Test: Verification submission triggers an observable network request (no silent client-side drop)

## Description
Validates that clicking Verify generates an outgoing request rather than failing silently in the client — directly addressing the gap flagged by REQ-060 and the observed flow's silent-failure description.

## Prerequisites
- Fresh browser session

## Steps
1. Navigate to https://my.gov.az/en/document-serial-number
2. Open browser network monitoring
3. Check the terms acceptance checkbox
4. Enter "AB123456" into the document number input
5. Click the Verify button
6. Inspect the network log for a verification request

## Expected Outcome
- At least one HTTP request is dispatched on Verify click
- The request response status and body are captured
- The UI reflects the response (result, error, or auth prompt) — not a silent no-op

## Test Data
- Target URL: https://my.gov.az/en/serviceCategories/01e3a9be-3f99-41d7-b285-c5238edb4c2f

## Source Evidence
- Source requirement(s): REQ-059, REQ-060
- Source flow(s): Verify Document Authenticity (with valid length input)
