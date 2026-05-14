# Test: Verify button is disabled or blocked when terms checkbox is not checked

## Description
Validates the precondition in REQ-057 that terms acceptance is required before submission can proceed.

## Prerequisites
- Fresh browser session

## Steps
1. Navigate to https://my.gov.az/en/document-serial-number
2. Leave the terms checkbox unchecked
3. Enter "AB123456" into the document number input
4. Attempt to click the Verify button

## Expected Outcome
- Verify button is disabled, OR clicking it does not submit the form
- A clear indication is given that terms must be accepted
- No submission proceeds without terms acceptance

## Test Data
- Target URL: https://my.gov.az/en/serviceCategories/01e3a9be-3f99-41d7-b285-c5238edb4c2f

## Source Evidence
- Source requirement(s): REQ-057, REQ-059
- Source flow(s): Verify Document Authenticity (with valid length input)
