# Test: custom-info endpoint should return page-level customization data (not 404)

## Description
Regression check for the observed broken custom-info endpoint returning 404. This endpoint is expected to provide page-level customization data.

## Prerequisites
- Fresh browser session

## Steps
1. Navigate to https://my.gov.az/
2. Issue a GET request to https://mygov-apigw.e-gov.az/dg-mw-web/custom-info
3. Capture the HTTP status code and response payload
4. Verify the response status is 200 and a JSON payload with customization data is returned

## Expected Outcome
- Endpoint returns HTTP 200
- Response contains expected customization data structure

## Test Data
- Target URL: https://my.gov.az/

## Source Evidence
- Observed API endpoint(s): https://mygov-apigw.e-gov.az/dg-mw-web/custom-info
