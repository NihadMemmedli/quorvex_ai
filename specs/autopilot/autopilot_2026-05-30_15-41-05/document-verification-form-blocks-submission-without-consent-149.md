# Test: Document verification form blocks submission without consent checkbox

## Description
Validates that the Check button cannot submit the form when the consent checkbox is unchecked, even if a document number is entered.

## Prerequisites
- Fresh browser session

## Steps
1. Navigate to https://my.gov.az/document-serial-number
2. Do NOT check the consent checkbox
3. Enter a document number in the input field
4. Click the 'Yoxla' (Check) button
5. Verify no form submission occurs (no network request, no page change)
6. Now check the consent checkbox
7. Clear the document number field
8. Click the 'Yoxla' button again
9. Verify no form submission occurs with empty document number

## Expected Outcome
- Form cannot be submitted without consent checkbox checked
- Form cannot be submitted with empty document number even with consent checked
- Both conditions must be met for the form to be submittable

## Test Data
- Target URL: https://my.gov.az/serviceCategories

## Source Evidence
- Source requirement(s): REQ-127
- Source flow(s): Document Verification with Invalid Number
