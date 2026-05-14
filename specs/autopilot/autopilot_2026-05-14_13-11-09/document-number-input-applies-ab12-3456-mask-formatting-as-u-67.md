# Test: Document number input applies AB12-3456 mask formatting as user types

## Description
Validates the input masking behavior observed during exploration — that an 8-character entry like AB123456 is visually formatted to AB12-3456.

## Prerequisites
- Fresh browser session

## Steps
1. Navigate to https://my.gov.az/en/document-serial-number
2. Type "AB123456" into the document number input one character at a time
3. Read the displayed value of the input

## Expected Outcome
- Input displays the value formatted as AB12-3456
- Underlying raw value is preserved for submission

## Test Data
- Target URL: https://my.gov.az/en/serviceCategories/01e3a9be-3f99-41d7-b285-c5238edb4c2f

## Source Evidence
- Source requirement(s): REQ-058
- Source flow(s): Verify Document Authenticity (with valid length input)
