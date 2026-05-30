# Test: Document verification submit button disabled without consent

## Description
Validates that the Yoxla (Verify) button cannot be clicked when the legal consent checkbox is unchecked, even if a valid document number is entered.

## Prerequisites
- Fresh browser session

## Steps
1. Navigate to https://my.gov.az/document-serial-number
2. Do NOT check the consent checkbox
3. Enter a valid 8-character document serial number
4. Verify Yoxla (Verify) button is disabled or not clickable
5. Check the consent checkbox
6. Verify Yoxla button becomes enabled

## Expected Outcome
- Yoxla button is disabled when consent is not given
- Yoxla button becomes enabled only after both consent is checked and valid input is provided

## Test Data
- Target URL: https://my.gov.az/serviceCategories

## Source Evidence
- Source requirement(s): REQ-112
- Source flow(s): Document Verification
