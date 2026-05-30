# Test: Document verification with consent checkbox and auto-formatting

## Description
Validates the document verification happy path: consent must be checked, input auto-formats with hyphen (1234-5678), and submission triggers a verification result.

## Prerequisites
- Fresh browser session
- Required test data exists

## Steps
1. Navigate to https://my.gov.az/document-serial-number
2. Verify legal consent checkbox with disclaimer is displayed
3. Verify Yoxla (Verify) button is disabled before consent is checked
4. Check the consent checkbox
5. Type '12345678' into the document serial number input
6. Verify input auto-formats to '1234-5678' with hyphen
7. Click Yoxla (Verify) button
8. Observe verification result is displayed

## Expected Outcome
- Consent checkbox must be checked before verification is possible
- Input auto-formats with hyphen at the 4th character position
- 8-character input is accepted and submitted successfully
- Verification result or feedback is displayed after submission

## Test Data
- Target URL: https://my.gov.az/serviceCategories

## Source Evidence
- Source requirement(s): REQ-100, REQ-111, REQ-112
- Source flow(s): Document Verification
- Observed API endpoint(s): https://mygov-apigw.e-gov.az/dg-mw-web/dg-catalog/api/v1/faq/by-source?sourceType=PDF_DOC_NUMBER&deviceType=WEB
