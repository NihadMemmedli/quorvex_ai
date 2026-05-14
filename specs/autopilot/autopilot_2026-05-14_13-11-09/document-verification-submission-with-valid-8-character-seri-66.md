# Test: Document verification submission with valid 8-character serial produces a user-visible outcome

## Description
Validates the end-to-end submission path observed during exploration and asserts that a visible result or error message is displayed — addressing the silent-failure gap noted in REQ-060.

## Prerequisites
- Fresh browser session
- Required test data exists

## Steps
1. Navigate to https://my.gov.az/en/document-serial-number
2. Check the terms acceptance checkbox
3. Enter "AB123456" into the document number input
4. Click the Verify button
5. Wait for a response to render

## Expected Outcome
- Input is masked to display as AB12-3456
- Form submission is accepted (no client-side blocking)
- A user-visible verification result, error message, or authentication prompt is displayed (no silent failure)

## Test Data
- Target URL: https://my.gov.az/en/serviceCategories/01e3a9be-3f99-41d7-b285-c5238edb4c2f

## Source Evidence
- Source requirement(s): REQ-057, REQ-058, REQ-059, REQ-060
- Source flow(s): Verify Document Authenticity (with valid length input)
