# Test: English locale routes under /en/ resolve to English content

## Description
Validates locale support per REQ-062 by verifying that pages prefixed with /en/ load and render English content consistently.

## Prerequisites
- Fresh browser session

## Steps
1. Navigate to https://my.gov.az/en/serviceCategories/01e3a9be-3f99-41d7-b285-c5238edb4c2f
2. Verify the URL contains the /en/ segment
3. Navigate to https://my.gov.az/en/document-serial-number
4. Verify the URL contains the /en/ segment and English UI labels are rendered

## Expected Outcome
- Both pages load successfully under the /en/ path
- Visible UI labels (e.g., terms checkbox label, Verify button) are in English

## Test Data
- Target URL: https://my.gov.az/en/serviceCategories/01e3a9be-3f99-41d7-b285-c5238edb4c2f

## Source Evidence
- Source requirement(s): REQ-062, REQ-061
