# Test: Document Verification Input Validation

## Description
The system shall validate the document serial number input to ensure it meets the required length (8 or 16 characters) before submitting for verification.

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
- Document number input rejects values shorter than 8 characters
- Document number input accepts values of exactly 8 characters
- Document number input accepts values of exactly 16 characters
- Document number input rejects values longer than 16 characters (excluding formatting hyphen)
- Clear validation message is displayed for invalid input lengths
- Yoxla (Verify) button cannot be clicked with invalid input

## Test Data
- Target URL: /document-serial-number

## Source Evidence
- Source flow(s): Document Verification
