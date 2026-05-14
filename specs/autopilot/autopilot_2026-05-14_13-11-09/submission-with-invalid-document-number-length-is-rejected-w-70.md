# Test: Submission with invalid document number length is rejected with a user-visible message

## Description
Validates negative-path handling for inputs that violate the 8/16-character length constraint — covering REQ-058 and the no-silent-failure expectation in REQ-060.

## Prerequisites
- Fresh browser session

## Steps
1. Navigate to https://my.gov.az/en/document-serial-number
2. Check the terms acceptance checkbox
3. Enter a 5-character value (e.g., "AB123") into the document number input
4. Click the Verify button

## Expected Outcome
- Submission is blocked or returns a visible validation error
- Error message indicates the required length constraint
- No silent failure occurs

## Test Data
- Target URL: https://my.gov.az/en/serviceCategories/01e3a9be-3f99-41d7-b285-c5238edb4c2f

## Source Evidence
- Source requirement(s): REQ-058, REQ-059, REQ-060
- Source flow(s): Verify Document Authenticity (with valid length input)
