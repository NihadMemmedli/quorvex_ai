# Test: Document number input accepts a 16-character value

## Description
Validates the alternate length constraint documented in REQ-058 — that the input accepts 16-character serial values in addition to 8-character ones.

## Prerequisites
- Fresh browser session
- Required test data exists

## Steps
1. Navigate to https://my.gov.az/en/document-serial-number
2. Check the terms acceptance checkbox
3. Enter a 16-character document number (e.g., "AB1234567890CDEF") into the input
4. Click the Verify button

## Expected Outcome
- Input accepts all 16 characters without truncation
- Form submits without a client-side length error
- A user-visible outcome is rendered after submission

## Test Data
- Target URL: https://my.gov.az/en/serviceCategories/01e3a9be-3f99-41d7-b285-c5238edb4c2f

## Source Evidence
- Source requirement(s): REQ-058, REQ-059
- Source flow(s): Verify Document Authenticity (with valid length input)
