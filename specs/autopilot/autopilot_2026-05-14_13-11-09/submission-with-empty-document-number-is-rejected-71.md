# Test: Submission with empty document number is rejected

## Description
Validates that the required-field constraint on the document number input (REQ-058) prevents empty submissions.

## Prerequisites
- Fresh browser session

## Steps
1. Navigate to https://my.gov.az/en/document-serial-number
2. Check the terms acceptance checkbox
3. Leave the document number input empty
4. Click the Verify button

## Expected Outcome
- Submission is blocked
- A required-field indication is displayed to the user

## Test Data
- Target URL: https://my.gov.az/en/serviceCategories/01e3a9be-3f99-41d7-b285-c5238edb4c2f

## Source Evidence
- Source requirement(s): REQ-058, REQ-059
- Source flow(s): Verify Document Authenticity (with valid length input)
