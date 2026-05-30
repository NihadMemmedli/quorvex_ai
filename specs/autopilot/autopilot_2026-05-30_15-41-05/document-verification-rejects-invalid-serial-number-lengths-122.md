# Test: Document verification rejects invalid serial number lengths

## Description
Validates that the document verification form enforces 8 or 16 character validation, rejecting inputs that are too short or too long, and disabling the Yoxla button for invalid lengths.

## Prerequisites
- Fresh browser session

## Steps
1. Navigate to https://my.gov.az/document-serial-number
2. Check the consent checkbox
3. Enter 7 characters (e.g., '1234567') into the document number input
4. Verify validation error or disabled Yoxla button
5. Clear and enter exactly 8 characters (e.g., '12345678')
6. Verify input is accepted and auto-formatted to '1234-5678'
7. Clear and enter exactly 16 characters
8. Verify input is accepted and formatted
9. Clear and enter 17 characters
10. Verify validation error or disabled Yoxla button

## Expected Outcome
- 7-character input is rejected with validation message or disabled button
- 8-character input is accepted
- 16-character input is accepted
- 17-character input is rejected
- Auto-formatting hyphen does not count toward character length validation

## Test Data
- Target URL: https://my.gov.az/serviceCategories

## Source Evidence
- Source requirement(s): REQ-100, REQ-114
- Source flow(s): Document Verification
