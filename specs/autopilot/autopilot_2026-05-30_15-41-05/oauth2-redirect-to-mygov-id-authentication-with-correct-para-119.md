# Test: OAuth2 redirect to mygov ID authentication with correct parameters

## Description
Validates that clicking DAXİL OLUN in the login modal redirects to mygovid.gov.az/auth with a valid OAuth2 authorization code flow including response_type=code, client_id, redirect_uri, proper scopes (person, openid, certificate, session, contact, user, document), and unique state parameter.

## Prerequisites
- Fresh browser session

## Steps
1. Open the login modal on a service detail page
2. Click DAXİL OLUN (Login) button
3. Verify browser is redirected to https://mygovid.gov.az/auth
4. Intercept or inspect the redirect URL parameters
5. Verify response_type=code is present
6. Verify client_id is present and non-empty
7. Verify redirect_uri=https://my.gov.az
8. Verify scope includes: person, openid, certificate, session, contact, user, document
9. Verify state parameter is present and unique (UUID format)

## Expected Outcome
- Redirect lands on https://mygovid.gov.az/auth
- All OAuth2 required parameters are present in the authorization URL
- State parameter is a unique UUID for CSRF protection
- Scopes cover the expected 7 permission areas

## Test Data
- Target URL: https://my.gov.az/serviceCategories

## Source Evidence
- Source requirement(s): REQ-095, REQ-096, REQ-117
- Source flow(s): Apply for Government Service, Navigation: service_categories to login (inferred)
- Observed API endpoint(s): https://mygovid.gov.az/grant-permission?response_type=code&client_id=41333e123d5543ed99d9382ff38b8174&redirect_uri=https://my.gov.az&scope=person%20openid%20certificate%20session%20contact%20user%20document&state=97e7666a-30f8-4b82-9b47-34253eefb21e
