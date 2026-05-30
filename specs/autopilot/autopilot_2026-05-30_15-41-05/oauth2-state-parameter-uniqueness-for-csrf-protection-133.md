# Test: OAuth2 state parameter uniqueness for CSRF protection

## Description
Validates that consecutive OAuth2 authorization requests generate unique state parameters, ensuring CSRF protection is properly implemented.

## Prerequisites
- Fresh browser session

## Steps
1. Open service detail page, trigger login modal, click DAXİL OLUN
2. Capture the state parameter from the OAuth2 redirect URL
3. Navigate back to my.gov.az and repeat the same flow
4. Capture the state parameter from the second OAuth2 redirect URL
5. Compare the two state values

## Expected Outcome
- Each OAuth2 redirect contains a state parameter in UUID format
- State values differ between consecutive requests
- State parameter is not predictable or reused

## Test Data
- Target URL: https://my.gov.az/serviceCategories

## Source Evidence
- Source requirement(s): REQ-117
- Source flow(s): Apply for Government Service
- Observed API endpoint(s): https://mygovid.gov.az/grant-permission?response_type=code&client_id=41333e123d5543ed99d9382ff38b8174&redirect_uri=https://my.gov.az&scope=person%20openid%20certificate%20session%20contact%20user%20document&state=97e7666a-30f8-4b82-9b47-34253eefb21e
