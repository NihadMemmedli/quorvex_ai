# Test: Document verification page is reachable and renders required form controls

## Description
Validates that the document authenticity verification page loads at the expected URL and displays the terms checkbox, document number input, and Verify button.

## Prerequisites
- Fresh browser session

## Steps
1. Navigate to https://my.gov.az/en/document-serial-number
2. Wait for the page to render
3. Verify the terms acceptance checkbox is visible
4. Verify the document number input field is visible
5. Verify the Verify submission button is visible

## Expected Outcome
- Page loads at /en/document-serial-number
- Terms checkbox, document input, and Verify button are all present and visible

## Test Data
- Target URL: https://my.gov.az/en/serviceCategories/01e3a9be-3f99-41d7-b285-c5238edb4c2f

## Source Evidence
- Source requirement(s): REQ-056
- Source flow(s): Verify Document Authenticity (with valid length input)
