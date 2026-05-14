# Test: Document Search rejects invalid-length document numbers

## Description
Negative test: validates that document numbers not equal to 8 or 16 characters trigger the documented validation error post-submit.

## Prerequisites
- Fresh browser session

## Steps
1. Navigate to https://my.gov.az/en/document-search
2. Locate the 'Document number' textbox
3. Enter a 5-character document number (e.g., '12345')
4. Submit the search
5. Observe the validation message
6. Clear the input and enter a 10-character document number
7. Submit the search again
8. Observe the validation message

## Expected Outcome
- Submitting a 5-character document number displays a validation error
- Submitting a 10-character document number displays a validation error
- Validation error states the number must be 8 or 16 characters long
- URL remains on /en/document-search after invalid submissions

## Test Data
- Target URL: https://my.gov.az/en/serviceCategories/01e3a9be-3f99-41d7-b285-c5238edb4c2f

## Source Evidence
- Source requirement(s): REQ-073
- Source flow(s): Document Search verification with length validation
