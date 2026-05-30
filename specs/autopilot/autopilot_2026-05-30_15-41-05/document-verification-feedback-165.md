# Test: Document Verification Feedback

## Description
The system shall display a clear, visible response (success message, error message, or validation feedback) after a document verification form submission, regardless of whether the document number is valid or invalid.

## Prerequisites
- Fresh browser session

## Steps
1. Navigate "https://my.gov.az/document-serial-number" into the URL
2. Observe "Legal disclaimer about document verification liability" into the Consent checkbox
3. Click the Consent checkbox
4. Fill "12345678" into the Document number input
5. Click the Yoxla (Verify) button
6. Observe "Input formatted to 1234-5678 pattern" into the Auto-formatting

## Expected Outcome
- After submitting the verification form, a visible response is displayed on the page
- If the document number format is invalid, a descriptive error message is shown
- If the document is verified successfully, a confirmation message is displayed
- If the document is not found or invalid, an appropriate error message is shown
- The response is clearly visible without requiring page scroll or additional interaction

## Test Data
- Target URL: /document-serial-number

## Source Evidence
- Source flow(s): Document Verification
