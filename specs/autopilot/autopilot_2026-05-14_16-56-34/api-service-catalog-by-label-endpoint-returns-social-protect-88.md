# Test: API: Service catalog by-label endpoint returns Social Protection services

## Description
Direct API contract check on the catalog gateway used by the Social Protection category page.

## Prerequisites
- Fresh browser session

## Steps
1. Navigate to https://my.gov.az/en/serviceCategories/01e3a9be-3f99-41d7-b285-c5238edb4c2f
2. Send GET https://mygov-apigw.e-gov.az/dg-mw-web/dg-catalog/api/v1/services/by-label?label=SOCIAL_PROTECTION
3. Capture status code, headers, and JSON body
4. Parse the services array

## Expected Outcome
- HTTP status is 200
- Response is valid JSON
- Response payload contains a services collection consistent with the 16 services rendered in the UI

## Test Data
- Target URL: https://my.gov.az/en/serviceCategories/01e3a9be-3f99-41d7-b285-c5238edb4c2f

## Source Evidence
- Source requirement(s): REQ-064, REQ-076
- Source flow(s): Browse Social Protection service category
- Observed API endpoint(s): https://mygov-apigw.e-gov.az/dg-mw-web/dg-catalog/api/v1/services/by-label?label=SOCIAL_PROTECTION
