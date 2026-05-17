# Test: SEO metadata endpoint for /document-serial-number should not return 404

## Description
Regression check for the observed broken SEO endpoint returning 404 for the document-serial-number page. Missing SEO metadata harms discoverability and indicates a backend data gap.

## Prerequisites
- Fresh browser session

## Steps
1. Navigate to https://my.gov.az/
2. Issue a GET request to https://mygov-apigw.e-gov.az/dg-mw-web/dg-catalog/api/v1/seo/by-label?label=/document-serial-number
3. Capture the HTTP status code and response body
4. Verify the status is 200 and the body contains SEO metadata fields (title, description, etc.)

## Expected Outcome
- Endpoint returns HTTP 200
- Response body includes non-empty SEO metadata for /document-serial-number

## Test Data
- Target URL: https://my.gov.az/

## Source Evidence
- Source requirement(s): REQ-088
- Source flow(s): Recover from Document Serial Number Verification Error (synthesized)
- Observed API endpoint(s): https://mygov-apigw.e-gov.az/dg-mw-web/dg-catalog/api/v1/seo/by-label?label=/document-serial-number
