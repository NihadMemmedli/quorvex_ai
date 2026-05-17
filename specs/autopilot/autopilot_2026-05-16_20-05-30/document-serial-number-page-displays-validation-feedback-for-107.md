# Test: Document serial number page displays validation feedback for invalid input

## Description
Validates that the /document-serial-number page provides validation feedback when invalid data is submitted, as required by REQ-088.

## Prerequisites
- Fresh browser session
- Required test data exists

## Steps
1. Navigate to https://my.gov.az/document-serial-number
2. Wait for the verification form to render
3. Submit the form with empty or clearly invalid serial number input
4. Verify a validation error message is displayed to the user
5. Verify the page remains on /document-serial-number

## Expected Outcome
- Form submission with invalid input does not navigate away
- A visible validation error message is displayed
- The user can still interact with the form to correct the input

## Test Data
- Target URL: https://my.gov.az/

## Source Evidence
- Source requirement(s): REQ-088
- Source flow(s): Recover from Document Serial Number Verification Error (synthesized)
